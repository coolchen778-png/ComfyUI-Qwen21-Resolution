# ComfyUI Qwen 多 Skill 提示词工具

本插件提供两个 ComfyUI 节点：

- `Qwen 多 Skill 提示词生成器`：按顺序联合多个 Skill，可接入 0–5 张参考图，通过本地 GGUF、本地 Transformers/Safetensors 或 OpenAI 兼容 API（包括 NewAPI）生成最终提示词。
- `Qwen 2.1 官方分辨率自动匹配缩放`：保留原有功能，按输入宽高比匹配 Qwen 2.1 推荐分辨率。

多 Skill 节点并不限定蒸馏模型。只要模型及其处理器支持对应的文本/视觉输入，即可使用普通版、指令版或兼容版本的视觉语言模型；Qwen 系列具有专门的加载回退，其他模型优先走 Transformers 通用自动类。

## 安装

将仓库放入 ComfyUI 的 `custom_nodes` 目录，然后重启 ComfyUI：

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/coolchen778-png/ComfyUI-Qwen21-Resolution.git
```

也可以在 ComfyUI Manager 中选择 “Install via Git URL”。

插件不会强制安装或选择 CUDA 推理包。只安装实际使用的后端依赖：

- 在线 API：无需额外推理依赖。
- Transformers/Safetensors：在 ComfyUI 的 Python 环境中安装 `transformers` 和 `accelerate`，并按模型说明补充处理器依赖。
- GGUF：安装与操作系统、Python、CPU/CUDA 环境匹配的 `llama-cpp-python`。不同构建支持的视觉 handler 可能不同。

## Skill 文件

支持递归扫描 UTF-8 编码的 `.md` 和 `.txt` 文件。节点界面提供搜索、添加、删除、拖拽排序、刷新和上传；合并顺序就是界面中的已选顺序，至少需要选择一个 Skill。

目录分为两类：

- 内置 Skill：插件目录下的 `skills/`。
- 用户 Skill：`ComfyUI/user/qwen_skill_prompt/skills/`；准确根目录以当前 ComfyUI 的用户目录为准。

上传文件只会保存到用户 Skill 目录，最大 1 MiB，不覆盖同名文件。工作流保存的是类似 `builtin:photo/a.md`、`user:style.txt` 的安全 ID，不保存任意绝对路径。

## 节点用法

1. 在 `Qwen/Prompt` 分类添加 `Qwen 多 Skill 提示词生成器`。
2. 在 Skill 面板中选择一个或多个 Skill，并拖拽确定联合顺序。
3. 填写任务描述；按需连接 `image_1` 到 `image_5`。每个端口只接受 `batch=1`，不允许第六张图。
4. 选择 `gguf`、`transformers` 或 `online_api`。界面只显示当前后端相关字段，切换时不会删除其他后端已经填写的值。
5. 执行节点并使用三个输出之一。

当前版本没有内置截图；节点加载后即可看到与上述流程对应的 Skill 双栏选择器。

### 公共字段

| 字段 | 说明 |
| --- | --- |
| `task` | 要生成或改写的图像提示词任务。 |
| `role_prompt` | 模型角色和输出要求，会与合并后的 Skill 一起进入 system prompt。 |
| `max_new_tokens` | 最大生成 token 数。 |
| `temperature` / `seed` | 采样温度和随机种子。 |
| `strip_thinking` | 清理响应开头完整或未闭合的 `<think>` 段。 |
| `unload_after_generate` | 本次请求结束后卸载本地缓存模型；失败路径同样执行。在线 API 无需卸载。 |

### GGUF / llama.cpp

- `gguf_model_path`：本地 `.gguf` 模型完整路径。
- `gguf_mmproj_path`：视觉投影文件路径；带图请求通常需要。
- `gguf_handler`：`auto` 优先 MTMD，其次按模型名选择 Qwen2.5-VL 或 Qwen3-VL handler，也可显式指定。
- `gguf_n_ctx`、`gguf_n_gpu_layers`、`gguf_n_threads`、`gguf_n_batch`、`gguf_flash_attn`：直接用于模型加载。

模型、投影文件和全部加载参数共同组成缓存键。明显超过 `n_ctx` 的文本预算会在生成前报错。

### Transformers / Safetensors

- `transformers_model`：本地模型目录，或在关闭 `transformers_local_files_only` 后使用 Hugging Face 模型标识。
- `transformers_device_map`：默认 `auto`，也支持 `cpu`、`cuda`、`cuda:0` 等。
- `transformers_dtype`：`auto`、`float16`、`bfloat16` 或 `float32`。
- `transformers_attention_implementation`：`auto`、`eager`、`sdpa` 或 `flash_attention_2`。
- `transformers_trust_remote_code`：默认关闭；只有信任模型仓库代码时才开启。
- `transformers_local_files_only`：默认开启，因此不会自动下载模型。

带图请求要求模型的 processor 具有视觉处理器。已知上下文上限时，输入 token 与输出预算超限会在推理前停止。

### OpenAI 兼容 API / NewAPI

API 密钥不会保存在工作流中，只从 `api_key_env` 指定的环境变量读取。PowerShell 临时示例：

```powershell
$env:OPENAI_API_KEY = "your-secret"
python main.py
```

NewAPI 示例配置：

```text
api_base_url = https://newapi.example.com/v1
api_model = qwen-vl-compatible-model
api_key_env = OPENAI_API_KEY
api_custom_headers = {}
```

`api_base_url` 可填写站点根地址、`/v1` 地址或完整 `/chat/completions` 地址，插件只规范化一次。`api_custom_headers` 必须是字符串键值 JSON，禁止在其中覆盖 `Authorization`。`api_max_image_side=0` 表示不缩放；其他正值会按最长边等比缩小 PNG。

## 输出

| 输出 | 内容 |
| --- | --- |
| `final_prompt` | 可选清理 `<think>` 后的最终提示词。 |
| `raw_response` | 后端返回的原始助手文本，便于排查模型行为。 |
| `combined_skills` | 按选择顺序带 `<skill>` 边界合并的完整 Skill 文本。 |

## 分辨率节点

原节点仍提供 `1:1`、`4:3`、`3:4`、`3:2`、`2:3`、`16:9`、`9:16` 七组预设，支持自动匹配、手动预设以及多种缩放/裁剪方式。

## 常见问题

- “缺少 llama-cpp-python / transformers / accelerate”：在 ComfyUI 实际使用的 Python 环境中安装对应可选依赖，重启后重试。
- “图片输入需要可用视觉 handler”：当前 `llama-cpp-python` 构建没有发现适合的 MTMD/Qwen handler，或没有配置正确的投影文件。
- “所选处理器不支持视觉输入”：当前 Transformers 模型/processor 是纯文本能力；换用视觉语言模型及配套 processor。
- Skill 不显示：确认扩展名、UTF-8 编码和目录位置，然后点击“刷新”。同名上传不会覆盖。
- API 返回错误：确认 NewAPI/OpenAI 兼容端点支持 `/v1/chat/completions` 及多模态 `image_url` data URI。错误正文会限制长度并对密钥、授权头脱敏。

## 真实环境验收清单

自动测试不包含真实模型和真实 API 凭据。发布前建议在目标 ComfyUI 中验证：Skill 搜索/多选/排序/上传、五图顺序、至少一个本地后端、一个 NewAPI 端点、后端字段显隐、工作流保存后重载，以及卸载选项是否释放目标设备显存。
