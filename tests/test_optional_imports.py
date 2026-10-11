import importlib.util
import sys
from pathlib import Path

import pytest

from skill_prompt.errors import SkillPromptError
from skill_prompt.types import PromptRequest


def test_plugin_import_does_not_require_optional_inference_packages(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    package_name = "qwen_multi_skill_test_plugin"
    spec = importlib.util.spec_from_file_location(
        package_name,
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module

    original_import = __import__

    def blocked_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"llama_cpp", "transformers"}:
            raise ImportError(f"blocked optional dependency: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    try:
        spec.loader.exec_module(module)
        assert "Qwen21ResolutionResize" in module.NODE_CLASS_MAPPINGS
        assert "QwenMultiSkillPromptGenerator" in module.NODE_CLASS_MAPPINGS
    finally:
        for name in list(sys.modules):
            if name == package_name or name.startswith(package_name + "."):
                sys.modules.pop(name, None)


def test_optional_dependencies_fail_only_when_the_backend_executes(tmp_path):
    from skill_prompt.backends.gguf import GGUFBackend
    from skill_prompt.backends.transformers_backend import TransformersBackend

    def missing():
        raise ImportError("optional package missing")

    model = tmp_path / "model.gguf"
    model.write_bytes(b"model")
    prompt = PromptRequest("SYSTEM", "TASK", (), 8, 0.2, 0)
    gguf = GGUFBackend(runtime_loader=missing)
    with pytest.raises(SkillPromptError, match="llama-cpp-python"):
        gguf.generate(
            prompt,
            {
                "model_path": str(model),
                "mmproj_path": "",
                "handler": "auto",
                "n_ctx": 128,
                "n_gpu_layers": 0,
                "n_threads": 1,
                "n_batch": 16,
                "flash_attn": False,
            },
        )

    transformers = TransformersBackend(runtime_loader=missing)
    with pytest.raises(SkillPromptError, match="transformers"):
        transformers.generate(
            prompt,
            {
                "model": "local/model",
                "device_map": "cpu",
                "dtype": "auto",
                "attention_implementation": "auto",
                "trust_remote_code": False,
                "local_files_only": True,
            },
        )
