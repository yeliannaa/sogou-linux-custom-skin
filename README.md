# Ubuntu 搜狗输入法自定义皮肤 · Sogou Linux Custom Skin

把自己的图片、配色和布局接入 Ubuntu 上的搜狗输入法：调整候选框、拼音和中文间距、悬浮状态栏，以及单独的 `v` 模式界面。无需为了换肤降级输入法。

这是从一次实际使用成功的搜狗 Linux 换肤任务提炼出来的工具和适配记录。方法是复用搜狗已识别的皮肤槽位，在本地修改 XML / SVG / 图片引用并保持资源包格式；其他版本可以参照这个流程适配。**安装包的校验对应具体构建，方法可以复用，原生补丁需要另行核对 ABI。**

[English](README.en.md) · [安装与回退](docs/INSTALL.md) · [制作自己的皮肤](docs/CUSTOMIZE.md) · [实现原理与版本适配](docs/ADAPTATION.md) · [验证范围](docs/VALIDATION.md)

## 快速开始

先确保搜狗输入法已经能正常输入，并安装了「尊贵黑金」皮肤。本项目使用这两个现有槽位；设置里的名称和缩略图可能仍显示「尊贵黑金」。

构建和检查都不会重启输入法。实际应用使用单独的安装命令：

```bash
git clone https://github.com/yeliannaa/sogou-linux-custom-skin.git
cd sogou-linux-custom-skin
python3 -B build.py --out build/minimal
bash build/minimal/install.sh --check
# 确认要应用，再执行：会备份并重载当前用户的输入法
bash build/minimal/install.sh --activate
```

构建只依赖 Python 3.6+ 标准库。生成的本地安装包有独立校验、备份、自启和卸载入口。不要用 `sudo` 运行整个脚本；安装器仅在替换两个系统皮肤 ZIP 时请求管理员权限。

仓库里的示例是原创深青色矢量背景，保留本机原皮肤的控件布局，便于检查换肤链路。它与最初验证的角色皮肤是不同的外观；示例的桌面视觉效果尚待用户验证。

已经换过皮肤的设备请用自己的**原始备份**作为构建输入：

```bash
python3 -B build.py --skin-root /path/to/original-skin-backups --out build/my-theme
```

安装器会拒绝覆盖原制作设备的既有适配。这里只读原始备份来构建，不要求卸载正在使用的皮肤。

## 自己的图片和角色状态栏

复制 `examples/minimal` 到被 Git 忽略的 `private/my-theme`，设置 `theme.json`，将素材放在 `assets/`，将 XML / SVG 覆盖文件放在 `overlay/ime/`。图片通过 `@@ASSET_DIR@@` 引用，安装时转换为目标用户路径。支持横版候选框、竖版候选框、异形背景和可调整按钮位置的状态栏。

细节见 [自定义教程](docs/CUSTOMIZE.md)。Windows `.ssf` 的素材可以作为本地适配输入；本工具不会把任意 `.ssf` 一键转换为 Linux 皮肤，布局需要核对和调整。

## 状态栏回弹和 V 模式

原任务中还有两项已解决的问题：人物状态栏拖到底部后，打字又回弹；单独输入 `v` 时，横版皮肤被拉成不合适的形状。对应补丁源码在 `src/`，通过以下选项单独编译加入安装包：

```bash
python3 -B build.py --with-native-fixes --out build/with-fixes
```

这一步需要系统已有 `gcc`、X11 开发头文件和链接库（Ubuntu 中通常由 `gcc`、`libx11-dev` 提供）；脚本不会安装依赖。默认构建不含原生补丁。补丁只通过该输入法进程的 `LD_PRELOAD` 加载，不改写搜狗可执行文件，也不设置全局预加载。

## 环境和复用

| 层次 | 当前记录 |
| --- | --- |
| 已验证的完整私有皮肤案例 | Ubuntu 18.04.5、X11、Fcitx 4、搜狗 4.2.1.145、x86_64；候选框、透明状态栏、双屏底部、V 模式由用户确认 |
| 本仓库构建配置 | 上述搜狗构建的核心库和两个原始皮肤 SHA-256，见 `profiles/` |
| 其他搜狗版本 / 发行版 | 可以复用资源分析、布局修改、打包、备份和验证流程；先采集差异并建立自己的配置 |
| Wayland / Fcitx 5 / ARM | 需要核对输入法实现、渲染路径和原生接口；不能直接加载这里的 x86_64 / X11 补丁 |

不要为了让校验通过而删除版本检查。检查失败可以说明是核心库不同、槽位已修改或需要新的适配配置；参照 [适配指南及 AI 提示词](docs/ADAPTATION.md) 继续调查。

## 回退

```bash
bash build/minimal/uninstall.sh --activate
```

恢复目标设备安装前的皮肤、启动项和本次修改的三个输入法选项。保留备份，并尽量保留安装后的其他设置变化；检测到文件被另行修改时停止覆盖。安装包丢失时可从 `~/.local/share/sogou-custom-skin/installer/` 运行卸载脚本。

## 素材、隐私和许可

代码与原创示例采用 [MIT](LICENSE)，作者：yelianna1001@gmail.com。

仓库不包含搜狗官方资源 ZIP、搜狗库文件、第三方角色图片、用户输入法配置或私人迁移包。构建时从本机读取官方资源，生成在 `build/` 中的安装包只供本地使用；是否可以再次分发取决于其中素材的授权。

最初使用的「染上黍黍了」素材作者为 **@陌芋marginal**，其随包说明禁止上传和商用，因此原图、重绘衍生图和含图截图均未收入本项目。详情见 [素材与来源说明](docs/ASSETS.md)。

## 开发和反馈

```bash
python3 -B -m unittest discover -s tests -v
```

欢迎反馈实际版本、X11/Wayland、Fcitx 版本、缩放、出问题的布局，以及最小复现步骤。不要上传个人输入记录、账号配置或未获允许分发的素材。

如果问题是仅在 PyCharm / JetBrains 中候选框不跟随光标，另见 [jetbrains-fcitx-caret-fix](https://github.com/yeliannaa/jetbrains-fcitx-caret-fix)。这里主要处理输入法皮肤和皮肤自身的布局行为。
