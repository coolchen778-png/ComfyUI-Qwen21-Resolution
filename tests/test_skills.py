from pathlib import Path

import pytest

from skill_prompt.errors import SkillPromptError
from skill_prompt.skills import SkillManager, SkillRoot


def _manager(tmp_path: Path) -> tuple[SkillManager, Path, Path]:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    return (
        SkillManager(
            [
                SkillRoot("builtin", builtin),
                SkillRoot("user", user),
            ]
        ),
        builtin,
        user,
    )


def test_list_skills_recurses_allowed_files_with_stable_ids(tmp_path):
    manager, builtin, user = _manager(tmp_path)
    nested = builtin / "path" / "to"
    nested.mkdir(parents=True)
    (nested / "a.md").write_text("BUILTIN", encoding="utf-8")
    (builtin / "ignored.json").write_text("{}", encoding="utf-8")
    (user / "b.txt").write_text("USER", encoding="utf-8")
    (user / "folder.md").mkdir()

    entries = manager.list_skills()

    assert [entry.id for entry in entries] == [
        "builtin:path/to/a.md",
        "user:b.txt",
    ]
    assert [(entry.source, entry.relative_path) for entry in entries] == [
        ("builtin", "path/to/a.md"),
        ("user", "b.txt"),
    ]


def test_combine_preserves_user_selection_order_and_boundaries(tmp_path):
    manager, builtin, user = _manager(tmp_path)
    (builtin / "a.md").write_text("FIRST", encoding="utf-8")
    (user / "b.txt").write_text("SECOND", encoding="utf-8")

    combined = manager.combine(["user:b.txt", "builtin:a.md"])

    assert combined == (
        '<skill name="b.txt" index="1">\n'
        "SECOND\n"
        "</skill>\n\n"
        '<skill name="a.md" index="2">\n'
        "FIRST\n"
        "</skill>"
    )


@pytest.mark.parametrize(
    "skill_id",
    [
        "missing-colon",
        "unknown:file.md",
        "builtin:../outside.md",
        "builtin:C:/outside.md",
        "builtin:folder",
        "builtin:file.json",
        "builtin:missing.md",
    ],
)
def test_combine_rejects_invalid_or_escaping_ids(tmp_path, skill_id):
    manager, builtin, _ = _manager(tmp_path)
    (builtin / "folder").mkdir()
    (builtin / "file.json").write_text("{}", encoding="utf-8")

    with pytest.raises(SkillPromptError) as error:
        manager.combine([skill_id])

    assert error.value.stage == "Skill 读取"


def test_combine_rejects_non_utf8_and_deleted_files(tmp_path):
    manager, builtin, _ = _manager(tmp_path)
    invalid = builtin / "invalid.md"
    invalid.write_bytes(b"\xff\xfe")

    with pytest.raises(SkillPromptError, match="invalid.md"):
        manager.combine(["builtin:invalid.md"])

    deleted = builtin / "deleted.md"
    deleted.write_text("temporary", encoding="utf-8")
    deleted.unlink()
    with pytest.raises(SkillPromptError, match="deleted.md"):
        manager.combine(["builtin:deleted.md"])


def test_combine_rejects_symlink_that_escapes_root(tmp_path):
    manager, builtin, _ = _manager(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    link = builtin / "linked.md"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    assert "builtin:linked.md" not in [entry.id for entry in manager.list_skills()]
    with pytest.raises(SkillPromptError):
        manager.combine(["builtin:linked.md"])


def test_combine_warns_but_preserves_empty_skill(tmp_path):
    manager, builtin, _ = _manager(tmp_path)
    (builtin / "empty.md").write_text("", encoding="utf-8")

    with pytest.warns(UserWarning, match="empty.md"):
        combined = manager.combine(["builtin:empty.md"])

    assert combined == '<skill name="empty.md" index="1">\n\n</skill>'


def test_save_upload_creates_user_root_and_returns_entry(tmp_path):
    user = tmp_path / "not-created-yet"
    manager = SkillManager([SkillRoot("user", user)])

    entry = manager.save_upload("new-skill.md", "规则".encode("utf-8"))

    assert entry.id == "user:new-skill.md"
    assert entry.source == "user"
    assert entry.relative_path == "new-skill.md"
    assert (user / "new-skill.md").read_text(encoding="utf-8") == "规则"


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("../escape.md", b"x"),
        ("folder/escape.md", b"x"),
        ("folder\\escape.md", b"x"),
        ("wrong.json", b"{}"),
        ("invalid.md", b"\xff"),
    ],
)
def test_save_upload_rejects_unsafe_name_extension_or_encoding(tmp_path, filename, content):
    manager, _, _ = _manager(tmp_path)

    with pytest.raises(SkillPromptError):
        manager.save_upload(filename, content)


def test_save_upload_refuses_to_overwrite_existing_file(tmp_path):
    manager, _, user = _manager(tmp_path)
    (user / "same.md").write_text("old", encoding="utf-8")

    with pytest.raises(SkillPromptError, match="已存在"):
        manager.save_upload("same.md", b"new")

    assert (user / "same.md").read_text(encoding="utf-8") == "old"


def test_save_upload_requires_user_root(tmp_path):
    manager = SkillManager([SkillRoot("builtin", tmp_path / "builtin")])

    with pytest.raises(SkillPromptError, match="用户 Skill 目录"):
        manager.save_upload("new.md", b"x")
