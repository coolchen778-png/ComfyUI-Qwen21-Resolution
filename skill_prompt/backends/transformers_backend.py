import gc
import re
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..errors import SkillPromptError
from ..types import PromptRequest
from .base import ModelCache

_DTYPES = {"auto", "float16", "bfloat16", "float32"}
_ATTENTION = {"auto", "eager", "sdpa", "flash_attention_2"}
_DEVICE = re.compile(r"^(auto|cpu|cuda(?::\d+)?)$")


@dataclass
class _ModelBundle:
    runtime: Any
    processor: Any
    model: Any


def _load_runtime() -> SimpleNamespace:
    import torch
    import transformers

    return SimpleNamespace(
        torch=torch,
        AutoProcessor=transformers.AutoProcessor,
        AutoModelForImageTextToText=getattr(
            transformers,
            "AutoModelForImageTextToText",
            None,
        ),
        Qwen3VLForConditionalGeneration=getattr(
            transformers,
            "Qwen3VLForConditionalGeneration",
            None,
        ),
        Qwen2_5_VLForConditionalGeneration=getattr(
            transformers,
            "Qwen2_5_VLForConditionalGeneration",
            None,
        ),
        Qwen2VLForConditionalGeneration=getattr(
            transformers,
            "Qwen2VLForConditionalGeneration",
            None,
        ),
    )


