import json
from pathlib import Path

import pytest
import torch

from skill_prompt.errors import SkillPromptError
from skill_prompt.models import LocalModelEntry, NO_LOCAL_MODEL, NO_MMPROJ
from skill_prompt.node import QwenMultiSkillPromptGenerator
from skill_prompt.types import PromptRequest


class FakeSkills:
    def __init__(self):
        self.calls = []

    def combine(self, ids):
        self.calls.append(ids)
        return "COMBINED SKILLS"


class FakeBackend:
    def __init__(self, response="<think>hidden</think>FINAL"):
        self.response = response
        self.validations = []
        self.requests = []
        self.unloads = []
        self.error = None

    def validate(self, config, has_images):
        self.validations.append((config, has_images))

    def cache_key(self, config):
        return "fake"

    def generate(self, request, config):
        self.requests.append((request, config))
        if self.error:
            raise self.error
        return self.response

    def unload(self, config):
        self.unloads.append(config)


class FakeRegistry:
    def __init__(self, backend):
        self.backend = backend
        self.names = []

    def get(self, name):
        self.names.append(name)
        return self.backend


class FakeCatalog:
    def __init__(self, main_entries=(), mmproj_entries=()):
        self.main = {entry.selection: entry for entry in main_entries}
        self.mmproj = {entry.selection: entry.path for entry in mmproj_entries}

    def main_choices(self):
        return [NO_LOCAL_MODEL, *self.main]

    def mmproj_choices(self):
        return [NO_MMPROJ, *self.mmproj]

    def resolve_main(self, selection):
        return self.main[selection]

    def resolve_mmproj(self, selection):
        return None if selection == NO_MMPROJ else self.mmproj[selection]


def make_node(response="<think>hidden</think>FINAL", catalog=None):
    skills = FakeSkills()
    backend = FakeBackend(response)
    registry = FakeRegistry(backend)
    factory = (lambda: catalog) if catalog is not None else None
    return (
        QwenMultiSkillPromptGenerator(skills, registry, factory),
        skills,
        backend,
        registry,
    )


def settings(**overrides):
    values = {
        "task": "draw a fox",
        "skills": json.dumps(["builtin:a.md", "user:b.md"]),
        "backend": "transformers",
        "role_prompt": "You write prompts.",
        "max_new_tokens": 256,
        "temperature": 0.3,
        "seed": 9,
        "strip_thinking": True,
        "unload_after_generate": False,
        "gguf_model_path": "model.gguf",
        "gguf_mmproj_path": "",
        "gguf_handler": "auto",
        "gguf_n_ctx": 4096,
        "gguf_n_gpu_layers": 0,
        "gguf_n_threads": 4,
        "gguf_n_batch": 128,
        "gguf_flash_attn": False,
        "transformers_model": "Qwen/model",
        "transformers_device_map": "auto",
        "transformers_dtype": "auto",
        "transformers_attention_implementation": "auto",
        "transformers_trust_remote_code": False,
        "transformers_local_files_only": True,
        "api_base_url": "https://example.com/v1",
        "api_model": "qwen-vl",
        "api_key_env": "OPENAI_API_KEY",
        "api_custom_headers": "{}",
        "api_timeout": 60.0,
        "api_max_image_side": 2048,
    }
    values.update(overrides)
    return values


def test_node_contract_and_registration():
    import nodes

    inputs = QwenMultiSkillPromptGenerator.INPUT_TYPES()
    assert {f"image_{index}" for index in range(1, 6)} == set(inputs["optional"])
    for field in (
        "task",
        "skills",
        "backend",
        "gguf_model_path",
        "transformers_model",
        "api_base_url",
    ):
        assert field in inputs["required"]
    assert QwenMultiSkillPromptGenerator.RETURN_TYPES == ("STRING", "STRING", "STRING")
    assert QwenMultiSkillPromptGenerator.RETURN_NAMES == (
        "final_prompt",
        "raw_response",
        "combined_skills",
    )
    assert QwenMultiSkillPromptGenerator.CATEGORY == "cbkk"
    assert QwenMultiSkillPromptGenerator.OUTPUT_NODE is True
    assert "Qwen21ResolutionResize" in nodes.NODE_CLASS_MAPPINGS
    assert "QwenSkillPromptPreview" in nodes.NODE_CLASS_MAPPINGS
    assert (
        nodes.NODE_CLASS_MAPPINGS["QwenMultiSkillPromptGenerator"]
        is QwenMultiSkillPromptGenerator
    )


