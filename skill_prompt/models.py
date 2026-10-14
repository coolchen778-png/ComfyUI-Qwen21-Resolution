from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .errors import SkillPromptError


NO_LOCAL_MODEL = "请选择本地模型"
NO_MMPROJ = "不使用 mmproj"


@dataclass(frozen=True)
class LocalModelEntry:
    selection: str
    backend: str
    path: Path


class LocalModelCatalog:
    def __init__(
        self,
        main_entries: Iterable[LocalModelEntry] = (),
        mmproj_entries: Iterable[LocalModelEntry] = (),
    ):
        self._main = {entry.selection: entry for entry in main_entries}
        self._mmproj = {entry.selection: entry for entry in mmproj_entries}

    @classmethod
    def discover(cls, roots: Iterable[Path | str]) -> "LocalModelCatalog":
        unique_roots: list[Path] = []
        seen_roots: set[Path] = set()
        for value in roots:
            root = Path(value).expanduser().resolve()
            if root not in seen_roots:
                seen_roots.add(root)
                unique_roots.append(root)

        main_entries: list[LocalModelEntry] = []
        mmproj_entries: list[LocalModelEntry] = []
        seen_paths: set[Path] = set()
        used_labels: set[str] = set()

        def append_entry(
            target: list[LocalModelEntry],
            prefix: str,
            backend: str,
            path: Path,
            relative: Path,
        ) -> None:
            resolved = path.resolve()
            if resolved in seen_paths:
                return
            seen_paths.add(resolved)
            base = f"{prefix}｜{relative.as_posix()}"
            selection = base
            suffix = 2
            while selection in used_labels:
                selection = f"{base} （{suffix}）"
                suffix += 1
            used_labels.add(selection)
            target.append(LocalModelEntry(selection, backend, resolved))

        for root in unique_roots:
            if not root.is_dir():
                continue
            gguf_files = sorted(
                (path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() == ".gguf"),
                key=lambda path: path.relative_to(root).as_posix().casefold(),
            )
            for path in gguf_files:
                relative = path.relative_to(root)
                if "mmproj" in path.stem.casefold():
                    append_entry(mmproj_entries, "mmproj", "gguf", path, relative)
                else:
                    append_entry(main_entries, "GGUF", "gguf", path, relative)

            transformer_dirs = sorted(
                {path.parent for path in root.rglob("config.json") if path.is_file()},
                key=lambda path: path.relative_to(root).as_posix().casefold(),
            )
            for path in transformer_dirs:
                append_entry(
                    main_entries,
                    "Transformers",
                    "transformers",
                    path,
                    path.relative_to(root),
                )

        main_entries.sort(key=lambda entry: (entry.backend != "gguf", entry.selection.casefold()))
        mmproj_entries.sort(key=lambda entry: entry.selection.casefold())
        return cls(main_entries, mmproj_entries)

    def main_choices(self) -> list[str]:
        return [NO_LOCAL_MODEL, *self._main]

    def mmproj_choices(self) -> list[str]:
        return [NO_MMPROJ, *self._mmproj]

    def resolve_main(self, selection: str) -> LocalModelEntry:
        entry = self._main.get(selection)
        if entry is None:
            raise SkillPromptError(
                "模型选择",
                "本地模型未选择或已失效，请刷新节点并重新扫描。",
            )
        return entry

    def resolve_mmproj(self, selection: str) -> Path | None:
        if not selection or selection == NO_MMPROJ:
            return None
        entry = self._mmproj.get(selection)
        if entry is None:
            raise SkillPromptError(
                "模型选择",
                "mmproj 选项已失效，请刷新节点并重新扫描。",
            )
        return entry.path


def get_llm_roots(folder_paths_module: Any | None = None) -> list[Path]:
    if folder_paths_module is None:
        try:
            import folder_paths as folder_paths_module
        except ImportError:
            return []

    models_dir = getattr(folder_paths_module, "models_dir", None)
    default_root = Path(models_dir).expanduser() / "llm" if models_dir else None
    if default_root is not None and hasattr(folder_paths_module, "add_model_folder_path"):
        try:
            folder_paths_module.add_model_folder_path("llm", str(default_root))
        except (KeyError, TypeError, ValueError):
            pass

    candidates: list[Path] = []
    if default_root is not None:
        candidates.append(default_root)
    if hasattr(folder_paths_module, "get_folder_paths"):
        try:
            candidates.extend(Path(value) for value in folder_paths_module.get_folder_paths("llm"))
        except (KeyError, TypeError, ValueError):
            pass

    roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)
    return roots


def create_default_model_catalog() -> LocalModelCatalog:
    return LocalModelCatalog.discover(get_llm_roots())
