# Skill 提示词生成器简化与汉化设计

## 目标

保留一个 `cbkk | Skill 提示词生成器` 节点，将运行方式简化为“本地模型 / 在线 API”，让用户可直接选择 `ComfyUI/models/llm` 中的模型，并始终能看到 Skill 上传入口。

## 界面

- 运行方式仅显示“本地模型”和“在线 API”。
- 本地模式显示“主模型”和“视觉投影模型 (mmproj)”两个选择框。
- 主模型递归扫描 `.gguf` 文件和包含 `config.json` 的 Transformers 模型目录；`mmproj` 单独递归扫描。
- 选择 Transformers 目录时隐藏 mmproj；选择 GGUF 时显示 mmproj。
- API 模式只显示 OpenAI/NewAPI 兼容参数。
- 节点的可见标签、状态和错误文案使用简体中文。
- Skill 选择面板保留多选和拖拽排序，不设数量上限；上传、刷新按钮始终明显可见。
- 参考图保持最多 5 张。

## 兼容性

- 保留节点类型 ID `QwenMultiSkillPromptGenerator` 和三个输出。
- 后端继续接受旧值 `gguf`、`transformers` 和 `online_api`，旧字段保留为隐藏兼容参数。
- 新工作流通过主模型选项自动决定 GGUF 或 Transformers 后端。

## 错误处理

- 未选模型、选项已失效或路径越界时，在加载前返回明确中文错误。
- 不创建、移动或下载模型文件。
- 没有 DOM 面板能力时，仍保留原始 Skill 值和独立上传/刷新按钮。
