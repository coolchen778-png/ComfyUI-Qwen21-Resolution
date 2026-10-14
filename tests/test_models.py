from pathlib import Path

import pytest

from skill_prompt.errors import SkillPromptError
from skill_prompt.models import (
    NO_LOCAL_MODEL,
    NO_MMPROJ,
    LocalModelCatalog,
    get_llm_roots,
)


def test_discovery_separates_main_models_mmproj_and_transformers(tmp_path):
    root = tmp_path / "models" / "llm"
    gguf = root / "gguf" / "qwen-vl-q4.gguf"
    mmproj = root / "gguf" / "mmproj-qwen-vl-f16.gguf"
    transformer = root / "Qwen-VL"
    ignored = root / "notes.bin"
    gguf.parent.mkdir(parents=True)
    transformer.mkdir(parents=True)
    gguf.write_bytes(b"model")
    mmproj.write_bytes(b"projector")
    (transformer / "config.json").write_text("{}", encoding="utf-8")
    (transformer / "model.safetensors").write_bytes(b"weights")
    ignored.write_bytes(b"ignored")

    catalog = LocalModelCatalog.discover([root])

    assert catalog.main_choices() == [
        NO_LOCAL_MODEL,
        "GGUF｜gguf/qwen-vl-q4.gguf",
        "Transformers｜Qwen-VL",
    ]
    assert catalog.mmproj_choices() == [
        NO_MMPROJ,
        "mmproj｜gguf/mmproj-qwen-vl-f16.gguf",
    ]
    assert catalog.resolve_main("GGUF｜gguf/qwen-vl-q4.gguf").path == gguf.resolve()
    transformer_entry = catalog.resolve_main("Transformers｜Qwen-VL")
    assert transformer_entry.backend == "transformers"
    assert transformer_entry.path == transformer.resolve()
    assert catalog.resolve_mmproj("mmproj｜gguf/mmproj-qwen-vl-f16.gguf") == mmproj.resolve()
    assert catalog.resolve_mmproj(NO_MMPROJ) is None


def test_discovery_is_recursive_case_insensitive_and_deduplicates_roots(tmp_path):
    root = tmp_path / "llm"
    model = root / "nested" / "MODEL.GGUF"
    projector = root / "nested" / "MMPROJ-VISION.GGUF"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model")
    projector.write_bytes(b"projector")

    catalog = LocalModelCatalog.discover([root, root, root.resolve()])

    assert catalog.main_choices() == [NO_LOCAL_MODEL, "GGUF｜nested/MODEL.GGUF"]
    assert catalog.mmproj_choices() == [
        NO_MMPROJ,
        "mmproj｜nested/MMPROJ-VISION.GGUF",
    ]


def test_unknown_or_stale_selection_is_rejected(tmp_path):
    catalog = LocalModelCatalog.discover([tmp_path])

    with pytest.raises(SkillPromptError, match="重新扫描"):
        catalog.resolve_main("GGUF｜../../outside.gguf")
    with pytest.raises(SkillPromptError, match="重新扫描"):
        catalog.resolve_mmproj("mmproj｜missing.gguf")


def test_get_llm_roots_registers_models_llm_and_keeps_extra_roots(tmp_path):
    default = tmp_path / "models" / "llm"
    extra = tmp_path / "external-llm"

    class FakeFolderPaths:
        models_dir = str(tmp_path / "models")

        def __init__(self):
            self.added = []

        def add_model_folder_path(self, name, path):
            self.added.append((name, path))

        def get_folder_paths(self, name):
            assert name == "llm"
            return [str(extra), str(default)]

    fake = FakeFolderPaths()

    roots = get_llm_roots(fake)

    assert roots == [default.resolve(), extra.resolve()]
    assert fake.added == [("llm", str(default))]
