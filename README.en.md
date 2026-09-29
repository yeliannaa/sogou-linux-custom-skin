# Ubuntu Sogou custom skins for Linux

Customize Sogou Pinyin candidate windows, transparent image backgrounds, text spacing and floating status bars on Ubuntu. This project extracts a working Linux skin adaptation into reusable source code, a local package builder, an installer with backups, and a porting guide.

[中文](README.md) · [Implementation and porting](docs/ADAPTATION.md) · [Asset provenance](docs/ASSETS.md)

## Import an SSF automatically

```bash
python3 -B build.py --ssf /path/to/skin.ssf --out build/my-skin
```

This reads classic ZIP-based SSF metadata and unchanged PNG assets to produce a native Sogou Linux theme draft, a static HTML preview, a mapping report and a local installer. Review `build/my-skin/imported-theme/preview.html` and `import-report.json` before applying. No input method is modified or restarted during import/build.

Initial support covers H1/V1 single-window layouts with stretch mode 0. Status-bar background and language/settings button coordinates are attempted when present. Complex dual-window schemes, animations and unsupported fields require manual adaptation. Encrypted `Skin` containers must first be unpacked with another local tool; the importer also accepts that unpacked directory. This is a reviewable starting point rather than a guarantee of pixel-perfect conversion. See [SSF import details](docs/SSF_IMPORT.md).

## How it works

The original implementation adapted a Windows skin's artwork to Sogou Linux XML/SVG layouts through an existing recognized skin slot. The public builder reads the installed vendor ZIPs locally, modifies selected resources, and preserves the archive format expected by that Sogou build. It does not distribute Sogou binaries, vendor ZIPs, third-party artwork or personal configuration.

The method can be reused across versions. The included profile targets an observed Sogou 4.2.1.145 build on x86_64, Fcitx 4 and X11. The original private theme was used successfully on Ubuntu 18.04.5. Different builds need their own resource inspection and, when applicable, native ABI adaptation; changing a hash alone is insufficient.

## Try the original vector example

Requires a working Sogou installation with both `尊贵黑金` skin slots and Python 3.6+; no pip dependencies. Build and check are separate from installation:

```bash
python3 -B build.py --out build/minimal
bash build/minimal/install.sh --check
# Explicitly apply, back up files, and reload the input method:
bash build/minimal/install.sh --activate
# Restore:
bash build/minimal/uninstall.sh --activate
```

Do not run the whole installer as root. It requests elevated access only for the two system skin ZIPs. Existing user settings and startup entries are backed up; unrelated preferences are preserved. It refuses to overwrite the original development machine's existing custom setup.

The minimal example uses original teal SVG backgrounds and native control layout. Its desktop appearance has not yet received the original private theme's manual validation. Generated packages remain local and ignored by Git.

## Custom images and optional native fixes

Copy `examples/minimal` to `private/my-theme`, or use the editable `imported-theme/` produced by `--ssf`. Add your permitted images under `assets/`, XML/SVG overrides under `overlay/ime/`, and layout attribute updates to `theme.json`. SVG image paths can use `@@ASSET_DIR@@`, relocated at installation time. Build with `--theme private/my-theme`.

Two optional source patches address a floating status bar snapping upward after typing and forced-vertical V-mode using horizontal skin geometry:

```bash
python3 -B build.py --with-native-fixes --out build/with-fixes
```

This additionally requires GCC and X11 development libraries. The launcher verifies the native library and compiled patch hashes before process-local preloading. Default builds have no native hooks. Porting requires checking symbols, structure offsets, display geometry, V-mode transitions, multi-monitor behavior, startup and rollback.

## License and contributions

Original project code and geometric example: [MIT](LICENSE), yelianna1001@gmail.com. The original character artwork prohibits uploading and is intentionally excluded, including derivative redraws and screenshots. Vendor resources are read from your own installation and are not covered by this license.

Run tests with `python3 -B -m unittest discover -s tests -v`. Reports should include exact software versions, display backend, scaling and reproduction steps without private input logs or restricted artwork.

For candidate windows stuck away from the caret specifically in PyCharm / JetBrains, see the separate [jetbrains-fcitx-caret-fix](https://github.com/yeliannaa/jetbrains-fcitx-caret-fix) project.
