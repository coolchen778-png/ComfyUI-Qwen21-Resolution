import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from skill_prompt.errors import SkillPromptError
from skill_prompt.types import PromptRequest


class MTMD:
    def __init__(self, clip_model_path=None):
        self.path = clip_model_path


class Qwen25:
    def __init__(self, mmproj_path=None):
        self.path = mmproj_path


class Qwen3:
    def __init__(self, model_path=None):
        self.path = model_path


class FakeLlama:
    loads = 0
    kwargs = None
    instances = []
    response = {"choices": [{"message": {"content": "GGUF prompt"}}]}
    error = None

    def __init__(self, **kwargs):
        type(self).loads += 1
        type(self).kwargs = kwargs
        type(self).instances.append(self)
        self.calls = []
        self.closed = False

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        if type(self).error:
            raise type(self).error
        return type(self).response

    def close(self):
        self.closed = True


def runtime(**overrides):
    values = {
        "Llama": FakeLlama,
        "LlamaMTMDChatHandler": MTMD,
        "Qwen25VLChatHandler": Qwen25,
        "Qwen3VLChatHandler": Qwen3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def reset_fake():
    FakeLlama.loads = 0
    FakeLlama.kwargs = None
    FakeLlama.instances = []
    FakeLlama.response = {"choices": [{"message": {"content": "GGUF prompt"}}]}
    FakeLlama.error = None


@pytest.fixture
def model_files(tmp_path):
    model = tmp_path / "Qwen2.5-VL.gguf"
    mmproj = tmp_path / "mmproj.gguf"
    model.write_bytes(b"model")
    mmproj.write_bytes(b"projection")
    return model, mmproj


def config(model: Path, mmproj: Path | None, **overrides):
    result = {
        "model_path": str(model),
        "mmproj_path": str(mmproj) if mmproj else "",
        "handler": "auto",
        "n_ctx": 4096,
        "n_gpu_layers": 0,
        "n_threads": 4,
        "n_batch": 128,
        "flash_attn": False,
    }
    result.update(overrides)
    return result


def request(images=(), task="TASK", max_new_tokens=32):
    return PromptRequest("SYSTEM", task, tuple(images), max_new_tokens, 0.2, 7)


def test_module_import_does_not_import_llama_cpp():
    sys.modules.pop("llama_cpp", None)
    module = importlib.import_module("skill_prompt.backends.gguf")
    assert module is not None
    assert "llama_cpp" not in sys.modules


def test_discover_handlers_reports_only_available_classes():
    from skill_prompt.backends.gguf import discover_handlers

    found = discover_handlers(runtime(Qwen25VLChatHandler=None))
    assert found == {"mtmd": MTMD, "qwen3-vl": Qwen3}


def test_discover_handlers_supports_official_chat_format_module_and_mtmd_name():
    from skill_prompt.backends.gguf import discover_handlers

    official_runtime = SimpleNamespace(
        llama_chat_format=SimpleNamespace(
            MTMDChatHandler=MTMD,
            Qwen25VLChatHandler=Qwen25,
        )
    )
    assert discover_handlers(official_runtime) == {
        "mtmd": MTMD,
        "qwen2.5-vl": Qwen25,
    }


def test_select_handler_auto_prefers_mtmd_and_filters_constructor_arguments(model_files):
    from skill_prompt.backends.gguf import discover_handlers, select_handler

    model, mmproj = model_files
    selected = select_handler("auto", discover_handlers(runtime()), model, mmproj)
    assert isinstance(selected, MTMD)
    assert selected.path == str(mmproj)


def test_select_handler_auto_matches_qwen_model_when_mtmd_missing(model_files):
    from skill_prompt.backends.gguf import discover_handlers, select_handler

    model, mmproj = model_files
    handlers = discover_handlers(runtime(LlamaMTMDChatHandler=None))
    selected = select_handler("auto", handlers, model, mmproj)
    assert isinstance(selected, Qwen25)


def test_select_handler_auto_without_projection_keeps_text_only_mode(model_files):
    from skill_prompt.backends.gguf import discover_handlers, select_handler

    model, _ = model_files
    assert select_handler("auto", discover_handlers(runtime()), model, None) is None


def test_select_handler_explicit_requires_projection(model_files):
    from skill_prompt.backends.gguf import discover_handlers, select_handler

    model, _ = model_files
    with pytest.raises(SkillPromptError, match="投影"):
        select_handler("mtmd", discover_handlers(runtime()), model, None)


def test_select_handler_explicit_missing_is_labeled(model_files):
    from skill_prompt.backends.gguf import select_handler

    model, mmproj = model_files
    with pytest.raises(SkillPromptError, match="qwen3-vl"):
        select_handler("qwen3-vl", {}, model, mmproj)


@pytest.mark.parametrize(
    "overrides",
    [
        {"n_ctx": 0},
        {"n_gpu_layers": "0"},
        {"n_threads": 0},
        {"n_batch": 0},
        {"flash_attn": "false"},
        {"handler": "bad"},
    ],
)
def test_validate_rejects_invalid_configuration(model_files, overrides):
    from skill_prompt.backends.gguf import GGUFBackend

    model, mmproj = model_files
    backend = GGUFBackend(runtime_loader=runtime)
    with pytest.raises(SkillPromptError) as error:
        backend.validate(config(model, mmproj, **overrides), has_images=False)
    assert error.value.stage == "模型加载"


def test_validate_rejects_missing_model_path(tmp_path):
    from skill_prompt.backends.gguf import GGUFBackend

    backend = GGUFBackend(runtime_loader=runtime)
    with pytest.raises(SkillPromptError, match="不存在"):
        backend.validate(config(tmp_path / "missing.gguf", None), has_images=False)


def test_missing_dependency_is_reported_only_at_execution(model_files):
    from skill_prompt.backends.gguf import GGUFBackend

    model, _ = model_files

    def missing():
        raise ImportError("No module named llama_cpp")

    backend = GGUFBackend(runtime_loader=missing)
    with pytest.raises(SkillPromptError) as error:
        backend.generate(request(), config(model, None))
    assert error.value.stage == "模型加载"
    assert "llama-cpp-python" in str(error.value)


def test_images_require_available_visual_handler(model_files):
    from skill_prompt.backends.gguf import GGUFBackend

    model, mmproj = model_files
    backend = GGUFBackend(
        runtime_loader=lambda: runtime(
            LlamaMTMDChatHandler=None,
            Qwen25VLChatHandler=None,
            Qwen3VLChatHandler=None,
        )
    )
    with pytest.raises(SkillPromptError, match="可用.*handler"):
        backend.generate(request([Image.new("RGB", (1, 1))]), config(model, mmproj))


def test_images_require_projection_path(model_files):
    from skill_prompt.backends.gguf import GGUFBackend

    model, _ = model_files
    backend = GGUFBackend(runtime_loader=runtime)
    with pytest.raises(SkillPromptError, match="投影"):
        backend.generate(request([Image.new("RGB", (1, 1))]), config(model, None))
    assert FakeLlama.loads == 0


def test_generate_loads_model_and_sends_png_images(model_files):
    from skill_prompt.backends.gguf import GGUFBackend

    model, mmproj = model_files
    backend = GGUFBackend(runtime_loader=runtime)
    result = backend.generate(
        request([Image.new("RGB", (2, 2), "red")]),
        config(model, mmproj, flash_attn=True),
    )

    assert result == "GGUF prompt"
    assert FakeLlama.kwargs["model_path"] == str(model.resolve())
    assert FakeLlama.kwargs["n_ctx"] == 4096
    assert FakeLlama.kwargs["flash_attn"] is True
    assert isinstance(FakeLlama.kwargs["chat_handler"], MTMD)
    call = FakeLlama.instances[-1].calls[-1]
    assert call["max_tokens"] == 32
    assert call["temperature"] == 0.2
    assert call["seed"] == 7
    image_url = call["messages"][1]["content"][0]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")


def test_known_context_overflow_stops_before_generation(model_files):
    from skill_prompt.backends.gguf import GGUFBackend

    model, _ = model_files
    backend = GGUFBackend(runtime_loader=runtime)
    with pytest.raises(SkillPromptError, match="上下文"):
        backend.generate(
            request(task="x" * 100, max_new_tokens=16),
            config(model, None, n_ctx=20),
        )
    assert FakeLlama.instances[-1].calls == []


def test_cache_key_reuses_same_load_and_changes_for_loading_options(model_files):
    from skill_prompt.backends.gguf import GGUFBackend

    model, mmproj = model_files
    backend = GGUFBackend(runtime_loader=runtime)
    backend.generate(request(), config(model, mmproj))
    backend.generate(request(), config(model, mmproj))
    backend.generate(request(), config(model, mmproj, n_ctx=8192))
    assert FakeLlama.loads == 2


def test_unload_closes_model_and_failure_remains_unloadable(model_files):
    from skill_prompt.backends.gguf import GGUFBackend

    model, mmproj = model_files
    settings = config(model, mmproj)
    backend = GGUFBackend(runtime_loader=runtime)
    FakeLlama.error = RuntimeError("boom")
    with pytest.raises(SkillPromptError) as error:
        backend.generate(request(), settings)
    assert error.value.stage == "生成"
    first = FakeLlama.instances[-1]
    backend.unload(settings)
    assert first.closed is True
    FakeLlama.error = None
    backend.generate(request(), settings)
    assert FakeLlama.loads == 2
