# Qwen 多 Skill 提示词生成器实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个 ComfyUI 单节点，用任意多个有序 Skill、任务文本和最多五张参考图，通过 GGUF、Transformers 或 OpenAI 兼容 API 生成提示词。

**Architecture:** 节点层只负责验证、构造统一 `PromptRequest` 和路由；Skill、图片、响应清理、模型缓存以及三个后端分别放在独立模块。前端扩展提供 Skill 多选和后端字段显隐，HTTP 路由只暴露安全的列表与上传操作。

**Tech Stack:** Python 3.10+、PyTorch/ComfyUI、Pillow、可选 `llama-cpp-python`、可选 Hugging Face Transformers/Accelerate、标准库 `urllib`、ComfyUI Web Extension JavaScript、pytest。

**Spec:** `docs/superpowers/specs/2026-10-11-qwen-multi-skill-prompt-generator-design.md`

## Global Constraints

- 保持 `Qwen21ResolutionResize` 的接口和行为不变。
- 接受 0–5 个独立 `IMAGE` 端口；任一端口 batch 大于 1 时停止，不隐式丢图。
- 至少选择一个 UTF-8 `.md`/`.txt` Skill，按用户顺序合并，禁止路径逃逸。
- 推理后端必须延迟导入；缺少一个可选依赖不得阻止插件或其他后端加载。
- 在线首版只实现 OpenAI 兼容 `/v1/chat/completions`，包括 NewAPI。
- API 密钥只从指定环境变量读取，日志和异常不得泄露密钥或授权头。
- `trust_remote_code` 默认关闭；Transformers 默认只使用本地文件。
- 不自动下载、量化或转换模型，不强制安装任何 CUDA 版推理包。
- 输出顺序固定为 `final_prompt`、`raw_response`、`combined_skills`。

## Review Focus

- 损坏的 Skill JSON、重复 Skill ID 或空选择应在模型加载前给出明确错误；Task 8 的编排测试覆盖。
- 非 UTF-8、读取中途被删除或符号链接逃逸的 Skill 不得被静默跳过；Task 2 的安全测试覆盖。
- 含 NaN、越界像素、灰度/四通道或 batch 大于 1 的图像必须得到确定处理或错误；Task 3 的图像测试覆盖。
- 带尾斜线、路径前缀或完整端点的 NewAPI URL 只能规范化一次；Task 5 的 URL 参数化测试覆盖。
- 空响应、文本块数组、服务端 HTML 错误和包含密钥的错误正文必须安全解析/脱敏；Task 5 的响应与错误测试覆盖。

---

## 文件结构

- `skill_prompt/types.py`: 统一请求、生成参数和后端配置数据结构。
- `skill_prompt/errors.py`: 带阶段标签的公开异常与脱敏工具。
- `skill_prompt/response.py`: 助手文本抽取和 `<think>` 清理。
- `skill_prompt/skills.py`: 双根目录 Skill 扫描、读取、上传与合并。
- `skill_prompt/images.py`: ComfyUI tensor、PIL、缩放和 data URI 转换。
- `skill_prompt/messages.py`: 统一 system/user 消息构造。
- `skill_prompt/backends/base.py`: 适配器协议、注册表与线程安全模型缓存。
- `skill_prompt/backends/openai_compatible.py`: OpenAI/NewAPI Chat Completions 适配器。
- `skill_prompt/backends/transformers_backend.py`: Transformers 多模态适配器。
- `skill_prompt/backends/gguf.py`: llama.cpp 多模态适配器。
- `skill_prompt/node.py`: ComfyUI 节点定义、验证与执行编排。
- `routes.py`: ComfyUI Skill 列表和上传路由。
- `web/js/qwen_skill_prompt.js`: Skill 多选、排序、刷新/上传和字段显隐。
- `tests/`: 与上述模块同名的 pytest 测试。
- `nodes.py`, `__init__.py`, `README.md`: 注册、Web 目录导出和用户文档。

### Task 1: 核心类型、阶段错误与响应清理

**Files:**
- Create: `skill_prompt/__init__.py`
- Create: `skill_prompt/types.py`
- Create: `skill_prompt/errors.py`
- Create: `skill_prompt/response.py`
- Test: `tests/test_response.py`

