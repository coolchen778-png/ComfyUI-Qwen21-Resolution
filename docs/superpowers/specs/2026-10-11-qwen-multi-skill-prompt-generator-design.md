# Qwen 多 Skill 提示词生成器设计

## 目标

在现有 ComfyUI 自定义节点仓库中新增一个单节点提示词生成器。用户可以按顺序组合任意数量的本地 Skill 文件，输入任务描述和最多五张参考图，并选择本地 GGUF、本地 Transformers/Safetensors 或 OpenAI 兼容在线 API（包括 NewAPI）生成最终提示词。

现有 `Qwen21ResolutionResize` 节点保持独立，行为与接口不变。

## 成功标准

- ComfyUI 画布只需一个生成节点即可完成 Skill 选择、图片输入、模型调用和文本输出。
- Skill 支持搜索、多选、排序、刷新和上传，工作流保存稳定的相对文件标识。
- 支持 0 至 5 张参考图，并保持端口顺序。
- 支持 GGUF、Transformers/Safetensors、OpenAI Chat Completions 兼容 API 三类后端。
- 优先兼容 Qwen 视觉语言模型，同时允许运行时支持的通用多模态模型。
- 原版、非蒸馏或推理型模型的 `<think>` 内容可以清理，同时保留原始响应。
- 缺少某个可选后端依赖时，插件和其他后端仍能正常使用。
- 不在日志中泄露 API 密钥或授权请求头。

## 非目标

- 不负责下载、量化或转换模型。
- 不保证旧版 `llama-cpp-python` 能运行其尚未实现的视觉架构。
- 首版不支持视频、音频、流式输出、批量任务或 Responses API。
- 首版不允许 Skill 执行代码；Skill 仅作为 UTF-8 文本读取。

## 用户界面

节点显示名为 `Qwen 多 Skill 提示词生成器`，分类为 `Qwen2.1/Skill Prompt`。

### 公共输入

- `task`: 多行任务描述，必填。
- `skills`: 自定义可搜索多选控件。支持刷新、上传、拖动排序和移除。
- `backend`: `GGUF`、`Transformers`、`Online API`。
- `image_1` 至 `image_5`: 五个可选 `IMAGE` 输入端口。
- `max_new_tokens`: 最大生成 token 数。
- `temperature`: 采样温度。
- `seed`: 随机种子；后端支持时使用。
- `strip_thinking`: 是否从最终提示词中移除 `<think>...</think>` 区段，默认开启。
- `unload_after_generate`: 生成后是否卸载本地模型，默认关闭；在线后端忽略此项。

前端扩展根据 `backend` 隐藏无关参数，但所有值仍保存在工作流中，切换后端不会丢失配置。

### GGUF 参数

- 主模型路径。
- 可选 `mmproj` 路径。
- handler：`auto`、`mtmd`、运行时发现的 Qwen VL handler。
- 上下文长度、GPU layers、threads、batch size 和 flash attention。

`auto` 优先使用显式可用的多模态 handler，再使用 GGUF 元数据中的模板。存在图片但运行时只能创建纯文本会话时必须报错，不得忽略图片继续生成。

### Transformers 参数

- 本地模型目录或 Hugging Face 模型标识。
- device map、dtype、attention implementation。
- `trust_remote_code`，默认关闭。
- 可选本地文件模式，默认开启，避免意外联网。

实现优先使用 `AutoProcessor` 和模型提供的多模态 chat template。模型自动类不可用时，对已支持的 Qwen 架构使用小范围显式回退，不维护自定义聊天模板副本。

### Online API 参数

- `base_url`。
- `model`。
- API 密钥环境变量名，默认 `OPENAI_API_KEY`。
- 请求超时。
- 可选自定义 headers JSON；`Authorization` 仍优先由密钥环境变量生成。
- 在线图片最大边长，默认 `2048`；设为 `0` 时不缩放。

首版调用 OpenAI 兼容的 `/v1/chat/completions`。`base_url` 既可以填写到 `/v1`，也可以填写完整 Chat Completions URL；实现必须规范化一次，不能重复追加路径。

