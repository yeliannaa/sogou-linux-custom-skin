# 从自己的素材制作皮肤

## 目录结构

```text
private/my-theme/
  theme.json
  assets/
    horizontal.png
    vertical.png
    status.png
  overlay/ime/
    my-horizontal.svg
    wndComp.xml
    wndStatus.xml
```

`private/` 和所有生成 ZIP 都被忽略。这里只放自己有权使用的素材，不要直接复制私人迁移包进公开仓库。

先复制 `examples/minimal`。`theme.json` 中 `name` 为英文小写标识符；`updates` 按 ZIP 内 XML 路径及控件 `name` 修改属性，`$window` 表示根窗口。`overlay/ime/` 可覆盖原文件或添加新文件；直接写 XML 时可以以本机已有布局为起点，修改后的供应商布局保留在自己的私有目录。

构建：

```bash
python3 -B build.py --theme private/my-theme --out build/my-theme
```

## 图片和透明背景

SVG 可作为图片引用层。例如 `overlay/ime/my-horizontal.svg`：

```xml
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     width="450" height="112" viewBox="0 16 450 112">
  <image width="450" height="150"
         xlink:href="@@ASSET_DIR@@/horizontal.png"/>
</svg>
```

图片放在 `assets/horizontal.png`。每个 SVG 只使用一次 `@@ASSET_DIR@@`；安装器会为目标用户名生成 XML 转义后的绝对路径。大图留在外部 assets，避免耗尽保持 ZIP 原始大小所需的填充空间。

PNG 需要真实 alpha 通道。看起来像棋盘格的背景可能已经画进图片，不代表透明。修复边缘时同时用深浅背景检查白边；原任务将高分辨率图预缩放至实际绘制尺寸，采用预乘 alpha 的滤波，减少透明边缘发黑和小尺寸锯齿。单纯把位图放大并不会增加真实细节。

## 候选框

涉及 `wndComp.xml`、`wndComp_vertical.xml` 及背景 SVG：

- 窗口尺寸、背景裁切和拉伸区域一起调整；人物和端部尽量不拉伸。
- `compbk` 和 `candbk` 决定上下区块，`CompString` 和 `CandString` 决定文本区域。
- 拼音对齐不代表中文对齐；看实际字形、光标和上下留白，不只比较数字。
- 实测该构建的 `margin` 按“上、下、左、右”理解；这是搜狗布局字段，不是 CSS，其他构建需要实测。
- 调整 `wndShadow` 等定位字段会改变候选窗口与光标的间距，先比较调整前后的实机截图。
- 测试短词、长词、翻页和单独 `v`，别只看固定宽度预览。

## 人物状态栏和按钮

`wndStatus.xml` 中的 `language`、`pinyinwubi`、`setting` 可以分别放在人物旁的方框。根据图片方框中心与图标实际可见像素调整 `pos` 和 `size`；资源尺寸中心与视觉中心未必一致。

图片底部透明区域也会占窗口面积。先裁窗口视口，再区分“拖动时到不了底部”和“能拖到底部但输入后回弹”。后者在原案例中是原生坐标限制，需要对应的可选补丁，单改 PNG 没有解决。

## V 模式

正常横排布局不一定能容纳 `v` 的帮助/计算器内容。可以提供 `wndComp_vmode.xml` 竖版布局，再启用经过验证的 `v_mode_fix.c`。

当前补丁用 `minheight=300` 识别专用布局，普通横版不能使用同一标记。示例 `theme.json` 的 `v_mode` 会在本机竖版 XML 基础上生成这个专用文件；具体图像、留白仍需根据自己的素材调整。

## 先预览再应用

构建只产出安装目录。先检查 XML、SVG 和图片，再在隔离桌面/测试用户验证完整渲染，确认后才执行 `install.sh --activate`。不要把“打包成功”和“所有桌面效果都已经验证”混为一谈。