**Interfaces:**
- Produces: `PromptRequest(system_prompt: str, task: str, images: tuple[Any, ...], max_new_tokens: int, temperature: float, seed: int)`。
- Produces: `SkillPromptError(stage: str, message: str)`、`redact_secrets(value: str, secrets: Iterable[str]) -> str`。
- Produces: `extract_assistant_text(payload: Mapping[str, Any]) -> str`、`strip_leading_think(text: str) -> str`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_response.py` 覆盖：字符串 content、文本块数组、缺少文本时报 `SkillPromptError("响应解析", ...)`、完整和未闭合的前导 `<think>`、正文内普通标签不被删除，以及错误字符串中的实际密钥/Authorization 被替换为 `[REDACTED]`。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_response.py -q`

Expected: FAIL，原因是 `skill_prompt.response` 尚不存在。

- [ ] **Step 3: 实现最小核心接口**

实现上述签名；`strip_leading_think` 只处理字符串开头的可选空白和第一个 `<think>` 区段，`extract_assistant_text` 接受 `choices[0].message.content` 的字符串或 `{type: "text", text: ...}` 数组。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_response.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

Run: `git add skill_prompt tests/test_response.py`

Run: `git -c user.name="coolchen778-png" -c user.email="coolchen778@gmail.com" commit -m "feat: add prompt response core"`

### Task 2: 安全的 Skill 管理器

**Files:**
- Create: `skill_prompt/skills.py`
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: `SkillPromptError` from Task 1。
- Produces: `SkillRoot(source: Literal["builtin", "user"], path: Path)`、`SkillEntry(id: str, source: str, relative_path: str)`。
- Produces: `SkillManager(roots: Sequence[SkillRoot])` with `list_skills() -> list[SkillEntry]`, `combine(skill_ids: Sequence[str]) -> str`, `save_upload(filename: str, content: bytes) -> SkillEntry`。

- [ ] **Step 1: 写扫描与顺序失败测试**

创建临时 builtin/user 根目录，断言仅递归列出 UTF-8 `.md/.txt`，ID 为 `builtin:path/to/a.md` 或 `user:b.txt`，列表稳定排序，`combine([second, first])` 严格保留选择顺序和 `<skill name=... index=...>` 边界。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_skills.py -q`

Expected: FAIL，原因是 `SkillManager` 尚不存在。

- [ ] **Step 3: 实现扫描、解析与合并**

所有路径先 `resolve()` 再用 `Path.is_relative_to(root.resolve())` 校验；读取必须使用 `encoding="utf-8"`；读取失败以 `SkillPromptError("Skill 读取", ...)` 包装且不跳过。

- [ ] **Step 4: 写安全和上传失败测试**

覆盖 `..`、绝对路径、非 UTF-8、读取前删除、目录、非法扩展名、符号链接逃逸、上传重名、上传文件名含路径分隔符；同时用 `pytest.warns` 断言空文件保留边界并产生警告。

- [ ] **Step 5: 实现上传与全部防护**

`save_upload` 只写 source=`user` 的根目录，使用独占创建避免覆盖；不存在 user 根时创建目录，拒绝路径分隔符和非 `.md/.txt`。

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_skills.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

Run: `git add skill_prompt/skills.py tests/test_skills.py`

Run: `git -c user.name="coolchen778-png" -c user.email="coolchen778@gmail.com" commit -m "feat: add secure skill management"`

### Task 3: 图像转换与统一消息

**Files:**
- Create: `skill_prompt/images.py`
- Create: `skill_prompt/messages.py`
- Test: `tests/test_images.py`
- Test: `tests/test_messages.py`

**Interfaces:**
- Consumes: `PromptRequest`, `SkillPromptError` from Task 1。
- Produces: `tensor_to_pil(image: torch.Tensor) -> PIL.Image.Image`、`prepare_images(values: Sequence[torch.Tensor | None]) -> tuple[Image.Image, ...]`。
- Produces: `resize_for_api(image: Image.Image, max_side: int) -> Image.Image`、`image_to_data_uri(image: Image.Image, max_side: int) -> str`。
- Produces: `build_openai_messages(request: PromptRequest, image_encoder: Callable[[Image.Image], str]) -> list[dict[str, Any]]`、`estimate_text_tokens(*texts: str) -> int`。

- [ ] **Step 1: 写图像失败测试**

断言 `[1,H,W,3]` float tensor 转 RGB、像素裁剪到 `[0,1]`、NaN/Inf 变为有限值、灰度和 RGBA 变 RGB、最长边按比例缩至精确上限、`max_side=0` 不缩放、data URI 可解码为 PNG；batch 大于 1 和非四维 tensor 报 `图片转换` 错误。

- [ ] **Step 2: 运行图像测试确认失败**

Run: `python -m pytest tests/test_images.py -q`

Expected: FAIL，原因是转换函数尚不存在。

- [ ] **Step 3: 实现图像转换**

只接受通道数 1、3、4；使用 `torch.nan_to_num(...).clamp(0, 1)`，灰度复制为 RGB，RGBA 丢弃 alpha，API 缩放使用 Lanczos。

- [ ] **Step 4: 写消息顺序失败测试**

断言 system 消息只有职责说明和 `combined_skills`，user content 依次为 image 1–5 再 task 文本；0 图时只有文本；第六张图片构造 `PromptRequest` 时由验证函数拒绝；token 粗估值为所有 UTF-8 文本字节数除以 3 后向上取整，用于只拦截明显超过上下文的请求。

- [ ] **Step 5: 实现消息构造与 token 粗估**

实现上述两个接口；粗估只为本地后端的提前报错服务，不用于截断或改写文本。

- [ ] **Step 6: 运行两组测试**

Run: `python -m pytest tests/test_images.py tests/test_messages.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