### 输出

- `final_prompt`: 清理后的最终提示词。
- `raw_response`: 后端返回的原始助手文本。
- `combined_skills`: 实际发送的合并 Skill 文本。

## Skill 存储与选择

Skill 管理器递归扫描两个根目录：

1. 插件目录内的 `skills/`，用于随插件分发示例或内置 Skill。
2. `folder_paths.get_user_directory()/qwen_skill_prompt/skills`，用于用户上传和长期保存；脱离 ComfyUI 的测试环境使用显式注入的临时目录，不自行猜测用户路径。

只接受 `.md` 和 `.txt`，按 UTF-8 读取。列表项使用“来源 + 相对路径”作为稳定标识。上传文件只写入用户 Skill 目录；文件名冲突时拒绝覆盖并返回可理解的错误。

所有解析后的绝对路径必须仍位于获准根目录中。拒绝 `..` 越界、绝对路径注入、目录项、非允许扩展名以及解析后逃逸根目录的符号链接。

Skill 按用户排序拼接，每份内容使用明确边界：

```text
<skill name="relative/path.md" index="1">
...文件内容...
</skill>
```

空文件会被保留名称并产生警告。读取失败属于执行错误，不静默跳过。节点不会擅自截断 Skill；如果上下文预算明显不足，会在调用模型前提示用户减少 Skill、图片或任务文本。

## 消息构造与数据流

1. 验证 Skill 标识、后端参数和图片数量。
2. 按 UI 顺序读取并合并 Skill。
3. 构造 system 消息：固定的提示词生成职责说明，加上合并后的 Skill 文本。
4. 构造 user 消息：按 `image_1` 至 `image_5` 顺序加入图片块，最后加入任务描述文本块。
5. 将统一中间消息交给所选后端适配器。
6. 解析助手文本为 `raw_response`。
7. 根据 `strip_thinking` 生成 `final_prompt`。清理仅删除完整或未闭合的 `<think>` 前导区段，不修改正文中的普通 XML/HTML。
8. 输出三个字符串；若开启卸载，则在 `finally` 阶段释放本地模型。

图片从 ComfyUI 的 `[B, H, W, C]` tensor 转为 RGB 图像。首版每个端口只使用 batch 中第一张图；若某端口 batch 大于 1，明确报错，避免隐式丢图。在线后端将处理后的图片编码为 data URI，本地后端使用内存图像对象或运行时要求的 data URI。

## 后端边界

三个后端实现相同接口：验证配置、生成缓存键、加载、生成、卸载。节点层不导入具体推理库。

### GGUF

延迟导入 `llama_cpp`。handler 通过能力探测选择，不通过版本号猜测。优先支持运行时提供的 MTMD、Qwen2.5-VL 及其他 Qwen VL handler。无法识别当前模型/投影组合时返回包含已发现 handler 的错误信息。

