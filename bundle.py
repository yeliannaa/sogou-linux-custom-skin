#!/usr/bin/env python3
"""Portable Sogou custom skin installer. Requires Python >= 3.6, no pip packages."""
import argparse
import datetime
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZipFile

from archive_tools import rewrite

BUNDLE = Path(__file__).resolve().parent
SYSTEM = Path('/opt/sogoupinyin/files/share/resources/skin')
NATIVE = Path('/opt/sogoupinyin/files/lib/libSogouIme.so')
RUNTIME = Path.home() / '.local/share/sogou-custom-skin'
STATE = Path.home() / '.local/state/sogou-custom-skin'
CONF = Path.home() / '.config/sogoupinyin/conf/env.ini'
AUTOSTART = Path.home() / '.config/autostart/fcitx.desktop'
SKINS = ('尊贵黑金', '尊贵黑金-Compositing')
SETTING = {'ActiveSkinName': '尊贵黑金', 'SkinEnabled': '1', 'CandStyle': '0'}
MARKER = 'X-Sogou-Custom-Skin=true'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def filehash(path):
    return digest(Path(path).read_bytes())


def readjson(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def savejson(path, value):
    atomic(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def run(argv, **kwargs):
    return subprocess.run([str(a) for a in argv], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, **kwargs)


def manifest():
    data = readjson(BUNDLE / 'manifest.json')
    for name, expected in data['files'].items():
        if filehash(BUNDLE / name) != expected:
            raise RuntimeError('安装包文件校验失败：' + name)
    return data


def ini_values(text):
    result = {}
    section = ''
    for line in text.splitlines():
        if line.strip().startswith('['):
            section = line.strip()
        elif section == '[Setting]' and '=' in line and not line.lstrip().startswith(('#', ';')):
            key, value = line.split('=', 1)
            if key.strip() in SETTING:
                key = key.strip()
                if key in result:
                    raise RuntimeError('输入法配置存在重复选项：' + key)
                result[key] = value.strip()
    return result


def ini_set(text, changes):
    """Only modify named keys in [Setting], preserving every other line."""
    ini_values(text)
    lines = text.splitlines(keepends=True)
    section = ''
    found = set()
    start = None
    for index, line in enumerate(lines):
        if line.strip().startswith('['):
            section = line.strip()
            if section == '[Setting]':
                start = index
        elif section == '[Setting]' and '=' in line:
            key = line.split('=', 1)[0].strip()
            if key in changes:
                value = changes[key]
                lines[index] = '' if value is None else key + '=' + str(value) + '\n'
                found.add(key)
    if start is None:
        raise RuntimeError('env.ini 缺少 [Setting] 段；请先正常启动一次搜狗')
    added = [key + '=' + str(value) + '\n' for key, value in changes.items()
             if key not in found and value is not None]
    lines[start + 1:start + 1] = added
    return ''.join(lines)


def fingerprint(data):
    import struct
    return hashlib.md5(data[:50] + struct.pack('<I', len(data))).hexdigest()


def supported(meta, desktop=True):
    if os.geteuid() == 0:
        raise RuntimeError('请以桌面普通用户运行，勿 sudo 整个安装脚本；需要时会单独请求系统文件权限')
    if platform.machine() != 'x86_64':
        raise RuntimeError('预编译补丁仅支持 x86_64')
    if not NATIVE.is_file() or filehash(NATIVE) != meta['native_sha256']:
        raise RuntimeError('搜狗核心库版本不匹配；此安装包的构建配置与本机不一致；请按适配文档核对环境并重新构建，未进行安装')
    if re.search(r'[\s:\x00-\x1f\\"%`$]', str(RUNTIME)):
        raise RuntimeError('LD_PRELOAD 不支持安装路径包含空白或冒号；请使用无这些字符的用户主目录')
    for command in ('bash', 'fcitx', 'fcitx-remote', 'flock', 'timeout', 'pgrep', 'sha256sum', 'ldd'):
        if shutil.which(command) is None:
            raise RuntimeError('缺少已有系统命令：' + command + '（安装器不会安装依赖）')
    version = run(['/usr/bin/fcitx', '-v']).stdout
    if not re.search(r'\b4\.', version):
        raise RuntimeError('需要 Fcitx 4，当前版本不匹配')
    if desktop and os.environ.get('XDG_SESSION_TYPE') != 'x11':
        raise RuntimeError('仅支持 X11 桌面；请在 X11 会话终端运行')
    if not CONF.is_file():
        raise RuntimeError('未找到当前用户搜狗配置；请先确认搜狗可正常输入')
    ini_values(CONF.read_text(encoding='utf-8'))
    for skin in SKINS:
        folder = SYSTEM / skin
        data = (folder / (skin + '.zip')).read_bytes()
        expected = meta['skins'][skin]
        if len(data) != expected['size'] or fingerprint(data) != expected['native_hash']:
            raise RuntimeError('皮肤槽位格式不匹配：' + skin)
        root = ET.parse(str(folder / '.metadata.xml')).getroot()
        match = root.find("file[@path='/%s.zip']" % skin)
        if match is None or match.get('hash') != expected['native_hash']:
            raise RuntimeError('皮肤元数据不匹配：' + skin)
    return version.strip()


def prepare(meta, output, asset_dir):
    """Stage a complete relocatable runtime without touching installed paths."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(str(BUNDLE / 'resources.zip')) as payload:
        for name in payload.namelist():
            rel = Path(name)
            if rel.is_absolute() or '..' in rel.parts:
                raise RuntimeError('资源包中出现不安全路径')
            if name.endswith('/'):
                continue
            target = output / rel
            atomic(target, payload.read(name), 0o644)
    for patch in meta['patches']:
        path = output / 'patches' / patch
        if filehash(path) != meta['patches'][patch]:
            raise RuntimeError('补丁校验失败：' + patch)
        deps = run(['ldd', str(path)], env=dict(os.environ, LD_LIBRARY_PATH='/usr/lib/x86_64-linux-gnu')).stdout
        if 'not found' in deps:
            raise RuntimeError('补丁依赖不齐：' + deps)
    for skin in SKINS:
        path = output / 'skins' / (skin + '.zip')
        source = path.read_bytes()
        replacements = {}
        with ZipFile(io.BytesIO(source)) as z:
            for member in meta['svg_paths']:
                text = z.read(member).decode('utf-8')
                if text.count('@@ASSET_DIR@@') != 1:
                    raise RuntimeError('图片路径模板异常：' + member)
                data = text.replace('@@ASSET_DIR@@', escape(str(asset_dir), {'"': '&quot;'})).encode()
                ET.fromstring(data)
                replacements[member] = data
        converted = rewrite(source, replacements)
        if fingerprint(converted) != meta['skins'][skin]['native_hash']:
            raise RuntimeError('重打包后原生校验值变化')
        atomic(path, converted, 0o644)
    launcher = (BUNDLE / 'src/start-template.sh').read_bytes()
    atomic(output / 'start.sh', launcher, 0o755)
    helper = output / 'installer'
    helper.mkdir(exist_ok=True)
    for name in list(meta['files']) + ['manifest.json']:
        atomic(helper / name, (BUNDLE / name).read_bytes(), 0o755 if name.endswith('.sh') else 0o644)


def desktop_entry():
    path = str(RUNTIME / 'start.sh')
    # Desktop Exec has its own quoting rules, separate from shell quoting.
    quoted = path.replace('\\', '\\\\\\\\').replace('"', '\\\\"').replace('`', '\\\\`').replace('$', '\\\\$').replace('%', '%%')
    return ('[Desktop Entry]\nType=Application\nName=Fcitx\n'
            'Name[zh_CN]=搜狗输入法（自定义皮肤）\n'
            'Exec="' + quoted + '"\nTryExec=' + path + '\n'
            'Icon=fcitx\nTerminal=false\nStartupNotify=false\n'
            'X-GNOME-Autostart-enabled=true\nX-GNOME-AutoRestart=false\n'
            'X-GNOME-Autostart-Delay=3\nX-KDE-autostart-after=panel\n' + MARKER + '\n').encode()


def system_write(transaction):
    """Only replace the two fixed skin slots, validating the whole batch first."""
    change = readjson(transaction)
    if {item['skin'] for item in change} != set(SKINS) or len(change) != 2:
        raise RuntimeError('系统文件事务范围错误')
    staged = []
    originals = []
    try:
        for item in change:
            dest = SYSTEM / item['skin'] / (item['skin'] + '.zip')
            if dest.is_symlink():
                raise RuntimeError('拒绝替换符号链接：' + str(dest))
            current = dest.read_bytes()
            new = Path(item['source']).read_bytes()
            if digest(current) != item['expected'] or digest(new) != item['new_hash']:
                raise RuntimeError('系统文件已被其他操作修改；停止覆盖：' + str(dest))
            if fingerprint(new) != item['native_hash'] or len(current) != len(new):
                raise RuntimeError('系统皮肤文件格式不匹配')
            with ZipFile(io.BytesIO(new)) as z:
                if z.testzip() is not None:
                    raise RuntimeError('系统皮肤 ZIP 校验失败')
            info = dest.stat()
            originals.append((dest, current, info))
            fd, name = tempfile.mkstemp(prefix='.skin-install-', dir=str(dest.parent))
            with os.fdopen(fd, 'wb') as out:
                out.write(new)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(name, stat.S_IMODE(info.st_mode))
            if os.geteuid() == 0:
                os.chown(name, info.st_uid, info.st_gid)
            staged.append((name, dest))
        applied = []
        try:
            for name, dest in staged:
                os.replace(name, str(dest))
                applied.append(dest)
        except BaseException:
            for dest, old, info in originals:
                if dest in applied:
                    atomic(dest, old, stat.S_IMODE(info.st_mode))
                    if os.geteuid() == 0:
                        os.chown(str(dest), info.st_uid, info.st_gid)
            raise
    finally:
        for name, _ in staged:
            if os.path.exists(name):
                os.unlink(name)


def apply_system(items, transaction):
    savejson(transaction, items)
    if all(os.access(str(SYSTEM / skin), os.W_OK) for skin in SKINS):
        system_write(transaction)
    else:
        print('仅替换两个系统皮肤文件需要管理员权限；其余文件归当前桌面用户所有。', flush=True)
        subprocess.run(['sudo', '--', '/usr/bin/python3', '-B', str(BUNDLE / 'bundle.py'),
                        'system-write', str(transaction)], check=True)


def item_for(skin, source, expected, meta):
    return {'skin': skin, 'source': str(source), 'new_hash': filehash(source),
            'expected': expected, 'native_hash': meta['skins'][skin]['native_hash']}


def state_lock():
    STATE.mkdir(parents=True, exist_ok=True)
    os.chmod(str(STATE), 0o700)
    stream = (STATE / 'install.lock').open('a')
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        stream.close()
        raise
    return stream


def activate(path):
    if not os.environ.get('DISPLAY') or not os.environ.get('XDG_RUNTIME_DIR'):
        raise RuntimeError('立即启用需要在本机桌面终端运行')
    subprocess.run([str(path)], check=True, timeout=45)


def running_fcitx():
    result = subprocess.run(['pgrep', '-u', str(os.getuid()), '-x', 'fcitx'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode not in (0, 1):
        raise RuntimeError('无法检查当前用户的 Fcitx 进程')
    return result.returncode == 0


def stop_fcitx():
    if not running_fcitx():
        return
    subprocess.run(['timeout', '3', '/usr/bin/fcitx-remote', '-e'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    import time
    for _ in range(20):
        if not running_fcitx():
            return
        time.sleep(.25)
    raise RuntimeError('Fcitx 尚未退出；停止替换文件，请先手动退出输入法后重试')


def install(args):
    meta = manifest()
    supported(meta)
    if args.activate and (not os.environ.get('DISPLAY') or not os.environ.get('XDG_RUNTIME_DIR')):
        raise RuntimeError('--activate 需要桌面 DISPLAY 和 XDG_RUNTIME_DIR')
    state_path = STATE / 'state.json'
    if state_path.exists() and readjson(state_path).get('active'):
        state = readjson(state_path)
        if state['bundle_id'] != meta['bundle_id']:
            raise RuntimeError('已安装其他版本；请先用原安装器卸载，勿覆盖备份')
        if any(filehash(SYSTEM / skin / (skin + '.zip')) != state['installed'][skin] for skin in SKINS):
            raise RuntimeError('已安装的系统皮肤被改动，请先核对，不自动覆盖')
        print('此版本已经安装；保留原始备份，不重复安装。')
        if args.activate:
            activate(RUNTIME / 'start.sh')
        return
    if AUTOSTART.exists() and 'X-Sogou-Shu-Status-Fix=true' in AUTOSTART.read_text(encoding='utf-8'):
        raise RuntimeError('检测到本次制作任务的原有适配自启；为保护当前使用，不覆盖源设备')
    if not args.activate and running_fcitx():
        raise RuntimeError('输入法正在运行，默认不打断它；请使用 --activate 明确允许重载，或先退出 Fcitx 再安装')
    if RUNTIME.exists():
        raise RuntimeError('安装目录已存在但未处于已安装状态，请先将旧目录移走保存：' + str(RUNTIME))
    for skin in SKINS:
        with ZipFile(str(SYSTEM / skin / (skin + '.zip'))) as existing:
            if {'ime/shu_horizontal.svg', 'ime/custom-padding.bin'} & set(existing.namelist()):
                raise RuntimeError('系统槽位已有自定义适配，可能由原方案或另一用户管理；不覆盖：' + skin)
    with state_lock():
        return install_locked(args, meta, state_path)


def install_locked(args, meta, state_path):
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = STATE / 'backups' / stamp
    backup.mkdir(parents=True)
    conf_before = CONF.read_bytes()
    autostart_before = AUTOSTART.read_bytes() if AUTOSTART.exists() else None
    conf_mode = stat.S_IMODE(CONF.stat().st_mode)
    autostart_mode = stat.S_IMODE(AUTOSTART.stat().st_mode) if AUTOSTART.exists() else 0o644
    atomic(backup / 'env.ini', conf_before)
    if autostart_before is not None:
        atomic(backup / 'fcitx.desktop', autostart_before)
    originals = {}
    for skin in SKINS:
        data = (SYSTEM / skin / (skin + '.zip')).read_bytes()
        atomic(backup / (skin + '.zip'), data)
        originals[skin] = digest(data)
    staging = Path(tempfile.mkdtemp(prefix='stage-', dir=str(STATE)))
    changed_system = False
    runtime_created = False
    changed_user = False
    stop_attempted = False
    try:
        prepare(meta, staging, RUNTIME / 'assets')
        entry = desktop_entry()
        entry_file = staging / 'fcitx.desktop'
        atomic(entry_file, entry, 0o644)
        if shutil.which('desktop-file-validate'):
            run(['desktop-file-validate', entry_file])
        run(['bash', '-n', staging / 'start.sh'])
        # Refuse to overwrite concurrent user configuration edits.
        if CONF.read_bytes() != conf_before or (AUTOSTART.read_bytes() if AUTOSTART.exists() else None) != autostart_before:
            raise RuntimeError('准备期间用户配置发生变化，请重试安装')
        RUNTIME.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(staging), str(RUNTIME))
        runtime_created = True
        if args.activate:
            stop_attempted = True
            stop_fcitx()
            # Capture the final saved preferences, after the old engine exits.
            conf_before = CONF.read_bytes()
            conf_mode = stat.S_IMODE(CONF.stat().st_mode)
            atomic(backup / 'env.ini', conf_before)
        items = [item_for(skin, RUNTIME / 'skins' / (skin + '.zip'), originals[skin], meta) for skin in SKINS]
        apply_system(items, staging / 'apply.json')
        changed_system = True
        changed_user = True
        atomic(CONF, ini_set(conf_before.decode('utf-8'), SETTING).encode(), conf_mode)
        atomic(AUTOSTART, entry, 0o644)
        state = {'active': True, 'bundle_id': meta['bundle_id'], 'runtime': str(RUNTIME),
                 'backup': str(backup), 'originals': originals,
                 'installed': {x['skin']: x['new_hash'] for x in items},
                 'previous_settings': ini_values(conf_before.decode('utf-8')),
                 'had_autostart': autostart_before is not None, 'autostart_hash': digest(entry),
                 'autostart_mode': autostart_mode}
        savejson(state_path, state)
        if args.activate:
            activate(RUNTIME / 'start.sh')
        print('安装完成：' + str(RUNTIME))
        print('目标设备原始备份：' + str(backup))
        print('已立即加载。' if args.activate else '未重启输入法；注销并重新登录后启用。')
    except BaseException:
        if changed_system:
            restore = [item_for(skin, backup / (skin + '.zip'),
                                filehash(RUNTIME / 'skins' / (skin + '.zip')), meta) for skin in SKINS]
            apply_system(restore, staging / 'restore.json')
        if changed_user:
            atomic(CONF, conf_before, conf_mode)
            if autostart_before is None:
                if AUTOSTART.exists(): AUTOSTART.unlink()
            else:
                atomic(AUTOSTART, autostart_before, autostart_mode)
        if state_path.exists(): state_path.unlink()
        if stop_attempted:
            restart_native()
        if runtime_created and not args.activate:
            shutil.rmtree(str(RUNTIME))
        elif runtime_created:
            print('立即启用失败后的运行资源暂时保留；注销后可移走再重试：' + str(RUNTIME), file=sys.stderr)
        print('安装未完成，已回退本次更改；备份保留在 ' + str(backup), file=sys.stderr)
        raise
    finally:
        shutil.rmtree(str(staging))


def uninstall(args):
    if os.geteuid() == 0:
        raise RuntimeError('请以原桌面用户运行卸载脚本')
    if args.activate and (not os.environ.get('DISPLAY') or not os.environ.get('XDG_RUNTIME_DIR')):
        raise RuntimeError('--activate 需要桌面 DISPLAY 和 XDG_RUNTIME_DIR')
    meta = manifest()
    state_path = STATE / 'state.json'
    if not state_path.exists() or not readjson(state_path).get('active'):
        print('当前用户没有通过本安装包启用的皮肤；未更改任何文件。')
        return
    if not args.activate and running_fcitx():
        raise RuntimeError('输入法正在运行，默认不打断它；请使用 --activate 明确允许重载，或先退出 Fcitx 再卸载')
    with state_lock():
        return uninstall_locked(args, meta, state_path)


def uninstall_locked(args, meta, state_path):
    state = readjson(state_path)
    backup = Path(state['backup'])
    if not AUTOSTART.exists() or filehash(AUTOSTART) != state['autostart_hash']:
        raise RuntimeError('自启入口在安装后被改动，停止自动卸载以免覆盖；请参阅备份手动核对')
    for skin in SKINS:
        if filehash(SYSTEM / skin / (skin + '.zip')) != state['installed'][skin]:
            raise RuntimeError('系统皮肤在安装后被改动，停止覆盖：' + skin)
        if filehash(backup / (skin + '.zip')) != state['originals'][skin]:
            raise RuntimeError('备份校验失败：' + skin)
    current = CONF.read_text(encoding='utf-8')
    items = [item_for(skin, backup / (skin + '.zip'), state['installed'][skin], meta) for skin in SKINS]
    entry_before = AUTOSTART.read_bytes()
    conf_mode = stat.S_IMODE(CONF.stat().st_mode)
    changed = False
    stop_attempted = False
    try:
        if args.activate:
            stop_attempted = True
            stop_fcitx()
            current = CONF.read_text(encoding='utf-8')
            conf_mode = stat.S_IMODE(CONF.stat().st_mode)
        selected = ini_values(current)
        restore_keys = {key: state['previous_settings'].get(key) for key, value in SETTING.items()
                        if selected.get(key) == value}
        apply_system(items, STATE / 'uninstall-transaction.json')
        changed = True
        atomic(CONF, ini_set(current, restore_keys).encode(), conf_mode)
        if state['had_autostart']:
            atomic(AUTOSTART, (backup / 'fcitx.desktop').read_bytes(), state['autostart_mode'])
        else:
            AUTOSTART.unlink()
        state['active'] = False
        savejson(state_path, state)
    except BaseException:
        if changed:
            restore = [item_for(skin, RUNTIME / 'skins' / (skin + '.zip'), state['originals'][skin], meta)
                       for skin in SKINS]
            apply_system(restore, STATE / 'uninstall-rollback.json')
            atomic(CONF, current.encode(), conf_mode)
            atomic(AUTOSTART, entry_before, 0o644)
        state['active'] = True
        savejson(state_path, state)
        if stop_attempted:
            activate(RUNTIME / 'start.sh')
        raise
    # Keep runtime assets and backup until the user chooses to remove them.
    # This also avoids invalidating resources of a currently running process.
    if args.activate:
        restart_native()
    print('已恢复此设备安装前的皮肤、自启和相关选项。')
    print('已重载输入法。' if args.activate else '未重启输入法；请注销并重新登录完成切换。')
    print('备份及资源保留：' + str(STATE) + '；' + str(RUNTIME))


def restart_native():
    subprocess.run(['timeout', '3', '/usr/bin/fcitx-remote', '-e'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    import time
    time.sleep(1)
    env = dict(os.environ)
    env.pop('LD_PRELOAD', None)
    env['LD_LIBRARY_PATH'] = '/usr/lib/x86_64-linux-gnu'
    subprocess.Popen(['/usr/bin/fcitx', '-r'], env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def main():
    parser = argparse.ArgumentParser(description='搜狗 Linux 自定义皮肤离线安装器')
    parser.add_argument('command', choices=['check', 'install', 'uninstall', 'prepare', 'system-write'])
    parser.add_argument('transaction', nargs='?')
    parser.add_argument('--activate', action='store_true', help='明确要求立即重载输入法')
    parser.add_argument('--out', type=Path, help='仅生成临时副本的输出目录')
    parser.add_argument('--asset-dir', type=Path, help='prepare 使用的图片绝对路径')
    args = parser.parse_args()
    if args.command == 'system-write':
        system_write(args.transaction)
    elif args.command == 'check':
        meta = manifest()
        print('兼容检查通过：' + supported(meta))
        print('原生搜狗核心库及两个皮肤槽位匹配；检查未写入文件或重启进程。')
        if AUTOSTART.exists() and 'X-Sogou-Shu-Status-Fix=true' in AUTOSTART.read_text(encoding='utf-8'):
            print('本机已有制作阶段的适配；安装器将拒绝覆盖源设备。')
    elif args.command == 'prepare':
        if args.out is None or args.asset_dir is None or not args.asset_dir.is_absolute():
            parser.error('prepare 需要 --out 和绝对路径 --asset-dir')
        prepare(manifest(), args.out, args.asset_dir)
        print('已生成副本：' + str(args.out))
    elif args.command == 'install':
        install(args)
    else:
        uninstall(args)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print('停止：' + str(exc), file=sys.stderr)
        sys.exit(1)
