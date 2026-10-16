import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from .errors import SkillPromptError

SkillSource = Literal["builtin", "user"]
_ALLOWED_SUFFIXES = {".md", ".txt"}


@dataclass(frozen=True)
class SkillRoot:
    source: SkillSource
    path: Path


@dataclass(frozen=True)
class SkillEntry:
    id: str
    source: str
    relative_path: str


class SkillManager:
    def __init__(self, roots: Sequence[SkillRoot]):
        self._roots = {root.source: root.path for root in roots}

    def list_skills(self) -> list[SkillEntry]:
        entries: list[SkillEntry] = []
        for source, root in self._roots.items():
            if not root.exists():
                continue
            resolved_root = root.resolve()
            for candidate in root.rglob("*"):
                if candidate.suffix.lower() not in _ALLOWED_SUFFIXES:
                    continue
                resolved = candidate.resolve()
                if not resolved.is_file() or not resolved.is_relative_to(resolved_root):
                    continue
                relative = resolved.relative_to(resolved_root).as_posix()
                entries.append(SkillEntry(f"{source}:{relative}", source, relative))
        return sorted(entries, key=lambda entry: entry.id.casefold())

    def combine(self, skill_ids: Sequence[str]) -> str:
        sections: list[str] = []
        for index, skill_id in enumerate(skill_ids, start=1):
            source, relative, path = self._resolve_id(skill_id)
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise SkillPromptError("Skill 读取", f"无法读取 {source}:{relative}: {exc}") from exc
            if not content:
                warnings.warn(f"Skill 为空: {source}:{relative}", UserWarning, stacklevel=2)
            sections.append(
                f'<skill name="{relative}" index="{index}">\n{content}\n</skill>'
            )
        return "\n\n".join(sections)

    def _resolve_id(self, skill_id: str) -> tuple[str, str, Path]:
        if not isinstance(skill_id, str) or ":" not in skill_id:
            raise SkillPromptError("Skill 读取", f"无效 Skill 标识: {skill_id!r}")
        source, relative = skill_id.split(":", 1)
        root = self._roots.get(source)
        posix_path = PurePosixPath(relative)
        if root is None or not relative or posix_path.is_absolute() or ".." in posix_path.parts:
            raise SkillPromptError("Skill 读取", f"无效 Skill 标识: {skill_id!r}")
        if Path(relative).is_absolute() or Path(relative).suffix.lower() not in _ALLOWED_SUFFIXES:
            raise SkillPromptError("Skill 读取", f"无效 Skill 文件: {skill_id!r}")
        resolved_root = root.resolve()
        path = resolved_root.joinpath(*posix_path.parts).resolve()
        if not path.is_relative_to(resolved_root) or not path.is_file():
            raise SkillPromptError("Skill 读取", f"Skill 不存在或越界: {skill_id!r}")
        return source, posix_path.as_posix(), path

    def save_upload(self, filename: str, content: bytes) -> SkillEntry:
        user_root = self._roots.get("user")
        if user_root is None:
            raise SkillPromptError("Skill 读取", "未配置用户 Skill 目录")
        if (
            not isinstance(filename, str)
            or not filename
            or "/" in filename
            or "\\" in filename
            or Path(filename).name != filename
            or Path(filename).suffix.lower() not in _ALLOWED_SUFFIXES
        ):
            raise SkillPromptError("Skill 读取", f"无效上传文件名: {filename!r}")
        if not isinstance(content, bytes):
            raise SkillPromptError("Skill 读取", "上传内容必须是 bytes")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SkillPromptError("Skill 读取", f"Skill 必须使用 UTF-8: {filename}") from exc

        try:
            user_root.mkdir(parents=True, exist_ok=True)
            resolved_root = user_root.resolve()
            target = (resolved_root / filename).resolve()
            if not target.is_relative_to(resolved_root):
                raise SkillPromptError("Skill 读取", f"上传路径越界: {filename!r}")
            with target.open("xb") as handle:
                handle.write(content)
        except FileExistsError as exc:
            raise SkillPromptError("Skill 读取", f"Skill 已存在: {filename}") from exc
        except SkillPromptError:
            raise
        except OSError as exc:
            raise SkillPromptError("Skill 读取", f"无法保存 Skill {filename}: {exc}") from exc

        return SkillEntry(f"user:{filename}", "user", filename)

    def delete_skill(self, skill_id: str) -> None:
        source, relative, path = self._resolve_id(skill_id)
        if source != "user":
            raise SkillPromptError("Skill 删除", "只能删除用户上传的 Skill，内置 Skill 不可删除")
        try:
            if path.is_file():
                path.unlink()
        except OSError as exc:
            raise SkillPromptError("Skill 删除", f"无法删除 Skill {skill_id}: {exc}") from exc
