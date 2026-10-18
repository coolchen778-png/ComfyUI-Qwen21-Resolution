import json
import math
import re
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .backends.base import BackendRegistry
from .backends.gguf import GGUFBackend
from .backends.openai_compatible import OpenAICompatibleBackend
from .backends.transformers_backend import TransformersBackend
from .errors import SkillPromptError
from .images import prepare_images
from .messages import estimate_text_tokens
from .models import (
    LocalModelCatalog,
    NO_LOCAL_MODEL,
    NO_MMPROJ,
    create_default_model_catalog,
)
from .response import strip_leading_think
from .skills import SkillManager, SkillRoot
from .types import PromptRequest


def create_default_skill_manager() -> SkillManager:
    builtin_root = Path(__file__).resolve().parents[1] / "skills"
    try:
        import folder_paths

        if hasattr(folder_paths, "get_user_directory"):
            user_base = Path(folder_paths.get_user_directory())
        else:
            user_base = Path(folder_paths.user_directory)
    except (ImportError, AttributeError):
        user_base = Path.home() / ".comfyui"
    return SkillManager(
        [
            SkillRoot("builtin", builtin_root),
            SkillRoot("user", user_base / "qwen_skill_prompt" / "skills"),
        ]
    )


def create_default_backend_registry() -> BackendRegistry:
    registry = BackendRegistry()
    registry.register("gguf", GGUFBackend())
    registry.register("transformers", TransformersBackend())
    registry.register("online_api", OpenAICompatibleBackend())
    return registry