def test_input_types_offer_two_chinese_modes_and_scanned_model_choices(monkeypatch):
    import skill_prompt.node as node_module

    catalog = FakeCatalog(
        [LocalModelEntry("GGUF｜qwen/model.gguf", "gguf", Path("model.gguf"))],
        [LocalModelEntry("mmproj｜qwen/mmproj.gguf", "gguf", Path("mmproj.gguf"))],
    )
    monkeypatch.setattr(node_module, "create_default_model_catalog", lambda: catalog)

    required = QwenMultiSkillPromptGenerator.INPUT_TYPES()["required"]

    assert required["backend"][0][:2] == ["本地模型", "在线 API"]
    assert {"gguf", "transformers", "online_api"}.issubset(required["backend"][0])
    assert required["local_model"][0] == [NO_LOCAL_MODEL, "GGUF｜qwen/model.gguf"]
    assert required["local_mmproj"][0] == [NO_MMPROJ, "mmproj｜qwen/mmproj.gguf"]


def test_new_model_selectors_are_appended_after_legacy_widgets(monkeypatch):
    import skill_prompt.node as node_module

    monkeypatch.setattr(
        node_module, "create_default_model_catalog", lambda: FakeCatalog()
    )

    names = list(QwenMultiSkillPromptGenerator.INPUT_TYPES()["required"])

    assert names[-2:] == ["local_model", "local_mmproj"]
    assert names.index("role_prompt") == 3
    assert names.index("api_max_image_side") == len(names) - 3


def test_local_mode_dispatches_gguf_with_separate_mmproj(tmp_path):
    model = (tmp_path / "model.gguf").resolve()
    mmproj = (tmp_path / "mmproj.gguf").resolve()
    catalog = FakeCatalog(
        [LocalModelEntry("GGUF｜model.gguf", "gguf", model)],
        [LocalModelEntry("mmproj｜mmproj.gguf", "gguf", mmproj)],
    )
    node, _, backend, registry = make_node("ok", catalog)

    node.generate(
        **settings(
            backend="本地模型",
            local_model="GGUF｜model.gguf",
            local_mmproj="mmproj｜mmproj.gguf",
        )
    )

    assert registry.names == ["gguf"]
    _, config = backend.requests[-1]
    assert config["model_path"] == str(model)
    assert config["mmproj_path"] == str(mmproj)


def test_local_mode_dispatches_transformers_and_ignores_mmproj(tmp_path):
    model = (tmp_path / "Qwen-VL").resolve()
    catalog = FakeCatalog(
        [LocalModelEntry("Transformers｜Qwen-VL", "transformers", model)]
    )
    node, _, backend, registry = make_node("ok", catalog)

    node.generate(
        **settings(
            backend="本地模型",
            local_model="Transformers｜Qwen-VL",
            local_mmproj=NO_MMPROJ,
        )
    )

    assert registry.names == ["transformers"]
    _, config = backend.requests[-1]
    assert config["model"] == str(model)


def test_chinese_online_api_mode_dispatches_openai_compatible_backend():
    node, _, backend, registry = make_node("ok")

    node.generate(**settings(backend="在线 API"))

    assert registry.names == ["online_api"]
    _, config = backend.requests[-1]
    assert config["base_url"] == "https://example.com/v1"


@pytest.mark.parametrize("empty_task", ["", "   ", None])
def test_empty_task_uses_default_prompt(empty_task):
    node, _, backend, registry = make_node()
    node.generate(**settings(task=empty_task))
    assert registry.names == ["transformers"]
    request, _ = backend.requests[-1]
    assert "提示词" in request.task


@pytest.mark.parametrize("empty_skills", ["", "{}", "[]"])
def test_empty_skills_handled_gracefully(empty_skills):
    node, _, backend, registry = make_node()
    result = node.generate(**settings(skills=empty_skills))
    assert registry.names == ["transformers"]
    assert result["result"][2] == ""