Run: `git add skill_prompt/images.py skill_prompt/messages.py tests/test_images.py tests/test_messages.py`

Run: `git -c user.name="coolchen778-png" -c user.email="coolchen778@gmail.com" commit -m "feat: add multimodal request conversion"`

### Task 4: 后端协议、注册表与模型缓存

**Files:**
- Create: `skill_prompt/backends/__init__.py`
- Create: `skill_prompt/backends/base.py`
- Test: `tests/test_backend_base.py`

**Interfaces:**
- Consumes: `PromptRequest` from Task 1。
- Produces: `BackendAdapter` protocol with `validate(config, has_images)`, `cache_key(config)`, `generate(request, config) -> str`, `unload(config) -> None`。
- Produces: `BackendRegistry.register(name: str, adapter: BackendAdapter)`, `get(name: str) -> BackendAdapter`。
- Produces: `ModelCache.get_or_load(key: Hashable, loader: Callable[[], Any]) -> Any`, `generation_lock(key)`, `unload(key, closer)`。

- [ ] **Step 1: 写注册和并发失败测试**

覆盖未知后端错误、重复注册替换规则、相同 key 只调用一次 loader、不同 key 独立缓存、同 key 生成锁串行化、loader 失败不污染缓存、unload 调用 closer 并移除实例。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_backend_base.py -q`

Expected: FAIL，原因是后端基础模块尚不存在。

- [ ] **Step 3: 实现协议、注册表与缓存**

使用 `threading.RLock` 保护缓存字典，并为每个缓存 key 保存独立生成锁；公开错误统一使用 `SkillPromptError`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_backend_base.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

Run: `git add skill_prompt/backends tests/test_backend_base.py`

Run: `git -c user.name="coolchen778-png" -c user.email="coolchen778@gmail.com" commit -m "feat: add backend registry and model cache"`

### Task 5: OpenAI/NewAPI 后端

**Files:**
- Create: `skill_prompt/backends/openai_compatible.py`
- Test: `tests/test_openai_compatible.py`

**Interfaces:**
- Consumes: `BackendAdapter`, `PromptRequest`, `build_openai_messages`, `extract_assistant_text`, `redact_secrets`。
- Produces: `normalize_chat_completions_url(base_url: str) -> str`。
- Produces: `OpenAICompatibleBackend(opener: Callable = urllib.request.urlopen)` implementing `BackendAdapter`。

- [ ] **Step 1: 写 URL 与配置失败测试**

参数化断言 `https://host`、`https://host/`、`https://host/v1`、`https://host/prefix/v1/` 和完整 `/chat/completions` 只追加一次；拒绝非 HTTP(S)、空 model、缺失密钥环境变量、非法 headers JSON，以及自定义 `Authorization` 覆盖环境变量密钥。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_openai_compatible.py -q`

