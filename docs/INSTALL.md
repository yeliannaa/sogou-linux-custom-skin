# 安装、迁移和回退

在源码仓库中先运行 `python3 -B build.py --out build/minimal`。如果已拿到自己构建的安装目录，进入该目录后运行以下命令。

通过 `--ssf` 构建的安装包还包含 `imported-theme/preview.html`、`import-report.json` 和可编辑主题。先检查报告中的未转换项与静态预览，再安装。这个目录包含你本地输入的素材，不会在安装时复制到运行目录，也不应随源码公开上传。

1. `sha256sum -c SHA256SUMS`：检查文件完整性。
2. `bash install.sh --check`：只读核对本机核心库、Fcitx、X11、已有皮肤槽位和配置。
3. `bash install.sh --activate`：备份、安装并重载输入法。
4. 测试普通拼音、长候选、翻页、删除、`v`、中英切换、设置按钮、状态栏拖动、双屏和缩放。

仅运行 `bash install.sh` 时，输入法必须已经退出，否则停止；成功后下次桌面登录加载。不必重启操作系统。不要 `sudo bash install.sh`，需要时安装器会单独请求替换系统皮肤的权限。

安装位置：

| 内容 | 位置 |
| --- | --- |
| 两个共享皮肤槽位 | `/opt/sogoupinyin/files/share/resources/skin/尊贵黑金*/` 下的 ZIP |
| 资源、启动脚本、卸载工具 | `~/.local/share/sogou-custom-skin/` |
| 原始备份、安装状态 | `~/.local/state/sogou-custom-skin/` |
| 当前用户自启项 | `~/.config/autostart/fcitx.desktop` |
| 本次修改的选项 | `env.ini` 中 `ActiveSkinName`、`SkinEnabled`、`CandStyle` |

不迁移用户词库、账号或其他输入法偏好。构建时不启动输入法、不写上述位置；安装时才会改动。

卸载：

```bash
bash uninstall.sh --activate
# 或安装目录已丢失：
bash "$HOME/.local/share/sogou-custom-skin/installer/uninstall.sh" --activate
```

卸载恢复本机备份，并保留备份和运行资源。文件被其他工具修改后会拒绝覆盖，请对照备份手动核对。原始制作任务的自启或角色皮肤存在时，安装器会停止，以免覆盖目前已满意的效果。

使用原生补丁的安装包在核心库升级后会跳过不匹配补丁，启动普通 Fcitx。此保护并不保证升级后的自定义皮肤仍正确，应使用升级前记录适配新版或回退皮肤。

这是每台设备由一个桌面用户管理两个共享槽位的设计；多个用户同时安装会涉及共享槽位和各自私有图片路径，需先改为共享资源方案。用户主目录不能含空白、冒号等 `LD_PRELOAD` 无法正确表达的字符；中文路径可以。Python 需要 3.6+，输入法命令及可选补丁依赖由目标设备提供。
