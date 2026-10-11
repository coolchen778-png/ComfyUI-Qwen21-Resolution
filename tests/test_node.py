import json

import pytest
import torch

from skill_prompt.errors import SkillPromptError
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


def make_node(response="<think>hidden</think>FINAL"):
    skills = FakeSkills()
    backend = FakeBackend(response)
    registry = FakeRegistry(backend)
    return QwenMultiSkillPromptGenerator(skills, registry), skills, backend, registry


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
    assert "Qwen21ResolutionResize" in nodes.NODE_CLASS_MAPPINGS
    assert (
        nodes.NODE_CLASS_MAPPINGS["QwenMultiSkillPromptGenerator"]
        is QwenMultiSkillPromptGenerator
    )


@pytest.mark.parametrize("bad_task", ["", "   ", None])
def test_empty_task_is_rejected_before_backend_lookup(bad_task):
    node, _, _, registry = make_node()
    with pytest.raises(SkillPromptError, match="任务"):
        node.generate(**settings(task=bad_task))
    assert registry.names == []


@pytest.mark.parametrize("bad_skills", ["", "{}", "[", "[]", '["a", "a"]', "[1]"])
def test_bad_skill_json_is_rejected_before_backend_lookup(bad_skills):
    node, _, _, registry = make_node()
    with pytest.raises(SkillPromptError, match="Skill"):
        node.generate(**settings(skills=bad_skills))
    assert registry.names == []


def test_orchestration_preserves_skill_and_image_order_and_three_outputs():
    node, skills, backend, registry = make_node()
    image_1 = torch.zeros((1, 1, 1, 3))
    image_3 = torch.ones((1, 1, 1, 3))

    result = node.generate(**settings(), image_1=image_1, image_3=image_3)

    assert result == ("FINAL", "<think>hidden</think>FINAL", "COMBINED SKILLS")
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


def test_strip_thinking_can_be_disabled():
    node, _, _, _ = make_node()
    result = node.generate(**settings(strip_thinking=False))
    assert result[0] == result[1]


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
