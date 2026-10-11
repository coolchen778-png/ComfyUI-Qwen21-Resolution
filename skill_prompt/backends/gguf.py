import gc
import inspect
from collections.abc import Callable, Hashable, Mapping
from pathlib import Path
from typing import Any

from ..errors import SkillPromptError
from ..images import image_to_data_uri
from ..messages import build_openai_messages, estimate_text_tokens
from ..response import extract_assistant_text
from ..types import PromptRequest
from .base import ModelCache

_HANDLER_ATTRIBUTES = {
    "mtmd": ("MTMDChatHandler", "LlamaMTMDChatHandler"),
    "qwen2.5-vl": ("Qwen25VLChatHandler",),
    "qwen3-vl": ("Qwen3VLChatHandler",),
}
_HANDLER_CHOICES = {"auto", *_HANDLER_ATTRIBUTES}


def _load_runtime() -> Any:
    import llama_cpp

    try:
        from llama_cpp import llama_chat_format
    except ImportError:
        llama_chat_format = None

    if llama_chat_format is not None:
        llama_cpp.llama_chat_format = llama_chat_format

    return llama_cpp


def discover_handlers(runtime: Any) -> dict[str, type]:
    sources = (runtime, getattr(runtime, "llama_chat_format", None))
    discovered: dict[str, type] = {}
    for name, attributes in _HANDLER_ATTRIBUTES.items():
        for source in sources:
            if source is None:
                continue
            for attribute in attributes:
                handler = getattr(source, attribute, None)
                if handler is not None:
                    discovered[name] = handler
                    break
            if name in discovered:
                break
    return discovered


def _construct_handler(
    handler_class: type,
    model_path: Path,
    mmproj_path: Path | None,
) -> Any:
    if mmproj_path is None:
        raise SkillPromptError("模型加载", "视觉 handler 需要 mmproj 投影文件")
    signature = inspect.signature(handler_class)
    kwargs: dict[str, str] = {}
    candidates = {
        "clip_model_path": str(mmproj_path),
        "mmproj_path": str(mmproj_path),
        "model_path": str(mmproj_path),
    }
    for name, value in candidates.items():
        if name in signature.parameters:
            kwargs[name] = value
    return handler_class(**kwargs)


def select_handler(
    name: str,
    handlers: Mapping[str, type],
    model_path: Path,
    mmproj_path: Path | None,
) -> Any | None:
    if mmproj_path is None:
        if name == "auto":
            return None
        raise SkillPromptError("模型加载", "显式视觉 handler 需要 mmproj 投影文件")
    if name != "auto":
        handler_class = handlers.get(name)
        if handler_class is None:
            discovered = ", ".join(sorted(handlers)) or "无"
            raise SkillPromptError(
                "模型加载",
                f"请求的 GGUF handler {name!r} 不可用；已发现: {discovered}",
            )
        return _construct_handler(handler_class, model_path, mmproj_path)

    selected: str | None = None
    if "mtmd" in handlers:
        selected = "mtmd"
    else:
        model_name = model_path.name.casefold().replace("_", "-")
        if "qwen3" in model_name and "qwen3-vl" in handlers:
            selected = "qwen3-vl"
        elif (
            "qwen2.5" in model_name or "qwen25" in model_name
        ) and "qwen2.5-vl" in handlers:
            selected = "qwen2.5-vl"
    if selected is None:
        return None
    return _construct_handler(handlers[selected], model_path, mmproj_path)


