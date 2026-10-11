import importlib
import sys
from types import SimpleNamespace

import pytest
import torch
from PIL import Image

from skill_prompt.errors import SkillPromptError
from skill_prompt.types import PromptRequest


class FakeBatch(dict):
    def __init__(self, input_ids):
        super().__init__(input_ids=input_ids)
        self.moved_to = None

    def to(self, device):
        self.moved_to = device
        return self


class FakeProcessor:
    loads = 0
    load_kwargs = None
    input_length = 3
    last_messages = None
    template_kwargs = None
    decoded_tokens = None
    image_processor = object()

    @classmethod
    def from_pretrained(cls, model, **kwargs):
        cls.loads += 1
        cls.load_kwargs = (model, kwargs)
        return cls()

    def apply_chat_template(self, messages, **kwargs):
        type(self).last_messages = messages
        type(self).template_kwargs = kwargs
        return FakeBatch(torch.arange(self.input_length).reshape(1, self.input_length))

    def batch_decode(self, tokens, **kwargs):
        type(self).decoded_tokens = tokens.tolist()
        return ["decoded prompt"]


class FakeModel:
    loads = 0
    load_kwargs = None
    instances = []
    raise_error = False

    def __init__(self):
        self.device = "cpu"
        self.config = SimpleNamespace(max_position_embeddings=64)
        self.generate_kwargs = None
        self.closed = False
        self.cpu_called = False
        type(self).instances.append(self)

    @classmethod
    def from_pretrained(cls, model, **kwargs):
        cls.loads += 1
        cls.load_kwargs = (model, kwargs)
        return cls()

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        if type(self).raise_error:
            raise RuntimeError("generation failed")
        suffix = torch.tensor([[90, 91]], dtype=kwargs["input_ids"].dtype)
        return torch.cat((kwargs["input_ids"], suffix), dim=1)

    def cpu(self):
        self.cpu_called = True
        return self

    def close(self):
        self.closed = True


def _runtime(processor=FakeProcessor, model=FakeModel, **overrides):
    values = {
        "torch": torch,
        "AutoProcessor": processor,
        "AutoModelForImageTextToText": model,
        "Qwen3VLForConditionalGeneration": None,
        "Qwen2_5_VLForConditionalGeneration": model,
        "Qwen2VLForConditionalGeneration": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def reset_fake_runtime():
    FakeProcessor.loads = 0
    FakeProcessor.load_kwargs = None
    FakeProcessor.input_length = 3
    FakeProcessor.last_messages = None
    FakeProcessor.template_kwargs = None
    FakeProcessor.decoded_tokens = None
    FakeProcessor.image_processor = object()
    FakeModel.loads = 0
    FakeModel.load_kwargs = None
    FakeModel.instances = []
    FakeModel.raise_error = False


def _config(**overrides):
    config = {
        "model": "Qwen/Qwen2.5-VL-3B-Instruct",
        "device_map": "auto",
        "dtype": "auto",
        "attention_implementation": "auto",
        "trust_remote_code": False,
        "local_files_only": True,
    }
    config.update(overrides)
    return config


def _request(images=(), max_new_tokens=8):
    return PromptRequest(
        system_prompt="SYSTEM",
        task="TASK",
        images=tuple(images),
        max_new_tokens=max_new_tokens,
        temperature=0.2,
        seed=3,
    )


def test_module_import_does_not_import_transformers():
    sys.modules.pop("transformers", None)

    module = importlib.import_module("skill_prompt.backends.transformers_backend")

    assert module is not None
    assert "transformers" not in sys.modules


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": ""},
        {"device_map": "magic"},
        {"dtype": "int8"},
        {"attention_implementation": "unknown"},
        {"trust_remote_code": "false"},
        {"local_files_only": "true"},
    ],
)
def test_validate_rejects_invalid_transformers_configuration(overrides):
    from skill_prompt.backends.transformers_backend import TransformersBackend

    backend = TransformersBackend(runtime_loader=lambda: None)

    with pytest.raises(SkillPromptError) as error:
        backend.validate(_config(**overrides), has_images=False)

    assert error.value.stage == "模型加载"


def test_missing_transformers_dependency_is_reported_at_execution_only():
    from skill_prompt.backends.transformers_backend import TransformersBackend

    def missing_runtime():
        raise ImportError("No module named transformers")

    backend = TransformersBackend(runtime_loader=missing_runtime)

    with pytest.raises(SkillPromptError) as error:
        backend.generate(_request(), _config())

    assert error.value.stage == "模型加载"
    assert "transformers" in str(error.value).lower()
    assert "accelerate" in str(error.value).lower()


def test_cache_key_changes_with_loading_configuration():
    from skill_prompt.backends.transformers_backend import TransformersBackend

    backend = TransformersBackend(runtime_loader=lambda: None)

    first = backend.cache_key(_config())
    assert first != backend.cache_key(_config(dtype="float16"))
    assert first != backend.cache_key(_config(device_map="cpu"))
    assert first != backend.cache_key(_config(trust_remote_code=True))