Expected: FAIL，原因是 API 后端尚不存在。

- [ ] **Step 3: 实现 URL、请求和配置验证**

使用标准库 `urllib.request.Request`；JSON 包含 model、messages、max_tokens、temperature、seed；先应用自定义 headers，再强制设置 `Authorization: Bearer <env secret>`。

- [ ] **Step 4: 写响应和脱敏失败测试**

伪 opener 覆盖字符串 content、文本块数组、空 choices、超时、HTTP JSON 错误、HTML 长错误和正文包含真实密钥；断言错误阶段、正文长度上限和 `[REDACTED]`。

- [ ] **Step 5: 实现响应解析与错误包装**

网络错误标记 `请求发送`，JSON/结构错误标记 `响应解析`；服务端正文最多保留 2,000 字符并经过 header 名与实际密钥脱敏。

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_openai_compatible.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

Run: `git add skill_prompt/backends/openai_compatible.py tests/test_openai_compatible.py`

Run: `git -c user.name="coolchen778-png" -c user.email="coolchen778@gmail.com" commit -m "feat: add OpenAI compatible backend"`

### Task 6: Transformers/Safetensors 后端

**Files:**
- Create: `skill_prompt/backends/transformers_backend.py`
- Test: `tests/test_transformers_backend.py`

**Interfaces:**
- Consumes: `BackendAdapter`, `ModelCache`, `PromptRequest`, `SkillPromptError`。
- Produces: `TransformersBackend(runtime_loader: Callable | None = None)` implementing `BackendAdapter`。
- Produces: `_load_runtime()` lazy import boundary returning the required AutoProcessor/model/torch symbols for test substitution。

- [ ] **Step 1: 写延迟导入和配置失败测试**