class TransformersBackend:
    def __init__(
        self,
        runtime_loader: Callable[[], Any] | None = None,
        cache: ModelCache | None = None,
    ):
        self._runtime_loader = runtime_loader or _load_runtime
        self._cache = cache or ModelCache()

    def validate(self, config: Mapping[str, Any], has_images: bool) -> None:
        model = config.get("model")
        if not isinstance(model, str) or not model.strip():
            raise SkillPromptError("模型加载", "Transformers 模型目录或标识不能为空")
        device_map = config.get("device_map", "auto")
        if not isinstance(device_map, str) or not _DEVICE.fullmatch(device_map):
            raise SkillPromptError("模型加载", f"无效 device map: {device_map!r}")
        if config.get("dtype", "auto") not in _DTYPES:
            raise SkillPromptError("模型加载", f"无效 dtype: {config.get('dtype')!r}")
        attention = config.get("attention_implementation", "auto")
        if attention not in _ATTENTION:
            raise SkillPromptError("模型加载", f"无效 attention implementation: {attention!r}")
        for name, default in (("trust_remote_code", False), ("local_files_only", True)):
            if not isinstance(config.get(name, default), bool):
                raise SkillPromptError("模型加载", f"{name} 必须是布尔值")

    def cache_key(self, config: Mapping[str, Any]) -> Hashable:
        model_name = str(config.get("model", "")).strip()
        model_path = Path(model_name).expanduser()
        normalized_model = str(model_path.resolve()) if model_path.exists() else model_name
        return (
            "transformers",
            normalized_model,
            config.get("device_map", "auto"),
            config.get("dtype", "auto"),
            config.get("attention_implementation", "auto"),
            config.get("trust_remote_code", False),
            config.get("local_files_only", True),
        )

    def _runtime(self) -> Any:
        try:
            return self._runtime_loader()
        except ImportError as exc:
            raise SkillPromptError(
                "模型加载",
                "Transformers 后端需要安装 transformers 和 accelerate，并与当前模型版本兼容",
            ) from exc

    @staticmethod
    def _model_class(runtime: Any, model_name: str) -> Any:
        auto_model = getattr(runtime, "AutoModelForImageTextToText", None)
        if auto_model is not None:
            return auto_model
        if "qwen" in model_name.casefold():
            for name in (
                "Qwen3VLForConditionalGeneration",
                "Qwen2_5_VLForConditionalGeneration",
                "Qwen2VLForConditionalGeneration",
            ):
                candidate = getattr(runtime, name, None)
                if candidate is not None:
                    return candidate
        raise SkillPromptError(
            "模型加载",
            "当前 Transformers 版本没有可用的视觉语言模型加载类，请升级 transformers",
        )

    def _load_bundle(self, config: Mapping[str, Any]) -> _ModelBundle:
        runtime = self._runtime()
        model_name = str(config["model"]).strip()
        safe_kwargs = {
            "local_files_only": config.get("local_files_only", True),
            "trust_remote_code": config.get("trust_remote_code", False),
        }
        try:
            processor = runtime.AutoProcessor.from_pretrained(model_name, **safe_kwargs)
            model_kwargs = {
                **safe_kwargs,
                "device_map": config.get("device_map", "auto"),
            }
            dtype = config.get("dtype", "auto")
            model_kwargs["dtype"] = (
                dtype if dtype == "auto" else getattr(runtime.torch, dtype)
            )
            attention = config.get("attention_implementation", "auto")
            if attention != "auto":
                model_kwargs["attn_implementation"] = attention
            model_class = self._model_class(runtime, model_name)
            model = model_class.from_pretrained(model_name, **model_kwargs)
            return _ModelBundle(runtime=runtime, processor=processor, model=model)
        except SkillPromptError:
            raise
        except Exception as exc:
            raise SkillPromptError("模型加载", f"无法加载模型 {model_name!r}: {exc}") from exc

    @staticmethod
    def _messages(request: PromptRequest) -> list[dict[str, Any]]:
        user_content = [
            {"type": "image", "image": image} for image in request.images
        ]
        user_content.append({"type": "text", "text": request.task})
        return [
            {
                "role": "system",
                "content": [{"type": "text", "text": request.system_prompt}],
            },
            {"role": "user", "content": user_content},
        ]

    def generate(self, request: PromptRequest, config: Mapping[str, Any]) -> str:
        self.validate(config, has_images=bool(request.images))
        key = self.cache_key(config)
        bundle = self._cache.get_or_load(key, lambda: self._load_bundle(config))
        if request.images and getattr(bundle.processor, "image_processor", None) is None:
            raise SkillPromptError("模型加载", "所选处理器不支持视觉输入")

        with self._cache.generation_lock(key):
            try:
                inputs = bundle.processor.apply_chat_template(
                    self._messages(request),
                    tokenize=True,
                    add_generation_prompt=True,
                    return_dict=True,
                    return_tensors="pt",
                )
                if hasattr(inputs, "to"):
                    inputs = inputs.to(bundle.model.device)
                input_length = inputs["input_ids"].shape[-1]
                context_limit = getattr(
                    getattr(bundle.model, "config", None),
                    "max_position_embeddings",
                    None,
                )
                if (
                    isinstance(context_limit, int)
                    and input_length + request.max_new_tokens > context_limit
                ):
                    raise SkillPromptError(
                        "生成",
                        f"输入与输出预算超出模型上下文限制 {context_limit}",
                    )
                if hasattr(bundle.runtime.torch, "manual_seed"):
                    bundle.runtime.torch.manual_seed(request.seed)
                outputs = bundle.model.generate(
                    **inputs,
                    max_new_tokens=request.max_new_tokens,
                    temperature=request.temperature,
                    do_sample=request.temperature > 0,
                )
                new_tokens = outputs[:, input_length:]
                decoded = bundle.processor.batch_decode(
                    new_tokens,
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=False,
                )
                result = decoded[0].strip() if decoded else ""
                if not result:
                    raise SkillPromptError("生成", "模型返回了空内容")
                return result
            except SkillPromptError:
                raise
            except Exception as exc:
                raise SkillPromptError("生成", f"Transformers 推理失败: {exc}") from exc

    def unload(self, config: Mapping[str, Any]) -> None:
        key = self.cache_key(config)

        def close(bundle: _ModelBundle) -> None:
            try:
                if hasattr(bundle.model, "cpu"):
                    bundle.model.cpu()
                if hasattr(bundle.model, "close"):
                    bundle.model.close()
            finally:
                gc.collect()
                cuda = getattr(bundle.runtime.torch, "cuda", None)
                if cuda is not None and cuda.is_available():
                    cuda.empty_cache()

        self._cache.unload(key, close)