参考：[`llama-cpp-python` 多模态模型说明](https://github.com/abetlen/llama-cpp-python/blob/main/README.md)。

### Transformers

延迟导入 `transformers`。通过 `AutoProcessor` 读取模型自带多模态模板，以 OpenAI 风格内容块组织消息，再调用 image-to-text 生成接口。模型输出只解码新生成 token，不重复输入提示。

参考：[Hugging Face 多模态聊天模板](https://huggingface.co/docs/transformers/main/chat_templating_multimodal)。

### Online API / NewAPI

使用 Python 标准库发出 HTTPS/HTTP POST，避免为在线后端增加强制 SDK 依赖。图片使用 `image_url` data URI 内容块。解析 `choices[0].message.content`，并兼容 content 为文本块数组的返回形式。

密钥仅从指定环境变量读取。错误消息可以包含 HTTP 状态码和经过长度限制的响应正文，但必须递归脱敏 `Authorization`、`api-key`、`x-api-key` 以及实际密钥值。

## 缓存、显存与并发

本地模型缓存键由后端类型、规范化模型路径、投影路径和全部加载参数组成。同一缓存键复用模型；配置变化会创建不同实例。

缓存访问使用进程内锁，防止 ComfyUI 并发队列重复加载同一模型。首版每个已加载模型的生成调用串行化，以避免底层运行时线程安全问题。

开启卸载时，在生成成功或失败后的 `finally` 中：

- 从缓存移除当前实例。
- 调用后端可用的关闭/释放接口。
- 删除 Python 引用并运行垃圾回收。
- CUDA 可用时调用空缓存；不宣称能强制回收其他节点持有的显存。

## 错误处理

错误统一包含阶段标签：`Skill 读取`、`图片转换`、`模型加载`、`请求发送`、`响应解析` 或 `生成`。用户可直接在 ComfyUI 错误面板看到解决方向。

以下情况必须停止执行：

- 没有选择任何 Skill。
- 任务描述为空。
- 第六张或更多图片以任何方式进入执行层。
- 图片端口包含 batch 大于 1。
- Skill 越界、扩展名不合法或读取失败。
- 使用图片时所选本地 handler/processor 不具备视觉能力。
- API 密钥环境变量不存在。
- API 响应缺少助手文本。

不输出 API 密钥、完整授权头或无限长度的服务端错误页面。

## 文件组织

- `nodes.py`: 保留现有分辨率节点，并注册新节点。
- `skill_prompt/node.py`: ComfyUI 输入输出定义和执行编排。
- `skill_prompt/skills.py`: Skill 扫描、上传、验证和合并。
- `skill_prompt/images.py`: tensor、PIL 和 data URI 转换。
- `skill_prompt/backends/base.py`: 适配器协议、缓存和公共错误。
- `skill_prompt/backends/gguf.py`: `llama-cpp-python` 适配器。
- `skill_prompt/backends/transformers_backend.py`: Transformers 适配器。
- `skill_prompt/backends/openai_compatible.py`: Online API/NewAPI 适配器。
- `skill_prompt/response.py`: 响应抽取和 `<think>` 清理。
- `routes.py`: Skill 列表和上传 HTTP 路由。
- `web/js/qwen_skill_prompt.js`: 多选、排序、刷新、上传和条件显隐。
- `tests/`: 纯逻辑、适配器协议和节点编排测试。
- `README.md`: 安装、三后端配置、安全提示和示例工作流说明。

## 测试与验收

自动测试不下载模型，也不要求 GPU：

- Skill 双根目录扫描、稳定排序、选择顺序和合并边界。
- 路径穿越、符号链接逃逸、扩展名和上传冲突保护。
- 0 至 5 张图片消息顺序，以及第六张图和 batch 大于 1 的拒绝。
- ComfyUI tensor 到图像、在线缩放和 data URI 编码。
- 三后端路由、配置验证、缓存键、复用与卸载。
- GGUF/Transformers 使用伪运行时验证能力探测和消息映射。
- API URL 规范化、请求 JSON、响应变体、超时和密钥脱敏。
- `<think>` 完整、未闭合、无推理段及正文标签场景。
- 新节点注册和现有分辨率节点回归。

仓库验证命令包括 Python 编译检查和完整测试集。完成自动测试后，在真实 ComfyUI 中至少进行以下人工验收：

1. 多选、排序、刷新和上传 Skill。
2. 使用五张图片生成并检查顺序。
3. 至少运行一个本地后端和一个 NewAPI/OpenAI 兼容端点。
4. 检查后端切换后的字段显隐和配置保留。
5. 检查卸载开关与 ComfyUI 重启后的工作流恢复。

## 依赖与安装策略

插件核心不强制安装推理后端。GGUF 用户自行安装与其 CPU/CUDA 环境匹配且具备所需多模态 handler 的 `llama-cpp-python`；Transformers 用户安装与模型兼容的 `transformers`、`accelerate` 及模型要求的可选包。README 提供检测命令和错误对照，不提供可能覆盖用户 CUDA 环境的一键强制安装。