不安装/不导入真实 Transformers，使用伪 runtime 断言模块导入成功；验证空模型、非法 dtype/device/attention、默认 `local_files_only=True`、默认 `trust_remote_code=False`，并断言缺依赖错误包含安装方向。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_transformers_backend.py -q`

Expected: FAIL，原因是 Transformers 后端尚不存在。

- [ ] **Step 3: 实现加载、缓存键与能力检查**

使用 `AutoProcessor.from_pretrained`；优先 `AutoModelForImageTextToText`，不可用时只对已识别 Qwen 配置选择运行时暴露的 Qwen 条件生成类；含图片但 processor 无多模态模板/图像处理器时停止。

- [ ] **Step 4: 写生成与卸载失败测试**

伪 processor/model 断言消息中使用 PIL 图像块，`apply_chat_template(..., tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt")`，只解码输入长度之后的 token；已知 `max_position_embeddings` 时，输入 token 加 `max_new_tokens` 超限会在 `generate` 前报错；同配置复用模型，加载参数改变产生新 key，成功和异常路径都可卸载。

- [ ] **Step 5: 实现生成和卸载**

生成受 `ModelCache.generation_lock(key)` 保护；卸载从缓存移除，删除引用、`gc.collect()`，CUDA 可用时 `torch.cuda.empty_cache()`。

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_transformers_backend.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

Run: `git add skill_prompt/backends/transformers_backend.py tests/test_transformers_backend.py`

Run: `git -c user.name="coolchen778-png" -c user.email="coolchen778@gmail.com" commit -m "feat: add Transformers vision backend"`

### Task 7: GGUF/llama.cpp 后端

**Files:**
- Create: `skill_prompt/backends/gguf.py`
- Test: `tests/test_gguf_backend.py`

**Interfaces:**
- Consumes: `BackendAdapter`, `ModelCache`, `PromptRequest`, `build_openai_messages`, `extract_assistant_text`。
- Produces: `GGUFBackend(runtime_loader: Callable | None = None)` implementing `BackendAdapter`。
- Produces: `discover_handlers(runtime: Any) -> dict[str, type]` and `select_handler(name: str, handlers: Mapping[str, type], model_path: Path, mmproj_path: Path | None) -> Any | None`。

- [ ] **Step 1: 写能力发现和验证失败测试**

用伪 `llama_cpp` 覆盖 MTMD、Qwen25VL、Qwen3VL handler 的存在/缺失组合；断言 `auto` 优先通用 MTMD，其次与模型名匹配的 Qwen handler；显式 handler 不存在、模型路径缺失、图片存在但无可用视觉 handler 时给出发现列表。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_gguf_backend.py -q`

Expected: FAIL，原因是 GGUF 后端尚不存在。

- [ ] **Step 3: 实现延迟导入、handler 构造和模型加载**

handler 构造通过 `inspect.signature` 只传运行时接受的 `clip_model_path`、`mmproj_path` 或 `model_path`；`Llama` 接收规范中的 n_ctx、n_gpu_layers、n_threads、n_batch、flash_attn 和 chat_handler。

- [ ] **Step 4: 写生成、缓存和卸载失败测试**

断言图片作为 PNG data URI 进入 OpenAI 风格消息；`create_chat_completion` 获得 max_tokens、temperature、seed；文本粗估 token 加 `max_tokens` 明显超过 `n_ctx` 时不调用模型生成；响应解析共享 Task 1；缓存键包含模型、投影和全部加载参数；关闭方法存在时调用，成功/异常后均可卸载。

- [ ] **Step 5: 实现生成和卸载**

生成调用在相同 key 的锁内；`unload` 优先调用实例 `close()`，再执行垃圾回收和可用的 CUDA 空缓存。

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_gguf_backend.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

Run: `git add skill_prompt/backends/gguf.py tests/test_gguf_backend.py`

Run: `git -c user.name="coolchen778-png" -c user.email="coolchen778@gmail.com" commit -m "feat: add GGUF vision backend"`

### Task 8: ComfyUI 节点编排与注册

**Files:**
- Create: `skill_prompt/node.py`
- Modify: `nodes.py`
- Modify: `__init__.py`
- Test: `tests/test_node.py`
- Test: `tests/test_resolution.py`

**Interfaces:**
- Consumes: Tasks 1–7 的管理器、图片函数、注册表和适配器。
- Produces: `QwenMultiSkillPromptGenerator.INPUT_TYPES()` and `generate(task: str, skills: str, backend: str, ..., image_1=None, image_2=None, image_3=None, image_4=None, image_5=None, **kwargs) -> tuple[str, str, str]`。
- Produces: `create_default_skill_manager() -> SkillManager`，用户根固定为 `folder_paths.get_user_directory()/qwen_skill_prompt/skills`。
- Produces: `NODE_CLASS_MAPPINGS["QwenMultiSkillPromptGenerator"]` and display name `Qwen 多 Skill 提示词生成器`。

- [ ] **Step 1: 写 INPUT_TYPES 与注册失败测试**

断言 required widgets 包含 task、skills JSON、backend 和三后端参数，optional 仅含 `image_1`–`image_5`；返回类型/名称严格为三个 STRING；现有分辨率节点映射仍存在。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_node.py::test_node_contract tests/test_resolution.py -q`

Expected: 新节点断言 FAIL，现有分辨率回归 PASS。

- [ ] **Step 3: 实现节点契约和默认后端注册**

所有后端专属 widget 使用安全默认值；`skills` 是保存 JSON 数组的隐藏/多行 STRING；后端参数先组成普通 dict，再交适配器验证。

- [ ] **Step 4: 写执行编排失败测试**

注入伪 SkillManager/BackendRegistry，覆盖空任务、空/损坏 JSON、重复 Skill ID、1–5 图顺序、第六图通过直接调用注入、batch 大于 1、后端选择、`strip_thinking` 开关、`unload_after_generate` 成功与失败 finally 路径，以及三个输出。

- [ ] **Step 5: 实现 `generate` 最小编排**

先完成全部输入和 Skill 验证，再加载后端；`combined_skills` 同时进入 system prompt 和第三输出；若后端失败，不伪造输出，仅确保请求的卸载执行。

- [ ] **Step 6: 运行节点与回归测试**

Run: `python -m pytest tests/test_node.py tests/test_resolution.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

Run: `git add skill_prompt/node.py nodes.py __init__.py tests/test_node.py tests/test_resolution.py`

Run: `git -c user.name="coolchen778-png" -c user.email="coolchen778@gmail.com" commit -m "feat: add multi-skill ComfyUI node"`

### Task 9: Skill HTTP 路由与前端控件

**Files:**
- Create: `routes.py`
- Create: `web/js/qwen_skill_prompt.js`
- Modify: `__init__.py`
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: `create_default_skill_manager()` and `SkillManager.save_upload/list_skills`。
- Produces: GET `/qwen_skill_prompt/skills` returning `{skills: [{id, source, relative_path}]}`。
- Produces: POST `/qwen_skill_prompt/upload` multipart field `file`, returning the created Skill entry with HTTP 201。
- Produces: `WEB_DIRECTORY = "./web"`。

- [ ] **Step 1: 写路由失败测试**

使用伪 PromptServer/请求对象断言列表 schema、合法上传 201、非法扩展名/重名/缺 file 为 400、内部错误为不泄密的 500；重复调用 `register_routes()` 不重复注册。

- [ ] **Step 2: 运行路由测试确认失败**

Run: `python -m pytest tests/test_routes.py -q`

Expected: FAIL，原因是路由尚不存在。

- [ ] **Step 3: 实现惰性路由注册**

只有能导入 ComfyUI `PromptServer` 时注册；测试和脱离 ComfyUI 导入时保持无副作用。上传读取设置 1 MiB Skill 文件上限，超限返回 413。

- [ ] **Step 4: 实现前端扩展**

为目标节点替换 `skills` 文本框为搜索列表、已选项拖动排序、删除、刷新和上传控件；每次变化把有序 ID 数组序列化回原 widget。根据 backend 显隐 GGUF/Transformers/API widget，隐藏不删除值。

- [ ] **Step 5: 验证 JS 语法**

Run: `node --check web/js/qwen_skill_prompt.js`

Expected: 退出码 0。

- [ ] **Step 6: 验证路由与节点回归**

Run: `python -m pytest tests/test_routes.py tests/test_node.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

Run: `git add routes.py web/js/qwen_skill_prompt.js __init__.py tests/test_routes.py`

Run: `git -c user.name="coolchen778-png" -c user.email="coolchen778@gmail.com" commit -m "feat: add skill picker web extension"`

### Task 10: 文档、完整验证与交付检查

**Files:**
- Modify: `README.md`
- Create: `skills/.gitkeep`
- Modify: `.gitignore` only if test/runtime artifacts reveal a missing ignore rule
- Test: all existing tests

**Interfaces:**
- Consumes: 完整节点行为。
- Produces: 安装、三后端配置、Skill 目录、环境变量、五图用法、卸载语义和故障排查文档。

- [ ] **Step 1: 写 README 验收清单**

加入：节点截图位置占位说明之外的真实字段表；GGUF/Transformers 可选安装且不提供强制 CUDA 命令；`OPENAI_API_KEY` 与自定义环境变量示例；NewAPI base URL 示例；Skill 上传/目录说明；0–5 图和 batch=1 限制；三输出说明；常见 handler/processor 缺失错误。

- [ ] **Step 2: 运行完整 pytest 验证**

Run: `python -m pytest -q`

Expected: 全部 PASS。

- [ ] **Step 3: 运行 Python 编译检查**

Run: `python -m compileall -q .`

Expected: 退出码 0。

- [ ] **Step 4: 运行前端语法检查**

Run: `node --check web/js/qwen_skill_prompt.js`

Expected: 退出码 0。

- [ ] **Step 5: 做无可选依赖导入检查**

在隔离 Python 进程中阻止 `llama_cpp`/`transformers` 导入，再导入包并断言两个节点均注册；随后调用对应后端并断言只在执行时返回带安装方向的 `模型加载` 错误。

- [ ] **Step 6: 检查空白错误**

Run: `git diff --check`

Expected: 退出码 0。

- [ ] **Step 7: 检查工作树状态**

Run: `git status --short`

Expected: 只剩用户明确保留的无关改动或本任务待提交文件。

- [ ] **Step 8: 提交文档与最终修正**

Run: `git add README.md skills tests skill_prompt routes.py web nodes.py __init__.py`

Run: `git -c user.name="coolchen778-png" -c user.email="coolchen778@gmail.com" commit -m "docs: document multi-skill prompt generator"`

- [ ] **Step 9: 记录真实环境烟雾测试待办**

交付说明明确列出尚需用户在 ComfyUI 中验证的项目：Skill 多选/排序/上传、五图顺序、至少一个本地后端、一个 NewAPI 端点、字段显隐、工作流重载和卸载显存。没有实际模型/API 时不得声称这些烟雾测试已通过。
