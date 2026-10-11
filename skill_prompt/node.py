import json
from pathlib import Path
from typing import Any

from .backends.base import BackendRegistry
from .backends.gguf import GGUFBackend
from .backends.openai_compatible import OpenAICompatibleBackend
from .backends.transformers_backend import TransformersBackend
from .errors import SkillPromptError
from .images import prepare_images
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
    ):
        self.skill_manager = skill_manager or create_default_skill_manager()
        self.backend_registry = backend_registry or create_default_backend_registry()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "task": (
                    "STRING",
                    {"default": "", "multiline": True, "placeholder": "描述要生成的图像提示词"},
                ),
                "skills": ("STRING", {"default": "[]", "multiline": True}),
                "backend": (["gguf", "transformers", "online_api"],),
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
                "gguf_n_ctx": ("INT", {"default": 16384, "min": 1, "max": 1048576}),
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
            },
            "optional": {
                f"image_{index}": ("IMAGE",) for index in range(1, 6)
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("final_prompt", "raw_response", "combined_skills")
    FUNCTION = "generate"
    CATEGORY = "Qwen/Prompt"

    @staticmethod
    def _parse_skill_ids(value: str) -> list[str]:
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise SkillPromptError("Skill 读取", "Skill 选择必须是 JSON 数组") from exc
        if not isinstance(parsed, list) or not parsed:
            raise SkillPromptError("Skill 读取", "至少选择一个 Skill")
        if not all(isinstance(item, str) and item for item in parsed):
            raise SkillPromptError("Skill 读取", "Skill ID 必须是非空字符串")
        if len(set(parsed)) != len(parsed):
            raise SkillPromptError("Skill 读取", "Skill 选择中不能有重复 ID")
        return parsed

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

    def generate(
        self,
        task,
        skills,
        backend,
        role_prompt="",
        max_new_tokens=1024,
        temperature=0.2,
        seed=0,
        strip_thinking=True,
        unload_after_generate=False,
        gguf_model_path="",
        gguf_mmproj_path="",
        gguf_handler="auto",
        gguf_n_ctx=16384,
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
        if not isinstance(task, str) or not task.strip():
            raise SkillPromptError("输入验证", "任务描述不能为空")
        unexpected_images = [
            name for name in kwargs if name.startswith("image_")
        ]
        if unexpected_images:
            raise SkillPromptError("图片转换", "最多支持 5 张参考图")
        skill_ids = self._parse_skill_ids(skills)
        combined_skills = self.skill_manager.combine(skill_ids)
        images = prepare_images((image_1, image_2, image_3, image_4, image_5))
        system_prompt = role_prompt.strip()
        if system_prompt:
            system_prompt += "\n\n"
        system_prompt += "请严格参考并联合执行以下 Skill：\n\n" + combined_skills
        request = PromptRequest(
            system_prompt=system_prompt,
            task=task.strip(),
            images=images,
            max_new_tokens=int(max_new_tokens),
            temperature=float(temperature),
            seed=int(seed),
        )
        values = locals()
        config = self._backend_config(backend, values)
        adapter = self.backend_registry.get(backend)
        try:
            adapter.validate(config, has_images=bool(images))
            raw_response = adapter.generate(request, config)
            final_prompt = (
                strip_leading_think(raw_response) if strip_thinking else raw_response
            )
            return final_prompt, raw_response, combined_skills
        finally:
            if unload_after_generate:
                adapter.unload(config)