def test_generate_uses_safe_defaults_and_decodes_only_new_tokens():
    from skill_prompt.backends.transformers_backend import TransformersBackend

    backend = TransformersBackend(runtime_loader=_runtime)

    result = backend.generate(_request(), _config())

    assert result == "decoded prompt"
    assert FakeProcessor.load_kwargs == (
        "Qwen/Qwen2.5-VL-3B-Instruct",
        {"local_files_only": True, "trust_remote_code": False},
    )
    model_name, model_kwargs = FakeModel.load_kwargs
    assert model_name == "Qwen/Qwen2.5-VL-3B-Instruct"
    assert model_kwargs["local_files_only"] is True
    assert model_kwargs["trust_remote_code"] is False
    assert model_kwargs["device_map"] == "auto"
    assert model_kwargs["dtype"] == "auto"
    assert "attn_implementation" not in model_kwargs
    assert FakeProcessor.decoded_tokens == [[90, 91]]


def test_generate_builds_multimodal_processor_messages_in_image_order():
    from skill_prompt.backends.transformers_backend import TransformersBackend

    first = Image.new("RGB", (1, 1), "red")
    second = Image.new("RGB", (1, 1), "blue")
    backend = TransformersBackend(runtime_loader=_runtime)

    backend.generate(_request([first, second]), _config())

    messages = FakeProcessor.last_messages
    assert messages[0] == {
        "role": "system",
        "content": [{"type": "text", "text": "SYSTEM"}],
    }
    assert messages[1]["content"] == [
        {"type": "image", "image": first},
        {"type": "image", "image": second},
        {"type": "text", "text": "TASK"},
    ]
    assert FakeProcessor.template_kwargs == {
        "tokenize": True,
        "add_generation_prompt": True,
        "return_dict": True,
        "return_tensors": "pt",
    }


def test_generate_rejects_images_when_processor_is_not_visual():
    from skill_prompt.backends.transformers_backend import TransformersBackend

    class TextProcessor(FakeProcessor):
        image_processor = None

    backend = TransformersBackend(runtime_loader=lambda: _runtime(processor=TextProcessor))

    with pytest.raises(SkillPromptError, match="视觉"):
        backend.generate(_request([Image.new("RGB", (1, 1))]), _config())


def test_generate_uses_qwen_fallback_when_auto_model_is_unavailable():
    from skill_prompt.backends.transformers_backend import TransformersBackend

    backend = TransformersBackend(
        runtime_loader=lambda: _runtime(AutoModelForImageTextToText=None)
    )

    assert backend.generate(_request(), _config()) == "decoded prompt"
    assert FakeModel.loads == 1


def test_generate_maps_dtype_attention_and_sampling_parameters():
    from skill_prompt.backends.transformers_backend import TransformersBackend

    backend = TransformersBackend(runtime_loader=_runtime)
    request = PromptRequest("SYSTEM", "TASK", (), 9, 0.0, 123)

    backend.generate(
        request,
        _config(dtype="float16", attention_implementation="flash_attention_2"),
    )

    _, load_kwargs = FakeModel.load_kwargs
    assert load_kwargs["dtype"] is torch.float16
    assert load_kwargs["attn_implementation"] == "flash_attention_2"
    generated = FakeModel.instances[-1].generate_kwargs
    assert generated["max_new_tokens"] == 9
    assert generated["temperature"] == 0.0
    assert generated["do_sample"] is False


def test_generate_rejects_known_context_overflow_before_model_generate():
    from skill_prompt.backends.transformers_backend import TransformersBackend

    FakeProcessor.input_length = 60
    backend = TransformersBackend(runtime_loader=_runtime)

    with pytest.raises(SkillPromptError, match="上下文"):
        backend.generate(_request(max_new_tokens=8), _config())

    assert FakeModel.instances[-1].generate_kwargs is None


def test_same_loading_config_reuses_model_and_changed_config_loads_another():
    from skill_prompt.backends.transformers_backend import TransformersBackend

    backend = TransformersBackend(runtime_loader=_runtime)

    backend.generate(_request(), _config())
    backend.generate(_request(), _config())
    backend.generate(_request(), _config(dtype="float16"))

    assert FakeProcessor.loads == 2
    assert FakeModel.loads == 2


def test_unload_closes_cached_model_and_next_generate_reloads():
    from skill_prompt.backends.transformers_backend import TransformersBackend

    backend = TransformersBackend(runtime_loader=_runtime)
    backend.generate(_request(), _config())
    first = FakeModel.instances[-1]

    backend.unload(_config())
    backend.generate(_request(), _config())

    assert first.cpu_called is True
    assert first.closed is True
    assert FakeModel.loads == 2


def test_generation_failure_is_labeled_and_cached_model_can_be_unloaded():
    from skill_prompt.backends.transformers_backend import TransformersBackend

    backend = TransformersBackend(runtime_loader=_runtime)
    FakeModel.raise_error = True

    with pytest.raises(SkillPromptError) as error:
        backend.generate(_request(), _config())

    assert error.value.stage == "生成"
    failed = FakeModel.instances[-1]
    backend.unload(_config())
    FakeModel.raise_error = False
    backend.generate(_request(), _config())
    assert failed.closed is True
    assert FakeModel.loads == 2
