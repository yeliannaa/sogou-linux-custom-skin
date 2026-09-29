# 提供 SSF，自动生成搜狗 Linux 皮肤草稿

现有入口可以自动完成“读 SSF → 识别素材和布局 → 生成 Linux XML/SVG → 生成预览及报告 → 构建带备份回退的安装包”。自动转换不等于自动安装，也不等于已经完成实机视觉调校。

## 一条命令生成

在源码目录中运行：

```bash
python3 -B build.py --ssf /path/to/skin.ssf --out build/my-skin
```

需要本机已安装匹配 profile 的搜狗及原始「尊贵黑金」槽位。已使用自定义皮肤时，从自己的原始备份读取：

```bash
python3 -B build.py --ssf /path/to/skin.ssf \
  --skin-root /path/to/original-skin-backups --out build/my-skin
```

生成后：

1. 打开 `build/my-skin/imported-theme/preview.html`，检查原图、估算文字位置和按钮位置。
2. 阅读同目录的 `import-report.json`，核对转换范围及未支持项。
3. 运行 `bash build/my-skin/install.sh --check`，核对目标设备。
4. 确认要应用后运行 `bash build/my-skin/install.sh --activate`。

已有输出目录会停止，不覆盖。导入和构建不会改动本机输入法，也不会上传 SSF 或素材。

## 只导入，不要求安装搜狗

```bash
python3 -B ssf_import.py /path/to/skin.ssf --out private/my-theme
```

在生成目录中调整 XML / SVG 后再构建：

```bash
python3 -B build.py --theme private/my-theme --out build/my-skin
```

首次生成安装包中的 `imported-theme/` 同样可以继续编辑，然后作为 `--theme` 的输入，输出到另一个新目录。

## 自动映射范围

| SSF 内容 | 自动处理 |
| --- | --- |
| ZIP 容器、单个 `Skin.ini` | 内存读取，支持子目录、大小写不敏感的图片引用；不直接解压整个归档 |
| UTF-8、带 BOM 的 UTF-16、GB18030 | 自动识别配置编码 |
| `Display` 字号和 RGB 颜色 | 映射字号、拼音色、首候选及普通候选色；Linux 默认字体使用 Droid Sans Fallback |
| `Scheme_H1` 单窗 PNG | 横版背景、文字边距、拉伸区域，作为必须能够转换的基本入口 |
| `Scheme_V1` 单窗 PNG | 竖版布局；缺失或不支持时保留本机原竖版并报告 |
| `StatusBar.pic`、中英/菜单坐标 | 有完整有效坐标时映射背景、中英和设置；使用 Linux 原生按钮图标 |
| V 模式 | 尺寸满足条件时生成 `minheight=300` 的专用草稿；补丁仍需另外指定构建选项 |

图片按原始字节复制。工具不会自动重绘、抠图、超分辨率修复、去除透明留白，也不会推断人物图中的方框在哪里。原案例中人工调整的字体视觉居中、三按钮摆放和图片清晰度不会凭空恢复。

## 明确需要人工处理的情况

- `Skin` 头的加密 SSF：先用其他工具解包，再传入解包目录。
- 只有 H2/V2 双窗布局、非 0 拉伸模式、动画及非 PNG 背景：当前没有可靠的自动映射；基本横版无法解析时停止，而不是猜坐标生成可安装包。
- Windows `anchor`、特殊动作、阴影、分隔线、悬停图、原素材字体或按钮语义差异：报告中会提示，先看实际需要再调整。
- 状态栏资料不完整：保留目标设备自带状态栏。Windows 全/双拼按钮与 Linux 拼音/五笔按钮不同，工具不会把两者直接当成同一种按钮。
- 竖版超过当前补丁的高度标记范围：可以生成普通皮肤，但不会声称可直接加载 V 模式补丁。

`ssfconv` 提供 SSF 解包入口和 Fcitx/Fcitx5 主题转换；加密输入可先参考其说明在本地解包，再把所得目录传给这里的 `--ssf`。本项目自己的 SSF 导入器独立实现，没有复制或依赖其转换器代码。[ssfconv 项目及用法](https://github.com/RadND/ssfconv#使用)

## 预览的含义

HTML 预览在原图上显示估算文字位置，方便发现明显的留白或坐标错误。浏览器与搜狗的字体度量、动态候选宽度、多屏缩放和按钮图标绘制不同；预览不是已经通过实机验证的承诺。先隔离验证，再决定是否安装。

## 文件与公开边界

读取归档时限制成员数、单文件及总大小，拒绝越界路径、符号链接、加密 ZIP 成员和大小写冲突。只保存引用到的 PNG，不把 SSF 的邮箱、账号或未使用文件转存到主题。

`build/`、`private/` 和 SSF 在 Git 中被忽略。生成的素材、预览及安装包保持本地私有，公开提交只包括工具源码、文档与合成测试数据。工具仍遵循原素材的使用授权；MIT 不覆盖输入的第三方皮肤。
