# ComfyUI-Qwen21-Resolution

自动识别输入图像的宽高比，匹配 **Qwen 2.1** 官方推荐分辨率并缩放图像的 ComfyUI 自定义节点。

## 官方推荐分辨率对照表

| 宽高比 | 官方分辨率 (`width × height`) |
| :---: | :---: |
| `1:1` | `2048 × 2048` |
| `4:3` | `2400 × 1792` |
| `3:4` | `1792 × 2400` |
| `3:2` | `2528 × 1696` |
| `2:3` | `1696 × 2528` |
| `16:9` | `2752 × 1536` |
| `9:16` | `1536 × 2752` |

## 功能特点

- **自动识别宽高比 (`preset = auto`)**：输入任意尺寸图像，自动计算并匹配最接近的 Qwen 2.1 官方推荐分辨率。
- **手动强制指定**：也可以在下拉菜单中直接指定固定的官方分辨率预设。
- **多种缩放与裁剪模式**：支持 `lanczos`、`bicubic`、`bilinear`、`nearest-exact`、`area`，以及 `disabled`（直接缩放）和 `center`（居中裁剪不拉伸）。
- **多端口输出**：同时输出缩放后的 `image`、`width` (`INT`)、`height` (`INT`) 和 `aspect_ratio` (`STRING`)。

## 安装方法

### 方法一：通过 Git 克隆（推荐）
进入 ComfyUI 的 `custom_nodes` 目录，运行：

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/<你的GitHub用户名>/ComfyUI-Qwen21-Resolution.git
```

### 方法二：通过 ComfyUI Manager 安装
打开 **ComfyUI Manager** -> **Install via Git URL**，粘贴本仓库的 GitHub 地址即可安装。