def test_orchestration_preserves_skill_and_image_order_and_three_outputs():
    node, skills, backend, registry = make_node()
    image_1 = torch.zeros((1, 1, 1, 3))
    image_3 = torch.ones((1, 1, 1, 3))

    result = node.generate(**settings(), image_1=image_1, image_3=image_3)

    assert result["result"] == ("FINAL", "<think>hidden</think>FINAL", "COMBINED SKILLS")
    assert result["ui"] == {"text": ["FINAL"]}
    assert skills.calls == [["builtin:a.md", "user:b.md"]]
    assert registry.names == ["transformers"]
    request, config = backend.requests[-1]
    assert isinstance(request, PromptRequest)
    assert request.task == "draw a fox"
    assert request.images[0].getpixel((0, 0)) == (0, 0, 0)
    assert request.images[1].getpixel((0, 0)) == (255, 255, 255)
    assert "You write prompts." in request.system_prompt
    assert "COMBINED SKILLS" in request.system_prompt
    assert config["model"] == "Qwen/model"


def test_backend_config_selection_for_gguf_and_online_api():
    node, _, backend, _ = make_node("ok")
    node.generate(**settings(backend="gguf"))
    _, gguf = backend.requests[-1]
    assert gguf["model_path"] == "model.gguf"
    assert gguf["n_ctx"] == 4096

    node.generate(**settings(backend="online_api"))
    _, api = backend.requests[-1]
    assert api["base_url"] == "https://example.com/v1"
    assert api["api_key_env"] == "OPENAI_API_KEY"


def test_gguf_auto_expands_n_ctx_when_needed():
    node, _, backend, _ = make_node("ok")
    huge_task = "x" * 6000
    node.generate(
        **settings(
            backend="gguf",
            task=huge_task,
            gguf_n_ctx=1024,
            max_new_tokens=512,
        )
    )
    _, gguf = backend.requests[-1]
    assert gguf["n_ctx"] >= 4096


def test_strip_thinking_can_be_disabled():
    node, _, _, _ = make_node()
    result = node.generate(**settings(strip_thinking=False))
    assert result["result"][0] == result["result"][1]
    assert result["ui"]["text"] == [result["result"][0]]


def test_sixth_image_is_rejected_even_when_injected_directly():
    node, _, _, registry = make_node()
    image = torch.zeros((1, 1, 1, 3))
    with pytest.raises(SkillPromptError, match="5"):
        node.generate(
            **settings(),
            image_1=image,
            image_2=image,
            image_3=image,
            image_4=image,
            image_5=image,
            image_6=image,
        )
    assert registry.names == []


def test_unload_runs_after_success_and_failure():
    node, _, backend, _ = make_node("ok")
    node.generate(**settings(unload_after_generate=True))
    assert len(backend.unloads) == 1

    backend.error = RuntimeError("generation failed")
    with pytest.raises(RuntimeError, match="generation failed"):
        node.generate(**settings(unload_after_generate=True))
    assert len(backend.unloads) == 2


def test_tensor_batch_greater_than_one_is_rejected_before_backend():
    node, _, backend, _ = make_node()
    with pytest.raises(SkillPromptError, match="batch=1"):
        node.generate(**settings(), image_1=torch.zeros((2, 1, 1, 3)))
    assert backend.requests == []


def test_prompt_preview_node_contract_and_execution():
    from skill_prompt.node import QwenSkillPromptPreview

    inputs = QwenSkillPromptPreview.INPUT_TYPES()
    assert "text" in inputs["required"]
    assert QwenSkillPromptPreview.RETURN_TYPES == ("STRING",)
    assert QwenSkillPromptPreview.RETURN_NAMES == ("text",)
    assert QwenSkillPromptPreview.OUTPUT_NODE is True

    preview_node = QwenSkillPromptPreview()
    res = preview_node.preview("sample prompt text")
    assert res == {
        "ui": {"text": ["sample prompt text"]},
        "result": ("sample prompt text",),
    }

