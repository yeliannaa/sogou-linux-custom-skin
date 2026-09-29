import json
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from zipfile import ZipFile, ZipInfo
import zlib
import xml.etree.ElementTree as ET

import ssf_import


CONFIG = '''[General]
skin_name=Example Skin
skin_email=private-author@example.org
[Display]
font_size=16
font_ch=Example Windows Font
pinyin_color=0x408080
zhongwen_first_color=0x804000
zhongwen_color=0x408080
[Scheme_H1]
pic=horizontal.png
layout_horizontal=0,100,100
layout_vertical=0,30,30
pinyin_marge=20,8,100,40
zhongwen_marge=5,5,100,40
anchor=25,6
[Scheme_V1]
pic=vertical.png
layout_horizontal=0,40,40
layout_vertical=0,40,40
pinyin_marge=20,8,40,40
zhongwen_marge=5,5,40,40
[StatusBar]
pic=status.png
cn_en_display=1
cn_en_pos=20,20
menu_pos=50,20
'''


def png(width, height):
    """Create an original solid-color PNG fixture in memory; no copied artwork."""
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    data = (b'\0' + b'\x80\x80\x80\xff' * width) * height
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(data)) + chunk(b'IEND', b''))


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'sample.ssf'
        self.out = self.root / 'draft'

    def make_ssf(self, config=CONFIG, encoding='utf-8', prefix='', extra=None):
        self.data = {'Skin.ini': config.encode(encoding), 'horizontal.png': png(450, 150),
                     'vertical.png': png(250, 300), 'status.png': png(200, 200)}
        with ZipFile(str(self.source), 'w') as z:
            for name, data in self.data.items():
                z.writestr(prefix + name, data)
            for name, data in (extra or {}).items():
                z.writestr(name, data)

    def test_zip_to_theme_with_unchanged_images_and_no_private_email(self):
        self.make_ssf()
        report = ssf_import.import_theme(self.source, self.out)
        self.assertEqual(set(report['layouts']), {'horizontal', 'vertical', 'status'})
        self.assertTrue(report['native_v_layout_ready'])
        self.assertEqual(report['status'], 'needs-review')
        copied = [p.read_bytes() for p in (self.out / 'assets').iterdir()]
        self.assertEqual(set(copied), {self.data[n] for n in ('horizontal.png', 'vertical.png', 'status.png')})
        horizontal = ET.parse(str(self.out / 'overlay/ime/wndComp.xml')).getroot()
        self.assertEqual(horizontal.get('bkimage'), 'skin1.svg,100,250,30,90')
        self.assertEqual(horizontal.find("CompString").get('margin'), '20,8,100,40')
        self.assertEqual(ET.parse(str(self.out / 'overlay/ime/wndComp_vmode.xml')).getroot().get('minheight'), '300')
        for p in self.out.rglob('*'):
            if p.is_file():
                self.assertNotIn(b'private-author@example.org', p.read_bytes())

    def test_unicode_encoding_and_nested_case_insensitive_paths(self):
        config = CONFIG.replace('Example Skin', '测试皮肤').replace('horizontal.png', 'HORIZONTAL.PNG')
        self.make_ssf(config, encoding='utf-16', prefix='nested/')
        report = ssf_import.import_theme(self.source, self.out)
        self.assertEqual(report['skin_name'], '测试皮肤')
        self.assertEqual(report['ini_encoding'], 'utf-16')

    def test_gb18030_ini(self):
        self.make_ssf(CONFIG.replace('Example Skin', '测试皮肤'), encoding='gb18030')
        self.assertEqual(ssf_import.import_theme(self.source, self.out)['ini_encoding'], 'gb18030')

    def test_unpacked_directory(self):
        self.make_ssf()
        folder = self.root / 'unpacked'
        folder.mkdir()
        for name, data in self.data.items():
            (folder / name).write_bytes(data)
        self.assertIn('horizontal', ssf_import.import_theme(folder, self.out)['layouts'])

    def test_missing_vertical_keeps_native_layout_and_reports(self):
        self.make_ssf(CONFIG.replace('[Scheme_V1]', '[Unused]'))
        report = ssf_import.import_theme(self.source, self.out)
        self.assertFalse(report['native_v_layout_ready'])
        self.assertFalse((self.out / 'overlay/ime/wndComp_vertical.xml').exists())
        self.assertTrue(any('竖版未自动转换' in n for n in report['notes']))

    def test_unsupported_status_keeps_native_status(self):
        self.make_ssf(CONFIG.replace('menu_pos=50,20', 'menu_pos=999,999'))
        report = ssf_import.import_theme(self.source, self.out)
        self.assertNotIn('status', report['layouts'])
        self.assertFalse((self.out / 'overlay/ime/wndStatus.xml').exists())

    def test_h2_only_is_not_silently_misconverted(self):
        self.make_ssf(CONFIG.replace('[Scheme_H1]', '[Scheme_H2]'))
        with self.assertRaisesRegex(ValueError, 'single-window'):
            ssf_import.import_theme(self.source, self.out)
        self.assertFalse(self.out.exists())

    def test_tile_mode_is_reported_instead_of_guessed(self):
        self.make_ssf(CONFIG.replace('layout_horizontal=0,100,100', 'layout_horizontal=1,100,100'))
        with self.assertRaisesRegex(ValueError, 'stretch mode 0'):
            ssf_import.import_theme(self.source, self.out)

    def test_text_outside_image_is_rejected(self):
        self.make_ssf(CONFIG.replace('pinyin_marge=20,8,100,40', 'pinyin_marge=200,8,100,40'))
        with self.assertRaisesRegex(ValueError, 'do not fit'):
            ssf_import.import_theme(self.source, self.out)

    def test_encrypted_format_has_actionable_error(self):
        self.source.write_bytes(b'Skin' + b'\0' * 40)
        with self.assertRaisesRegex(ValueError, 'Unpack it locally'):
            ssf_import.import_theme(self.source, self.out)
        self.assertFalse(self.out.exists())

    def test_refuse_overwriting_existing_draft(self):
        self.make_ssf()
        ssf_import.import_theme(self.source, self.out)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            ssf_import.import_theme(self.source, self.out)

    def test_zip_traversal_and_absolute_paths_are_rejected(self):
        for name in ('../outside', 'nested/../../outside', '/absolute', 'C:\\absolute', '..\\outside'):
            with self.subTest(name=name):
                self.make_ssf(extra={name: b'bad'})
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    ssf_import.import_theme(self.source, self.out)
        self.assertFalse((self.root / 'outside').exists())

    def test_image_reference_cannot_escape_directory(self):
        self.make_ssf(CONFIG.replace('pic=horizontal.png', 'pic=../horizontal.png'))
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            ssf_import.import_theme(self.source, self.out)

    def test_zip_symlink_is_rejected(self):
        self.make_ssf()
        with ZipFile(str(self.source), 'a') as z:
            info = ZipInfo('link')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, '/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            ssf_import.import_theme(self.source, self.out)

    def test_duplicate_case_names_are_rejected(self):
        self.make_ssf(extra={'HORIZONTAL.PNG': b'ambiguous'})
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            ssf_import.import_theme(self.source, self.out)

    def test_many_members_and_oversized_input_are_rejected(self):
        self.make_ssf()
        with mock.patch.object(ssf_import, 'MAX_FILES', 1):
            with self.assertRaisesRegex(ValueError, 'Too many'):
                ssf_import.import_theme(self.source, self.out)
        with mock.patch.object(ssf_import, 'MAX_TOTAL', 1):
            with self.assertRaisesRegex(ValueError, 'input limit'):
                ssf_import.import_theme(self.source, self.out)

    def test_static_preview_does_not_embed_ini_html(self):
        self.make_ssf(CONFIG.replace('Example Skin', '<script>alert(1)</script>'))
        ssf_import.import_theme(self.source, self.out)
        self.assertNotIn('<script>', (self.out / 'preview.html').read_text())

    def test_large_vertical_does_not_claim_patch_compatibility(self):
        self.make_ssf()
        with ZipFile(str(self.source), 'r') as z:
            data = {n: z.read(n) for n in z.namelist()}
        data['vertical.png'] = png(250, 400)
        with ZipFile(str(self.source), 'w') as z:
            for name, value in data.items():
                z.writestr(name, value)
        report = ssf_import.import_theme(self.source, self.out)
        self.assertIn('vertical', report['layouts'])
        self.assertFalse(report['native_v_layout_ready'])

    def test_import_does_not_invoke_desktop_or_subprocesses(self):
        self.make_ssf()
        with mock.patch.object(subprocess, 'run', side_effect=AssertionError('No processes allowed')):
            ssf_import.import_theme(self.source, self.out)

    def test_invalid_zip_cli_error_is_readable(self):
        self.source.write_bytes(b'not a zip')
        result = subprocess.run([sys.executable, '-B', 'build.py', '--ssf', str(self.source), '--out', str(self.out)],
                                cwd=str(Path(ssf_import.__file__).parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Build stopped:', result.stderr)
        self.assertNotIn(b'Traceback', result.stderr)

    def test_cli_builds_self_contained_installer_and_editable_draft(self):
        from test_skin import original_zip
        import bundle
        self.make_ssf()
        native = self.root / 'core'
        native.write_bytes(b'synthetic core; never loaded')
        original = original_zip()
        skins = self.root / 'originals'
        skins.mkdir()
        metadata = {}
        for name in bundle.SKINS:
            (skins / (name + '.zip')).write_bytes(original)
            metadata[name] = {'size': len(original), 'native_hash': bundle.fingerprint(original),
                              'source_sha256': bundle.digest(original)}
        profile = self.root / 'profile.json'
        profile.write_text(json.dumps({'skins': metadata, 'native_sha256': bundle.filehash(native)}))
        result = subprocess.run([sys.executable, '-B', 'build.py', '--ssf', str(self.source),
                                 '--profile', str(profile), '--native', str(native), '--skin-root', str(skins),
                                 '--out', str(self.out)], cwd=str(Path(ssf_import.__file__).parent),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertTrue((self.out / 'imported-theme/preview.html').is_file())
        self.assertTrue((self.out / 'imported-theme/theme.json').is_file())
        manifest = json.loads((self.out / 'manifest.json').read_text())
        for name, digest in manifest['files'].items():
            self.assertEqual(bundle.filehash(self.out / name), digest)
        self.assertEqual(set(manifest['svg_paths']), {'ime/skin1.svg', 'ime/skin2.svg', 'ime/bar.svg'})
        self.assertEqual(manifest['patches'], {})
        self.assertFalse((self.out / 'sample.ssf').exists())
        for name in bundle.SKINS:
            self.assertEqual((skins / (name + '.zip')).read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