class QwenMultiSkillPromptGenerator:
    def __init__(
        self,
        skill_manager: SkillManager | None = None,
        backend_registry: BackendRegistry | None = None,
        model_catalog_factory: Callable[[], LocalModelCatalog] | None = None,
    ):
        self.skill_manager = skill_manager or create_default_skill_manager()
        self.backend_registry = backend_registry or create_default_backend_registry()
        self.model_catalog_factory = model_catalog_factory or create_default_model_catalog

    @classmethod
    def INPUT_TYPES(cls):
        catalog = create_default_model_catalog()
        return {
            "required": {
                "task": (
                    "STRING",
                    {"default": "", "multiline": True, "placeholder": "描述要生成的图像提示词"},
                ),
                "skills": ("STRING", {"default": "[]", "multiline": True}),
                "backend": (
                    ["本地模型", "在线 API", "gguf", "transformers", "online_api"],
                ),
                "role_prompt": (
                    "STRING",
                    {
                        "default": "你是专业的图像生成提示词编写助手。请结合全部 Skill 和参考图，直接输出最终提示词。",
                        "multiline": True,
                    },
                ),
                "max_new_tokens": ("INT", {"default": 1024, "min": 1, "max": 32768}),
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 2.0, "step": 0.05}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0x7FFFFFFF}),
                "strip_thinking": ("BOOLEAN", {"default": True}),
                "unload_after_generate": ("BOOLEAN", {"default": False}),
                "gguf_model_path": ("STRING", {"default": ""}),
                "gguf_mmproj_path": ("STRING", {"default": ""}),
                "gguf_handler": (["auto", "mtmd", "qwen2.5-vl", "qwen3-vl"],),
                "gguf_n_ctx": ("INT", {"default": 32768, "min": 1, "max": 1048576}),
                "gguf_n_gpu_layers": ("INT", {"default": -1, "min": -1, "max": 1000}),
                "gguf_n_threads": ("INT", {"default": 8, "min": 1, "max": 512}),
                "gguf_n_batch": ("INT", {"default": 512, "min": 1, "max": 8192}),
                "gguf_flash_attn": ("BOOLEAN", {"default": False}),
                "transformers_model": ("STRING", {"default": ""}),
                "transformers_device_map": ("STRING", {"default": "auto"}),
                "transformers_dtype": (["auto", "float16", "bfloat16", "float32"],),
                "transformers_attention_implementation": (
                    ["auto", "eager", "sdpa", "flash_attention_2"],
                ),
                "transformers_trust_remote_code": ("BOOLEAN", {"default": False}),
                "transformers_local_files_only": ("BOOLEAN", {"default": True}),
                "api_base_url": ("STRING", {"default": "https://api.openai.com/v1"}),
                "api_model": ("STRING", {"default": ""}),
                "api_key_env": ("STRING", {"default": "OPENAI_API_KEY"}),
                "api_custom_headers": ("STRING", {"default": "{}", "multiline": True}),
                "api_timeout": ("FLOAT", {"default": 120.0, "min": 0.1, "max": 3600.0}),
                "api_max_image_side": ("INT", {"default": 2048, "min": 0, "max": 16384}),
                "local_model": (catalog.main_choices(), {"default": NO_LOCAL_MODEL}),
                "local_mmproj": (catalog.mmproj_choices(), {"default": NO_MMPROJ}),
            },
            "optional": {
                f"image_{index}": ("IMAGE",) for index in range(1, 6)
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("final_prompt", "raw_response", "combined_skills")
    OUTPUT_NODE = True
    FUNCTION = "generate"
    CATEGORY = "cbkk"

    def _resolve_skills_text(self, skills: Any) -> str:
        if not skills:
            return ""
        if isinstance(skills, str):
            val = skills.strip()
            if not val or val in ("[]", "{}"):
                return ""
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    if not parsed:
                        return ""
                    return self.skill_manager.combine([str(item) for item in parsed if str(item).strip()])
            except Exception:
                pass
            return val
        if isinstance(skills, (list, tuple)):
            clean_list = [str(item).strip() for item in skills if str(item).strip()]
            return self.skill_manager.combine(clean_list) if clean_list else ""
        return str(skills).strip()

    @staticmethod
    def _backend_config(backend: str, values: dict[str, Any]) -> dict[str, Any]:
        if backend == "gguf":
            return {
                "model_path": values["gguf_model_path"],
                "mmproj_path": values["gguf_mmproj_path"],
                "handler": values["gguf_handler"],
                "n_ctx": values["gguf_n_ctx"],
                "n_gpu_layers": values["gguf_n_gpu_layers"],
                "n_threads": values["gguf_n_threads"],
                "n_batch": values["gguf_n_batch"],
                "flash_attn": values["gguf_flash_attn"],
            }
        if backend == "transformers":
            return {
                "model": values["transformers_model"],
                "device_map": values["transformers_device_map"],
                "dtype": values["transformers_dtype"],
                "attention_implementation": values[
                    "transformers_attention_implementation"
                ],
                "trust_remote_code": values["transformers_trust_remote_code"],
                "local_files_only": values["transformers_local_files_only"],
            }
        if backend == "online_api":
            return {
                "base_url": values["api_base_url"],
                "model": values["api_model"],
                "api_key_env": values["api_key_env"],
                "custom_headers": values["api_custom_headers"],
                "timeout": values["api_timeout"],
                "api_max_image_side": values["api_max_image_side"],
            }
        raise SkillPromptError("模型加载", f"未知后端: {backend}")

    def _resolve_backend(
        self,
        backend: str,
        local_model: str,
        local_mmproj: str,
        values: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        if backend == "在线 API":
            return "online_api", self._backend_config("online_api", values)
        if backend == "本地模型":
            catalog = self.model_catalog_factory()
            entry = catalog.resolve_main(local_model)
            selected_values = dict(values)
            if entry.backend == "gguf":
                mmproj = catalog.resolve_mmproj(local_mmproj)
                selected_values["gguf_model_path"] = str(entry.path)
                selected_values["gguf_mmproj_path"] = str(mmproj) if mmproj else ""
            elif entry.backend == "transformers":
                selected_values["transformers_model"] = str(entry.path)
            else:
                raise SkillPromptError(
                    "模型选择", f"不支持的本地模型类型: {entry.backend}"
                )
            return entry.backend, self._backend_config(entry.backend, selected_values)
        if backend in {"gguf", "transformers", "online_api"}:
            return backend, self._backend_config(backend, values)
        raise SkillPromptError("模型选择", f"未知运行方式: {backend}")

    def generate(
        self,
        task,
        skills,
        backend,
        local_model=NO_LOCAL_MODEL,
        local_mmproj=NO_MMPROJ,
        role_prompt="",
        max_new_tokens=1024,
        temperature=0.2,
        seed=0,
        strip_thinking=True,
        unload_after_generate=False,
        gguf_model_path="",
        gguf_mmproj_path="",
        gguf_handler="auto",
        gguf_n_ctx=32768,
        gguf_n_gpu_layers=-1,
        gguf_n_threads=8,
        gguf_n_batch=512,
        gguf_flash_attn=False,
        transformers_model="",
        transformers_device_map="auto",
        transformers_dtype="auto",
        transformers_attention_implementation="auto",
        transformers_trust_remote_code=False,
        transformers_local_files_only=True,
        api_base_url="https://api.openai.com/v1",
        api_model="",
        api_key_env="OPENAI_API_KEY",
        api_custom_headers="{}",
        api_timeout=120.0,
        api_max_image_side=2048,
        image_1=None,
        image_2=None,
        image_3=None,
        image_4=None,
        image_5=None,
        **kwargs,
    ):
        unexpected_images = [
            name for name in kwargs if name.startswith("image_")
        ]
        if unexpected_images:
            raise SkillPromptError("图片转换", "最多支持 5 张参考图")
        combined_skills = self._resolve_skills_text(skills)
        images = prepare_images((image_1, image_2, image_3, image_4, image_5))

        clean_task = task.strip() if isinstance(task, str) else ""
        if not clean_task:
            if images:
                clean_task = "请根据参考图像，详细分析画面主体、光影与构图细节，输出用于图像生成的优质提示词。"
            else:
                clean_task = "请生成一段丰富细致、富有画面感的高质量图像生成提示词。"

        system_prompt = role_prompt.strip()
        if combined_skills:
            if system_prompt:
                system_prompt += "\n\n"
            system_prompt += "请严格参考并联合执行以下 Skill：\n\n" + combined_skills
        if strip_thinking:
            if system_prompt:
                system_prompt += "\n\n"
            system_prompt += "【输出规范】请直接输出用于生图的最终提示词正文（Prompt），严禁输出任何 <think> 思考过程或分析过程，直接给出提示词。"
        request = PromptRequest(
            system_prompt=system_prompt,
            task=clean_task,
            images=images,
            max_new_tokens=int(max_new_tokens),
            temperature=float(temperature),
            seed=int(seed),
        )
        values = locals()
        selected_backend, config = self._resolve_backend(
            backend, local_model, local_mmproj, values
        )
        if selected_backend == "gguf":
            estimated_tokens = (
                estimate_text_tokens(request.system_prompt, request.task)
                + len(request.images) * 1024
            )
            needed_ctx = estimated_tokens + request.max_new_tokens + 256
            current_n_ctx = int(config.get("n_ctx", 32768))
            if needed_ctx > current_n_ctx:
                expanded = 1 << math.ceil(math.log2(needed_ctx))
                config["n_ctx"] = max(current_n_ctx, min(expanded, 131072))
        adapter = self.backend_registry.get(selected_backend)
        try:
            adapter.validate(config, has_images=bool(images))
            raw_response = adapter.generate(request, config)
            final_prompt = (
                strip_leading_think(raw_response) if strip_thinking else raw_response
            )
            if not final_prompt and raw_response.strip():
                cleaned = re.sub(r"^\s*<think>", "", raw_response, flags=re.IGNORECASE).strip()
                cleaned = re.sub(r"</think>\s*$", "", cleaned, flags=re.IGNORECASE).strip()
                final_prompt = cleaned if cleaned else raw_response.strip()
            return {
                "ui": {"text": [final_prompt]},
                "result": (final_prompt, raw_response, combined_skills),
            }
        finally:
            if unload_after_generate:
                adapter.unload(config)


class QwenSkillLoader:
    """
    cbkk｜Skill 知识库加载器
    独立加载或编写 Skill 知识库规则，支持从下拉列表选择已有 Skill、手动补充自定义规则，并支持多节点串联输入。
    """

    @classmethod
    def INPUT_TYPES(cls):
        manager = create_default_skill_manager()
        skills = ["none (不使用/仅自定义)"]
        try:
            skills += [entry.id for entry in manager.list_skills()]
        except Exception:
            pass
        return {
            "required": {
                "skill_name": (skills, {"default": skills[0]}),
                "custom_skill_text": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "placeholder": "在此输入或粘贴自定义 Skill 规则（可选，将与选中的 Skill 合并）",
                    },
                ),
            },
            "optional": {
                "prev_skills": ("STRING", {"forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("skills",)
    FUNCTION = "load_skill"
    CATEGORY = "cbkk"

    def load_skill(self, skill_name: str, custom_skill_text: str = "", prev_skills: str = ""):
        parts = []
        if prev_skills and prev_skills.strip():
            parts.append(prev_skills.strip())

        if skill_name and skill_name != "none (不使用/仅自定义)":
            manager = create_default_skill_manager()
            try:
                skill_content = manager.combine([skill_name])
                if skill_content.strip():
                    parts.append(skill_content.strip())
            except Exception as e:
                parts.append(f'<skill name="{skill_name}">\n# 读取失败: {e}\n</skill>')

        if custom_skill_text and custom_skill_text.strip():
            parts.append(f'<skill name="custom_skill">\n{custom_skill_text.strip()}\n</skill>')

        return ("\n\n".join(parts),)


class QwenSkillPromptPreview:
    """
    cbkk｜Skill 提示词预览 / 文本中继
    接收并展示提示词文本，同时输出文本（中继），可直连下游节点（如 CLIPTextEncode 文本框或其它文本输入）。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True, "multiline": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "preview"
    OUTPUT_NODE = True
    CATEGORY = "cbkk"

    def preview(self, text):
        val = text if isinstance(text, str) else str(text)
        return {"ui": {"text": [val]}, "result": (val,)}


