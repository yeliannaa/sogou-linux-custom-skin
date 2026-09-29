#!/usr/bin/env python3
"""Build a private installer from local Sogou resources; never install/reload."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from archive_tools import build
from bundle import fingerprint

ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / 'profiles/sogou-4.2.1.145.json'
SYSTEM = Path('/opt/sogoupinyin/files/share/resources/skin')
NATIVE = Path('/opt/sogoupinyin/files/lib/libSogouIme.so')
FILES = ('bundle.py', 'archive_tools.py', 'install.sh', 'uninstall.sh', 'LICENSE')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(name):
    rel = Path(name)
    if rel.is_absolute() or '..' in rel.parts or '\\' in name or not rel.parts:
        raise ValueError('Unsafe relative path: ' + name)
    return rel


def local_files(folder):
    if not folder.exists():
        return {}
    result = {}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            raise ValueError('Theme symlinks are unsupported: ' + str(path))
        if path.is_file():
            name = path.relative_to(folder).as_posix()
            safe_name(name)
            result[name] = path.read_bytes()
    return result


def update_xml(data, changes):
    root = ET.fromstring(data)
    for name, attributes in changes.items():
        matches = [root] if name == '$window' else [e for e in root.iter() if e.get('name') == name]
        if len(matches) != 1:
            raise ValueError('XML control not uniquely found: ' + name)
        for key, value in attributes.items():
            matches[0].set(key, str(value))
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def overlay_for(source, theme, meta):
    replacements = local_files(theme / 'overlay')
    for name in replacements:
        if not name.startswith('ime/'):
            raise ValueError('Only ime/ overlay members are supported: ' + name)
    with ZipFile(io.BytesIO(source)) as z:
        for name, updates in meta.get('updates', {}).items():
            safe_name(name)
            if not name.startswith('ime/') or not name.endswith('.xml'):
                raise ValueError('XML updates must name ime/*.xml members')
            replacements[name] = update_xml(replacements.get(name, z.read(name)), updates)
        if meta.get('v_mode'):
            key = 'ime/wndComp_vertical.xml'
            updates = dict(meta['v_mode'])
            updates['$window'] = updates.pop('window')
            replacements['ime/wndComp_vmode.xml'] = update_xml(replacements.get(key, z.read(key)), updates)
    for name, data in replacements.items():
        if name.endswith(('.svg', '.xml')):
            ET.fromstring(data)
    return replacements


def generate(args):
    profile = json.loads(args.profile.read_text(encoding='utf-8'))
    if set(profile['skins']) != {'尊贵黑金', '尊贵黑金-Compositing'}:
        raise ValueError('This installer manages exactly the two documented skin slots')
    theme = args.theme.resolve()
    meta = json.loads((theme / 'theme.json').read_text(encoding='utf-8'))
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', meta['name']):
        raise ValueError('Theme name must be a short lowercase identifier')
    out = args.out.absolute()
    if out.exists() or out.is_symlink():
        raise ValueError('Output exists; choose a new directory (nothing will be replaced)')
    if args.with_native_fixes and args.profile.resolve() != PROFILE.resolve():
        raise ValueError('Native fixes require the audited built-in profile; adapt and audit C sources first')
    if digest(args.native.read_bytes()) != profile['native_sha256']:
        raise ValueError('Native library does not match profile; follow docs/ADAPTATION.md')
    # Validate all inputs before compiling or creating an output directory.
    skins, svg_paths = {}, set()
    for name, expected in profile['skins'].items():
        safe_name(name)
        nested = args.skin_root / name / (name + '.zip')
        source_path = nested if nested.exists() else args.skin_root / (name + '.zip')
        source = source_path.read_bytes()
        if digest(source) != expected['source_sha256'] or len(source) != expected['size'] or fingerprint(source) != expected['native_hash']:
            raise ValueError('Expected pristine matching skin: ' + name + '; use your original backup, not an active custom slot')
        replacements = overlay_for(source, theme, meta)
        if args.with_native_fixes:
            key = 'ime/wndComp_vmode.xml'
            if key not in replacements or ET.fromstring(replacements[key]).get('minheight') != '300':
                raise ValueError('V-mode patch requires dedicated wndComp_vmode.xml with minheight=300')
            horizontal = replacements.get('ime/wndComp.xml')
            if horizontal is not None and ET.fromstring(horizontal).get('minheight') == '300':
                raise ValueError('Regular layout must not use the V-mode marker minheight=300')
        for key, data in replacements.items():
            if b'@@ASSET_DIR@@' in data:
                if not key.endswith('.svg') or data.count(b'@@ASSET_DIR@@') != 1:
                    raise ValueError('Use exactly one @@ASSET_DIR@@ placeholder per image SVG')
                svg_paths.add(key)
        skins[name] = build(source, replacements)
    assets = local_files(theme / 'assets')
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.skin-build-', dir=str(out.parent)))
    try:
        patches = {}
        if args.with_native_fixes:
            for source, filename, libs in (
                ('status_screen_fix.c', 'status-screen-fix.so', ['-lX11', '-ldl']),
                ('v_mode_fix.c', 'v-mode-fix.so', ['-ldl']),
            ):
                target = stage / filename
                subprocess.run(['gcc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                                str(ROOT / 'src' / source), '-o', str(target)] + libs, check=True)
                patches[filename] = target.read_bytes()
                target.unlink()
        with ZipFile(str(stage / 'resources.zip'), 'w', compression=ZIP_DEFLATED) as payload:
            def write_payload(name, data):
                info = ZipInfo(name)
                info.compress_type = ZIP_DEFLATED
                payload.writestr(info, data)
            for name, data in sorted(assets.items()):
                write_payload('assets/' + name, data)
            for name, data in sorted(patches.items()):
                write_payload('patches/' + name, data)
            for name, data in skins.items():
                write_payload('skins/' + name + '.zip', data)
        for name in FILES:
            shutil.copyfile(str(ROOT / name), str(stage / name))
        (stage / 'src').mkdir()
        launcher = (ROOT / 'src/start-template.sh').read_text(encoding='utf-8')
        for placeholder, value in (
            ('NATIVE', profile['native_sha256']),
            ('STATUS', digest(patches['status-screen-fix.so']) if patches else 'disabled'),
            ('VMODE', digest(patches['v-mode-fix.so']) if patches else 'disabled'),
        ):
            launcher = launcher.replace('@@' + placeholder + '_SHA256@@', value)
        (stage / 'src/start-template.sh').write_text(launcher, encoding='utf-8')
        file_list = list(FILES) + ['resources.zip', 'src/start-template.sh']
        output_meta = dict(profile)
        output_meta.update({
            'bundle_id': 'sogou-custom-' + meta['name'] + '-' + digest((stage / 'resources.zip').read_bytes())[:16],
            'python_minimum': '3.6', 'svg_paths': sorted(svg_paths),
            'patches': {name: digest(data) for name, data in patches.items()},
            'files': {name: digest((stage / name).read_bytes()) for name in file_list},
        })
        (stage / 'manifest.json').write_text(json.dumps(output_meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        shutil.copyfile(str(ROOT / 'docs/INSTALL.md'), str(stage / 'README.md'))
        (stage / 'SHA256SUMS').write_text(''.join(digest(f.read_bytes()) + '  ' + f.relative_to(stage).as_posix() + '\n'
                                                  for f in sorted(stage.rglob('*')) if f.is_file()), encoding='utf-8')
        os.rename(str(stage), str(out))
    except BaseException:
        shutil.rmtree(str(stage))
        raise
    print('Built private installer: ' + str(out))
    print('No installed skin/configuration was changed; no input method was restarted.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--theme', type=Path, default=ROOT / 'examples/minimal')
    parser.add_argument('--profile', type=Path, default=PROFILE)
    parser.add_argument('--skin-root', type=Path, default=SYSTEM, help='Installed skin root or flat directory of original backups')
    parser.add_argument('--native', type=Path, default=NATIVE)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/minimal')
    parser.add_argument('--with-native-fixes', action='store_true', help='Compile the profile-specific bottom-position and V-mode hooks')
    args = parser.parse_args()
    try:
        generate(args)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, 'Build stopped: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
