#!/usr/bin/env python3
"""Import a classic ZIP-based SSF into a private Sogou Linux theme draft.

Independent implementation of the Skin.ini fields observed in local SSF files.
Images are copied unchanged. No third-party converter code is incorporated.
"""
import argparse
import configparser
import hashlib
import html
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile

MAX_FILES = 2048
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
SVG = 'http://www.w3.org/2000/svg'
XLINK = 'http://www.w3.org/1999/xlink'
ET.register_namespace('', SVG)
ET.register_namespace('xlink', XLINK)


def member_name(name):
    name = name.replace('\\', '/')
    path = PurePosixPath(name)
    if (not name or name.startswith('/') or re.match(r'^[A-Za-z]:', name)
            or '..' in path.parts or any(ord(c) < 32 for c in name)):
        raise ValueError('Unsafe SSF member path')
    return str(path)


class Source:
    """Bounded archive reader; never extract an archive onto the filesystem."""
    def __init__(self, path):
        self.path = Path(path)
        self.zip = None
        self.members = {}
        self.actual_names = {}
        try:
            if self.path.is_dir():
                entries = []
                for p in self.path.rglob('*'):
                    if p.is_symlink():
                        raise ValueError('Symlinks are not supported in unpacked SSF')
                    if p.is_file():
                        entries.append((p.relative_to(self.path).as_posix(), p.stat().st_size, p))
                    if len(entries) > MAX_FILES:
                        raise ValueError('Too many SSF members')
            else:
                if self.path.stat().st_size > MAX_TOTAL:
                    raise ValueError('SSF exceeds the 64 MiB input limit')
                with self.path.open('rb') as stream:
                    if stream.read(4) == b'Skin':
                        raise ValueError('Encrypted Skin-format SSF is not decoded by this importer. '
                                         'Unpack it locally with a suitable tool, then pass the unpacked directory.')
                self.zip = ZipFile(str(self.path))
                entries = []
                for info in self.zip.infolist():
                    member_name(info.filename)
                    if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                        raise ValueError('Symlink/password-protected ZIP member is unsupported')
                    if not info.is_dir():
                        entries.append((info.filename, info.file_size, info))
                if len(entries) > MAX_FILES:
                    raise ValueError('Too many SSF members')
            total = 0
            for name, size, entry in entries:
                name = member_name(name)
                if size > MAX_FILE:
                    raise ValueError('SSF member exceeds the 16 MiB limit')
                total += size
                if total > MAX_TOTAL:
                    raise ValueError('Unpacked SSF exceeds the 64 MiB limit')
                key = name.casefold()
                if key in self.members:
                    raise ValueError('Ambiguous case-insensitive SSF member names')
                self.members[key] = entry
                self.actual_names[key] = name
            candidates = [k for k in self.members if PurePosixPath(k).name == 'skin.ini']
            if len(candidates) != 1:
                raise ValueError('Expected exactly one Skin.ini in SSF')
            self.ini = candidates[0]
            self.base = PurePosixPath(self.ini).parent
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.zip is not None:
            self.zip.close()

    def read(self, key):
        key = key.casefold()
        if key not in self.members:
            raise ValueError('Referenced image is missing: ' + key)
        entry = self.members[key]
        if self.zip is not None:
            with self.zip.open(entry) as stream:
                data = stream.read(MAX_FILE + 1)
        else:
            with entry.open('rb') as stream:
                data = stream.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise ValueError('SSF member exceeds size limit')
        return data

    def image(self, reference):
        relative = member_name(reference.strip().strip('"'))
        key = str(self.base / relative).casefold()
        data = self.read(key)
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data) < 33 or data[12:16] != b'IHDR':
            raise ValueError('Automatic layout currently requires PNG images: ' + relative)
        width, height = struct.unpack('>II', data[16:24])
        if not 1 <= width <= 8192 or not 1 <= height <= 8192 or width * height > 16000000:
            raise ValueError('PNG dimensions exceed layout limits')
        return key, data, width, height


def read_ini(data):
    encodings = ['utf-16'] if data.startswith((b'\xff\xfe', b'\xfe\xff')) else ['utf-8-sig', 'gb18030']
    for encoding in encodings:
        try:
            text = data.decode(encoding)
        except UnicodeError:
            continue
        parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(';',))
        try:
            parser.read_string(text)
        except configparser.Error as exc:
            raise ValueError('Invalid Skin.ini: ' + str(exc))
        sections = {}
        for name in parser.sections():
            key = name.casefold()
            if key in sections:
                raise ValueError('Ambiguous Skin.ini section names')
            sections[key] = dict(parser.items(name))
        return sections, encoding
    raise ValueError('Skin.ini encoding is not UTF-8, UTF-16 BOM or GB18030')


