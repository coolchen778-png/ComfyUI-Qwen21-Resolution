# ComfyUI cbkk 节点

本插件提供三个 `cbkk` 分类的 ComfyUI 节点：

- `cbkk｜Skill 知识库加载器`：独立加载或自定义 Skill 知识库规则，支持下拉选择本地文件、手动输入规则及链式多节点串联。
- `cbkk｜Skill 提示词生成器`：按顺序联合多个 Skill，支持本地模型或 OpenAI/NewAPI 兼容接口，可连接 0–5 张参考图。
- `cbkk｜Qwen 2.1 分辨率自动匹配`：按输入图片宽高比选择 Qwen 2.1 推荐分辨率。

## 安装与更新

在 ComfyUI 的 `custom_nodes` 目录中执行：

```powershell
git clone https://github.com/coolchen778-png/ComfyUI-Qwen21-Resolution.git
```

如果已安装，在插件目录中执行：

```powershell
git pull
```

然后完全重启 ComfyUI，并强制刷新浏览器页面（`Ctrl+F5`）。

## 本地模型放置

节点会递归扫描：

```text
ComfyUI/models/llm/
```

支持两类主模型：

```text
ComfyUI/models/llm/Qwen-GGUF/qwen-vl-q4.gguf
ComfyUI/models/llm/Qwen-Transformers/config.json
ComfyUI/models/llm/Qwen-Transformers/*.safetensors
```

GGUF 视觉投影文件单独放置，文件名需包含 `mmproj`：

```text
ComfyUI/models/llm/Qwen-GGUF/mmproj-qwen-vl-f16.gguf
```

节点中的本地模型区有两个选择框：

- `主模型`：选择普通 GGUF 文件或 Transformers 模型文件夹。
- `视觉投影模型（mmproj）`：仅在 GGUF 模型时需要；选择 Transformers 模型时会自动隐藏。

新增或移动模型后，请重启 ComfyUI，再重新添加节点或刷新页面。

## Skill 使用

Skill 支持 UTF-8 编码的 `.md` 和 `.txt` 文件，可以同时选择任意多个，并通过拖拽调整联合顺序。Skill 数量没有硬性上限，实际数量取决于模型上下文容量。

在节点内点击绿色的 `⬆ 上传 Skill` 按钮，上传后会自动加入已选列表。节点还会额外显示一个 `⬆ 上传 Skill 文件` 备用按钮，即使当前 ComfyUI 版本无法显示复杂面板，也能上传 Skill。

Skill 文件存放位置：

- 插件内置：`插件目录/skills/`
- 用户上传：`ComfyUI/user/qwen_skill_prompt/skills/`

单个上传文件最大 1 MiB，同名文件不会被覆盖。

## 运行方式

### 本地模型

选择“本地模型”后，只需选择主模型；GGUF 视觉模型再选择对应的 mmproj。节点会自动判断 GGUF 或 Transformers 加载方式。

本地依赖需安装在 ComfyUI 实际使用的 Python 环境中：

- GGUF：与系统、Python 和 CUDA 匹配的 `llama-cpp-python`。
- Transformers/Safetensors：`transformers` 和 `accelerate`，以及模型自身要求的处理器依赖。

### 在线 API

选择“在线 API”后，界面只显示 OpenAI/NewAPI 兼容参数。例如：

```text
API 地址 = https://newapi.example.com/v1
API 模型名 = qwen-vl-compatible-model
API Key 环境变量 = OPENAI_API_KEY
```

API Key 不会保存在工作流中，请在启动 ComfyUI 前设置环境变量：

```powershell
$env:OPENAI_API_KEY = "your-secret"
python main.py
```

## 输出

- `final_prompt`：可选移除 `<think>` 段后的最终提示词。
- `raw_response`：模型的原始响应。
- `combined_skills`：按界面顺序合并的 Skill 全文。

## 常见问题

- `主模型` 列表为空：确认文件位于 `ComfyUI/models/llm`，Transformers 目录内必须有 `config.json`，然后重启 ComfyUI 并按 `Ctrl+F5`。
- 找不到 mmproj：确认它是 `.gguf` 文件，且文件名包含 `mmproj`。
- 找不到 Skill 上传：完全重启 ComfyUI 并按 `Ctrl+F5`；节点中应同时有上传备用按钮。
- API 返回错误：确认端点支持 `/v1/chat/completions` 和多模态 `image_url` data URI。