class GGUFBackend:
    def __init__(
        self,
        runtime_loader: Callable[[], Any] | None = None,
        cache: ModelCache | None = None,
    ):
        self._runtime_loader = runtime_loader or _load_runtime
        self._cache = cache or ModelCache()

    def validate(self, config: Mapping[str, Any], has_images: bool) -> None:
        model_value = config.get("model_path")
        if not isinstance(model_value, str) or not model_value.strip():
            raise SkillPromptError("模型加载", "GGUF 模型路径不能为空")
        model_path = Path(model_value).expanduser()
        if not model_path.is_file():
            raise SkillPromptError("模型加载", f"GGUF 模型文件不存在: {model_path}")

        mmproj_value = config.get("mmproj_path", "")
        if not isinstance(mmproj_value, str):
            raise SkillPromptError("模型加载", "mmproj_path 必须是字符串")
        if has_images and not mmproj_value.strip():
            raise SkillPromptError("模型加载", "图片输入需要 mmproj 视觉投影文件")
        if mmproj_value and not Path(mmproj_value).expanduser().is_file():
            raise SkillPromptError("模型加载", f"视觉投影文件不存在: {mmproj_value}")

        handler = config.get("handler", "auto")
        if handler not in _HANDLER_CHOICES:
            raise SkillPromptError("模型加载", f"无效 GGUF handler: {handler!r}")
        for name in ("n_ctx", "n_threads", "n_batch"):
            value = config.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise SkillPromptError("模型加载", f"{name} 必须是正整数")
        gpu_layers = config.get("n_gpu_layers")
        if not isinstance(gpu_layers, int) or isinstance(gpu_layers, bool):
            raise SkillPromptError("模型加载", "n_gpu_layers 必须是整数")
        if not isinstance(config.get("flash_attn", False), bool):
            raise SkillPromptError("模型加载", "flash_attn 必须是布尔值")

    @staticmethod
    def _paths(config: Mapping[str, Any]) -> tuple[Path, Path | None]:
        model = Path(str(config["model_path"])).expanduser().resolve()
        mmproj_value = str(config.get("mmproj_path", "")).strip()
        mmproj = Path(mmproj_value).expanduser().resolve() if mmproj_value else None
        return model, mmproj

    def cache_key(self, config: Mapping[str, Any]) -> Hashable:
        model, mmproj = self._paths(config)
        return (
            "gguf",
            str(model),
            str(mmproj) if mmproj else "",
            config.get("handler", "auto"),
            config.get("n_ctx"),
            config.get("n_gpu_layers"),
            config.get("n_threads"),
            config.get("n_batch"),
            config.get("flash_attn", False),
        )

    def _runtime(self) -> Any:
        try:
            return self._runtime_loader()
        except ImportError as exc:
            raise SkillPromptError(
                "模型加载",
                "GGUF 后端需要安装与当前环境匹配的 llama-cpp-python",
            ) from exc

    def _load_model(self, config: Mapping[str, Any]) -> Any:
        runtime = self._runtime()
        model_path, mmproj_path = self._paths(config)
        try:
            handler = select_handler(
                str(config.get("handler", "auto")),
                discover_handlers(runtime),
                model_path,
                mmproj_path,
            )
            model = runtime.Llama(
                model_path=str(model_path),
                n_ctx=config["n_ctx"],
                n_gpu_layers=config["n_gpu_layers"],
                n_threads=config["n_threads"],
                n_batch=config["n_batch"],
                flash_attn=config.get("flash_attn", False),
                chat_handler=handler,
            )
            return runtime, model, handler
        except SkillPromptError:
            raise
        except Exception as exc:
            raise SkillPromptError("模型加载", f"无法加载 GGUF 模型: {exc}") from exc

    def generate(self, request: PromptRequest, config: Mapping[str, Any]) -> str:
        self.validate(config, has_images=bool(request.images))
        key = self.cache_key(config)
        runtime, model, handler = self._cache.get_or_load(
            key, lambda: self._load_model(config)
        )
        if request.images and handler is None:
            available = ", ".join(sorted(discover_handlers(runtime))) or "无"
            raise SkillPromptError(
                "模型加载",
                f"图片输入需要可用视觉 handler；当前已发现: {available}",
            )
        estimated = estimate_text_tokens(request.system_prompt, request.task)
        if estimated + request.max_new_tokens > config["n_ctx"]:
            raise SkillPromptError(
                "生成",
                f"文本粗估与输出预算超出上下文限制 {config['n_ctx']}",
            )
        messages = build_openai_messages(
            request, lambda image: image_to_data_uri(image, max_side=0)
        )
        with self._cache.generation_lock(key):
            try:
                payload = model.create_chat_completion(
                    messages=messages,
                    max_tokens=request.max_new_tokens,
                    temperature=request.temperature,
                    seed=request.seed,
                )
                return extract_assistant_text(payload)
            except SkillPromptError:
                raise
            except Exception as exc:
                raise SkillPromptError("生成", f"GGUF 推理失败: {exc}") from exc

    def unload(self, config: Mapping[str, Any]) -> None:
        key = self.cache_key(config)

        def close(bundle: tuple[Any, Any, Any]) -> None:
            _, model, _ = bundle
            try:
                if hasattr(model, "close"):
                    model.close()
            finally:
                gc.collect()
                try:
                    import torch

                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass

        self._cache.unload(key, close)