def numbers(value, count, label):
    try:
        values = [int(v.strip()) for v in value.split(',')]
    except (AttributeError, ValueError):
        raise ValueError('Invalid numeric field: ' + label)
    if len(values) != count or any(v < 0 or v > 8192 for v in values):
        raise ValueError('Unsupported negative/out-of-range layout field: ' + label)
    return values


def xml_bytes(root):
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def image_svg(asset, width, height):
    root = ET.Element('{' + SVG + '}svg', {'width': str(width), 'height': str(height),
                      'viewBox': '0 0 {} {}'.format(width, height)})
    ET.SubElement(root, '{' + SVG + '}image', {'width': str(width), 'height': str(height),
                  '{' + XLINK + '}href': '@@ASSET_DIR@@/' + asset})
    return xml_bytes(root)


def import_theme(source_path, output):
    """Generate a private editable draft, report and static preview only."""
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Import output already exists; choose a new directory')
    source = Source(source_path)
    try:
        return convert(source, output)
    finally:
        source.close()


def convert(source, output):
    ini_bytes = source.read(source.ini)
    sections, encoding = read_ini(ini_bytes)
    display = sections.get('display', {})
    notes, layouts, previews, assets, overlay = [], {}, [], {}, {}
    asset_map = {}
    font = 'Droid Sans Fallback'
    try:
        size = int(display.get('font_size', '16'))
    except ValueError:
        raise ValueError('Invalid Display.font_size')
    if not 8 <= size <= 48:
        raise ValueError('Automatic font size must be between 8 and 48')
    line = int(math.ceil(size * 1.25))

    def color(field, default):
        value = display.get(field, default).strip()
        if not re.fullmatch(r'(?:0x|#)?[0-9a-fA-F]{6}', value):
            raise ValueError('Unsupported RGB color: Display.' + field)
        return '0xff' + value.lower().replace('0x', '').lstrip('#')

    colors = {'pinyin': color('pinyin_color', '408080'),
              'candidate': color('zhongwen_color', '408080'),
              'first': color('zhongwen_first_color', '804000')}

    def add_image(reference):
        key, data, width, height = source.image(reference)
        if key not in asset_map:
            name = 'image-' + hashlib.sha256(data).hexdigest()[:20] + '.png'
            assets[name] = data
            asset_map[key] = name
        return asset_map[key], width, height

    def layout(section_name, role):
        if section_name not in sections:
            raise ValueError('Missing [' + section_name + '] single-window layout')
        section = sections[section_name]
        if not section.get('pic'):
            raise ValueError('Missing background pic in [' + section_name + ']')
        asset, width, height = add_image(section['pic'])
        horizontal = numbers(section.get('layout_horizontal', ''), 3, section_name + '.layout_horizontal')
        vertical = numbers(section.get('layout_vertical', ''), 3, section_name + '.layout_vertical')
        if horizontal[0] != 0 or vertical[0] != 0:
            raise ValueError('Only stretch mode 0 is mapped automatically: ' + section_name)
        left, right = horizontal[1:]
        top, bottom = vertical[1:]
        if left + right >= width or top + bottom >= height:
            raise ValueError('Stretch region is empty/outside image: ' + section_name)
        py = numbers(section.get('pinyin_marge', ''), 4, section_name + '.pinyin_marge')
        cn = numbers(section.get('zhongwen_marge', ''), 4, section_name + '.zhongwen_marge')
        split = py[0] + line + py[1]
        if (split + cn[0] + line + cn[1] > height or py[2] + py[3] + size > width
                or cn[2] + cn[3] + size > width):
            raise ValueError('Text margins do not fit the image at the declared font size: ' + section_name)
        # Reuse the existing background members rather than accumulating large
        # unused SVGs in the fixed-size vendor archive.
        filename = 'skin1.svg' if role == 'horizontal' else 'skin2.svg'
        overlay['ime/' + filename] = image_svg(asset, width, height)
        root = ET.Element('Window', {'name': 'compWnd', 'size': '{},{}'.format(width, height),
                              'minwidth': str(width), 'minheight': str(height),
                              'bkimage': '{},{},{},{},{}'.format(filename, left, width-left-right, top, height-top-bottom)})
        for _ in range(2):
            ET.SubElement(root, 'Font', {'name': font, 'size': str(size)})
        ET.SubElement(root, 'Control', {'name': 'compbk', 'bkimage': '', 'minheight': str(split),
                      'padding': '0,0,0,0', 'pos': '0,0', 'visible': 'true', 'enablemove': 'true'})
        ET.SubElement(root, 'Control', {'name': 'candbk', 'bkimage': '', 'minheight': str(height-split),
                      'padding': '0,0,0,0', 'pos': '0,' + str(split), 'visible': 'true', 'enablemove': 'true'})
        ET.SubElement(root, 'CompString', {'name': 'CompString', 'textcolor': colors['pinyin'], 'font': '1',
                      'margin': ','.join(str(v) for v in py), 'minheight': str(line)})
        ET.SubElement(root, 'CandString', {'name': 'CandString', 'font': '0',
                      'margin': ','.join(str(v) for v in cn), 'minheight': str(line),
                      'focus_candString_color': colors['first'], 'candString_color': colors['candidate'],
                      'candStringPressBgClr': '0x26808040', 'candStringPressTextClr': colors['first']})
        ET.SubElement(root, 'Control', {'name': 'separator', 'visible': 'false'})
        ET.SubElement(root, 'Caret', {'name': 'caret', 'bkcolor': colors['pinyin']})
        ET.SubElement(root, 'Control', {'name': 'compLogo', 'size': '0,0', 'visible': 'false'})
        # Keep native paging icons; placement is only a starting point.
        for name, stem in [('pageup', 'ov_pageup'), ('pagedown', 'ov_pagedown')]:
            ET.SubElement(root, 'Button', {'name': name, 'normalimage': stem + '_on1.svg',
                          'hotimage': stem + '_on2.svg', 'pushedimage': stem + '_on3.svg',
                          'disabledimage': stem + '_off1.svg', 'size': '15,15', 'pos': '0,0',
                          'padding': '7,0,0,8' if name == 'pageup' else '0,0,11,0'})
        layouts[role] = {'source_section': section_name, 'image_size': [width, height],
                         'pinyin_top_left': [py[2], py[0]], 'candidate_top_left': [cn[2], split+cn[0]],
                         'stretch_rect': [left, top, width-left-right, height-top-bottom]}
        previews.append({'label': role, 'asset': asset, 'width': width, 'height': height,
                         'text': [(py[2], py[0], 'ni hao', colors['pinyin']),
                                  (cn[2], split+cn[0], '1.你好  2.拟好', colors['first'])]})
        if 'anchor' in section:
            notes.append(section_name + '.anchor 未直接套用：Windows 锚点与搜狗 Linux 光标定位不同，需要实机检查。')
        return root

    # Without a supported horizontal layout, stop instead of inventing coordinates.
    horizontal = layout('scheme_h1', 'horizontal')
    if horizontal.get('minheight') == '300':
        notes.append('横版高度恰好为 300，不能直接使用现有 V 模式补丁；请先调整布局标记或适配补丁。')
    overlay['ime/wndComp.xml'] = xml_bytes(horizontal)
    native_v_ready = False
    try:
        vertical = layout('scheme_v1', 'vertical')
    except ValueError as exc:
        notes.append('竖版未自动转换，保留本机原竖版；V 模式需要人工适配。原因：' + str(exc))
    else:
        overlay['ime/wndComp_vertical.xml'] = xml_bytes(vertical)
        height = int(vertical.get('minheight'))
        if height <= 300 and horizontal.get('minheight') != '300':
            vertical.set('size', vertical.get('minwidth') + ',300')
            vertical.set('minheight', '300')
            for child in vertical:
                if child.get('name') == 'candbk':
                    child.set('minheight', str(int(child.get('minheight')) + 300 - height))
            overlay['ime/wndComp_vmode.xml'] = xml_bytes(vertical)
            native_v_ready = True
            if height < 300:
                notes.append('V 模式草稿通过中间拉伸补到 300 像素，以匹配现有补丁；请检查背景和上下留白。')
        else:
            notes.append('竖版尺寸不满足现有 V 模式补丁标记；未生成专用布局，默认构建不会加载补丁。')

    status = sections.get('statusbar', {})
    try:
        if not status.get('pic'):
            raise ValueError('StatusBar.pic 缺失')
        asset, width, height = add_image(status['pic'])
        positions = {}
        for native, ssf in [('language', 'cn_en'), ('setting', 'menu')]:
            if status.get(ssf + '_display', '1') == '0':
                raise ValueError(ssf + ' 按钮在原皮肤中关闭')
            x, y = numbers(status.get(ssf + '_pos', ''), 2, 'StatusBar.' + ssf + '_pos')
            if x + 18 > width or y + 18 > height:
                raise ValueError(ssf + ' 按钮位置超出状态栏')
            positions[native] = [x, y]
        root = ET.Element('Window', {'name': 'statusWnd', 'size': '{},{}'.format(width, height),
                             'minwidth': str(width), 'minheight': str(height), 'bkimage': 'bar.svg'})
        ET.SubElement(root, 'Font', {'name': font, 'size': str(size)})
        for name, position in positions.items():
            attrs = {'name': name, 'size': '18,18', 'pos': ','.join(str(v) for v in position)}
            if name == 'setting':
                attrs.update(normalimage='setting.svg', hotimage='setting_hover.svg',
                             pushedimage='setting_press.svg', disabledimage='setting_disable.svg')
            ET.SubElement(root, 'Button', attrs)
        overlay['ime/bar.svg'] = image_svg(asset, width, height)
        overlay['ime/wndStatus.xml'] = xml_bytes(root)
        layouts['status'] = {'image_size': [width, height], 'buttons': positions}
        previews.append({'label': 'status', 'asset': asset, 'width': width, 'height': height,
                         'text': [(positions['language'][0], positions['language'][1], '中', colors['pinyin']),
                                  (positions['setting'][0], positions['setting'][1], '⚙', colors['pinyin'])]})
        notes.append('状态栏仅映射中英与设置的坐标，使用 Linux 原生图标；Windows 专用按钮、悬停图和自定义动作未映射。')
    except ValueError as exc:
        notes.append('状态栏保留本机原样，未猜测按钮坐标。原因：' + str(exc))
    notes.append('Windows 字体替换为 Droid Sans Fallback；字体实际回退和字形基线需要实机确认。')
    notes.append('只转换静态 PNG 和 H1/V1 单窗拉伸布局；H2/V2 双窗、动画、分隔线与阴影效果未复制。')
    notes.append('预览只表示原图、估算文字位置；不模拟搜狗的动态候选宽度、换行、光标和缩放。')
    name = 'ssf-' + hashlib.sha256(ini_bytes).hexdigest()[:12]
    theme = {'name': name, 'description': 'Automatically imported SSF draft; review import-report.json.', 'updates': {}}
    report = {'format': 1, 'status': 'needs-review', 'source_name': source.path.name,
              'skin_name': sections.get('general', {}).get('skin_name', ''), 'ini_encoding': encoding,
              'font': font, 'font_size': size, 'layouts': layouts, 'native_v_layout_ready': native_v_ready,
              'notes': notes, 'images_copied_unchanged': True}
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.ssf-import-', dir=str(output.parent)))
    try:
        for folder, files in [('assets', assets), ('overlay', overlay)]:
            for name, data in files.items():
                path = stage / folder / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        for filename, data in [('theme.json', theme), ('import-report.json', report)]:
            (stage / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        panels = []
        for item in previews:
            text = ''.join('<text x="{}" y="{}" font-family="sans-serif" font-size="{}" fill="#{}">{}</text>'.format(
                          x, y+size, size, color[-6:], html.escape(label)) for x, y, label, color in item['text'])
            panels.append('<section><h2>{}</h2><svg width="{}" height="{}" viewBox="0 0 {} {}">'
                          '<image href="assets/{}" width="{}" height="{}"/>{}</svg></section>'.format(
                          item['label'], item['width'], item['height'], item['width'], item['height'],
                          item['asset'], item['width'], item['height'], text))
        preview = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>SSF 导入预览</title>'
                   '<style>body{font:16px sans-serif;background:#eee;padding:24px}section{display:inline-block;'
                   'vertical-align:top;padding:12px;border:1px solid #aaa;margin:8px}svg{background:#ddd}</style>'
                   '<h1>SSF 布局草稿</h1><p>静态示意，尚未应用输入法。请先检查文字、留白、按钮和下列未转换项。</p>'
                   + ''.join(panels) + '<h2>需要检查</h2><ul>'
                   + ''.join('<li>' + html.escape(n) + '</li>' for n in notes) + '</ul></html>')
        (stage / 'preview.html').write_text(preview, encoding='utf-8')
        stage.rename(output)
    except BaseException:
        shutil.rmtree(str(stage))
        raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='ZIP-based SSF or a previously unpacked directory')
    parser.add_argument('--out', type=Path, required=True, help='New private theme directory')
    args = parser.parse_args()
    try:
        report = import_theme(args.source, args.out)
    except (OSError, ValueError, BadZipFile, RuntimeError) as exc:
        parser.exit(1, 'SSF import stopped: ' + str(exc) + '\n')
    print('Created draft: ' + str(args.out))
    print('Open preview.html and import-report.json before building/applying.')
    print('Converted: ' + ', '.join(report['layouts']))


if __name__ == '__main__':
    main()
