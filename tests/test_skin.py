import argparse
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
from zipfile import ZipFile, ZipInfo, ZIP_STORED

import archive_tools
import build as builder
import bundle


def original_zip():
    output = io.BytesIO()
    with ZipFile(output, 'w', compression=ZIP_STORED) as z:
        first = ZipInfo('handinput/')
        first.extra = b'\xfe\xca' + struct.pack('<H', 24) + b'\0' * 24
        z.writestr(first, b'')
        z.writestr('ime/wndComp.xml', b'<Window minheight="56"><CompString name="CompString" textcolor="old"/></Window>')
        z.writestr('ime/wndComp_vertical.xml', b'<Window minheight="56"><Control name="candbk"/></Window>')
        z.writestr('ime/asset.svg', b'<svg/>')
        z.writestr('untouched.bin', b'unchanged payload\n' * 3000)
    return output.getvalue()


class ArchiveTests(unittest.TestCase):
    def test_build_keeps_fingerprint_and_other_contents(self):
        source = original_zip()
        target = archive_tools.build(source, {'ime/asset.svg': b'<svg>example</svg>', 'ime/new.svg': b'<svg/>'})
        self.assertEqual(bundle.fingerprint(source), bundle.fingerprint(target))
        self.assertEqual(source[:50], target[:50])
        self.assertEqual(len(source), len(target))
        with ZipFile(io.BytesIO(source)) as old, ZipFile(io.BytesIO(target)) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(old.read('untouched.bin'), z.read('untouched.bin'))
            self.assertEqual(z.read('ime/asset.svg'), b'<svg>example</svg>')
            self.assertEqual(z.namelist()[-1], archive_tools.PAD)

    def test_relocation_preserves_compressed_unrelated_record(self):
        source = archive_tools.build(original_zip(), {'ime/new.svg': b'<svg>@@ASSET_DIR@@</svg>'})
        target = archive_tools.rewrite(source, {'ime/new.svg': '<svg>/home/测试/assets</svg>'.encode()})
        def record(data, name):
            with ZipFile(io.BytesIO(data)) as z:
                info = z.getinfo(name)
                n, e = struct.unpack_from('<HH', data, info.header_offset + 26)
                return data[info.header_offset:info.header_offset + 30 + n + e + info.compress_size]
        self.assertEqual(record(source, 'untouched.bin'), record(target, 'untouched.bin'))
        self.assertEqual(bundle.fingerprint(source), bundle.fingerprint(target))

    def test_reject_first_record_replacement(self):
        with self.assertRaises(ValueError):
            archive_tools.build(original_zip(), {'handinput/': b'bad'})

    def test_reject_comment(self):
        output = io.BytesIO(original_zip())
        with ZipFile(output, 'a') as z:
            z.comment = b'unsupported comment'
        with self.assertRaises(ValueError):
            archive_tools.build(output.getvalue(), {})

    def test_reject_size_overflow(self):
        import random
        generator = random.Random(42)
        data = bytes(generator.getrandbits(8) for _ in range(100000))
        with self.assertRaisesRegex(ValueError, 'size budget'):
            archive_tools.build(original_zip(), {'ime/big.bin': data})

    def test_reject_duplicate_members(self):
        import warnings
        output = io.BytesIO(original_zip())
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with ZipFile(output, 'a') as z:
                z.writestr('ime/asset.svg', b'duplicate')
        with self.assertRaises(ValueError):
            archive_tools.build(output.getvalue(), {})


class BuildAndTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.system = self.root / 'system'
        self.source = original_zip()
        self.profile = self.root / 'profile.json'
        self.native = self.root / 'native.so'
        self.native.write_bytes(b'synthetic core - never loaded')
        self.profile.write_text(json.dumps({
            'sogou_version': 'synthetic',
            'native_sha256': bundle.filehash(self.native),
            'skins': {s: {'size': len(self.source), 'native_hash': bundle.fingerprint(self.source),
                          'source_sha256': bundle.digest(self.source)} for s in bundle.SKINS},
        }))
        for skin in bundle.SKINS:
            path = self.system / skin / (skin + '.zip')
            path.parent.mkdir(parents=True)
            path.write_bytes(self.source)
        self.theme = self.root / 'theme'
        self.theme.mkdir()
        (self.theme / 'theme.json').write_text(json.dumps({
            'name': 'test', 'updates': {'ime/wndComp.xml': {'CompString': {'textcolor': 'new'}}}
        }))
        self.out = self.root / 'output'
        self.args = argparse.Namespace(profile=self.profile, theme=self.theme, out=self.out,
                                       native=self.native, skin_root=self.system, with_native_fixes=False)

    def generate(self):
        with mock.patch('builtins.print'):
            builder.generate(self.args)

    def bind_installer(self):
        self.generate()
        self.conf = self.root / 'config/env.ini'
        self.conf.parent.mkdir()
        self.conf.write_text('[Setting]\nActiveSkinName=original\nSkinEnabled=0\nCandStyle=1\nUserChoice=keep\n')
        self.autostart = self.root / 'autostart/fcitx.desktop'
        self.autostart.parent.mkdir()
        self.autostart.write_text('[Desktop Entry]\nExec=original-fcitx\n')
        self.runtime = self.root / 'runtime'
        self.state = self.root / 'state'
        for name, value in {'BUNDLE': self.out, 'SYSTEM': self.system, 'NATIVE': self.native,
                            'CONF': self.conf, 'AUTOSTART': self.autostart,
                            'RUNTIME': self.runtime, 'STATE': self.state}.items():
            patch = mock.patch.object(bundle, name, value)
            patch.start(); self.addCleanup(patch.stop)
        for name, result in [('supported', 'synthetic'), ('running_fcitx', False)]:
            patch = mock.patch.object(bundle, name, return_value=result)
            patch.start(); self.addCleanup(patch.stop)
        # No desktop/process tools are run from transaction tests.
        patch = mock.patch.object(bundle, 'run', return_value=argparse.Namespace(stdout=''))
        patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(bundle.os, 'geteuid', return_value=1000)
        patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch('builtins.print')
        patch.start(); self.addCleanup(patch.stop)

    def test_build_is_local_and_pins_files(self):
        self.generate()
        meta = json.loads((self.out / 'manifest.json').read_text())
        for name, expected in meta['files'].items():
            self.assertEqual(bundle.filehash(self.out / name), expected)
        self.assertEqual(meta['patches'], {})
        self.assertIn('EXPECTED_PATCH=disabled', (self.out / 'src/start-template.sh').read_text())
        for skin in bundle.SKINS:
            self.assertEqual((self.system / skin / (skin + '.zip')).read_bytes(), self.source)

    def test_reject_existing_output(self):
        self.generate()
        with self.assertRaisesRegex(ValueError, 'Output exists'):
            builder.generate(self.args)

    def test_reject_modified_source(self):
        path = self.system / bundle.SKINS[0] / (bundle.SKINS[0] + '.zip')
        path.write_bytes(self.source + b'changed')
        with self.assertRaisesRegex(ValueError, 'pristine'):
            builder.generate(self.args)
        self.assertFalse(self.out.exists())

    def test_reject_changed_native(self):
        self.native.write_bytes(b'other core')
        with self.assertRaisesRegex(ValueError, 'Native library'):
            builder.generate(self.args)

    def test_native_fixes_refuse_custom_unreviewed_profile(self):
        self.args.with_native_fixes = True
        with self.assertRaisesRegex(ValueError, 'audited built-in profile'):
            builder.generate(self.args)

    def test_reject_theme_symlink(self):
        folder = self.theme / 'assets'
        folder.mkdir()
        (folder / 'secret').symlink_to(self.native)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            builder.generate(self.args)

    def test_install_uninstall_preserves_other_settings(self):
        self.bind_installer()
        before = self.conf.read_text()
        entry = self.autostart.read_bytes()
        args = argparse.Namespace(activate=False)
        bundle.install(args)
        state = bundle.readjson(self.state / 'state.json')
        bundle.install(args)
        self.assertEqual(state, bundle.readjson(self.state / 'state.json'))
        self.conf.write_text(self.conf.read_text().replace('UserChoice=keep', 'UserChoice=later'))
        bundle.uninstall(args)
        self.assertEqual(self.conf.read_text(), before.replace('UserChoice=keep', 'UserChoice=later'))
        self.assertEqual(self.autostart.read_bytes(), entry)
        for skin in bundle.SKINS:
            self.assertEqual((self.system / skin / (skin + '.zip')).read_bytes(), self.source)

    def test_fault_after_system_write_rolls_back(self):
        self.bind_installer()
        conf_before = self.conf.read_bytes()
        entry_before = self.autostart.read_bytes()
        real = bundle.atomic
        raised = [False]
        def failing_atomic(path, data, mode=0o600):
            if Path(path) == self.autostart and not raised[0]:
                raised[0] = True
                raise OSError('injected startup write failure')
            return real(path, data, mode)
        with mock.patch.object(bundle, 'atomic', side_effect=failing_atomic):
            with self.assertRaisesRegex(OSError, 'injected'):
                bundle.install(argparse.Namespace(activate=False))
        self.assertEqual(self.conf.read_bytes(), conf_before)
        self.assertEqual(self.autostart.read_bytes(), entry_before)
        self.assertFalse(self.runtime.exists())
        for skin in bundle.SKINS:
            self.assertEqual((self.system / skin / (skin + '.zip')).read_bytes(), self.source)

    def test_uninstall_refuses_user_modified_startup(self):
        self.bind_installer()
        args = argparse.Namespace(activate=False)
        bundle.install(args)
        self.autostart.write_text('user modified')
        with self.assertRaisesRegex(RuntimeError, '自启入口'):
            bundle.uninstall(args)
        self.assertEqual(self.autostart.read_text(), 'user modified')

    def test_original_setup_is_protected(self):
        self.bind_installer()
        self.autostart.write_text('X-Sogou-Shu-Status-Fix=true\n')
        with self.assertRaisesRegex(RuntimeError, '保护当前使用'):
            bundle.install(argparse.Namespace(activate=False))
        self.assertFalse(self.runtime.exists())

    def test_running_input_method_not_implicitly_stopped(self):
        self.bind_installer()
        with mock.patch.object(bundle, 'running_fcitx', return_value=True), mock.patch.object(bundle, 'stop_fcitx') as stop:
            with self.assertRaisesRegex(RuntimeError, '输入法正在运行'):
                bundle.install(argparse.Namespace(activate=False))
            stop.assert_not_called()


class ConfigurationTests(unittest.TestCase):
    def test_ini_preserves_sections_and_comments(self):
        data = '[Other]\nCandStyle=other\n[Setting]\n; comment\nCandStyle=1\nUnknown=yes\n'
        result = bundle.ini_set(data, {'CandStyle': '0'})
        self.assertEqual(result, data.replace('CandStyle=1', 'CandStyle=0'))

    def test_duplicate_ini_key_is_rejected(self):
        with self.assertRaises(RuntimeError):
            bundle.ini_set('[Setting]\nCandStyle=1\nCandStyle=2\n', {'CandStyle': '0'})

    def test_xml_change_requires_unique_control(self):
        with self.assertRaises(ValueError):
            builder.update_xml(b'<Window/>', {'missing': {'size': '1,1'}})

    def test_path_traversal_rejected(self):
        for path in ('../secret', '/etc/passwd', 'ime/../../secret', 'ime\\secret'):
            with self.assertRaises(ValueError):
                builder.safe_name(path)


if __name__ == '__main__':
    unittest.main()
