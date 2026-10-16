import asyncio
import json
from types import SimpleNamespace

from skill_prompt.errors import SkillPromptError
from skill_prompt.skills import SkillEntry


class FakeManager:
    def __init__(self):
        self.saved = []
        self.deleted = []
        self.list_error = None
        self.save_error = None
        self.delete_error = None

    def list_skills(self):
        if self.list_error:
            raise self.list_error
        return [
            SkillEntry("builtin:a.md", "builtin", "a.md"),
            SkillEntry("user:nested/b.txt", "user", "nested/b.txt"),
        ]

    def save_upload(self, filename, content, overwrite=False):
        if self.save_error:
            raise self.save_error
        self.saved.append((filename, content, overwrite))
        return SkillEntry(f"user:{filename}", "user", filename)

    def delete_skill(self, skill_id):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append(skill_id)


class FakeField:
    def __init__(self, name="file", filename="new.md", chunks=(b"hello",)):
        self.name = name
        self.filename = filename
        self.chunks = list(chunks)

    async def read_chunk(self):
        return self.chunks.pop(0) if self.chunks else b""


class FakeReader:
    def __init__(self, fields):
        self.fields = list(fields)

    async def next(self):
        return self.fields.pop(0) if self.fields else None


class FakeRequest:
    def __init__(self, fields=(), json_data=None, query=None):
        self.fields = fields
        self.json_data = json_data or {}
        self.query = query or {}

    async def multipart(self):
        return FakeReader(self.fields)

    async def json(self):
        return self.json_data


def body(response):
    return json.loads(response.text)


def test_list_route_schema(monkeypatch):
    import routes

    manager = FakeManager()
    monkeypatch.setattr(routes, "create_default_skill_manager", lambda: manager)
    response = asyncio.run(routes.list_skills_handler(FakeRequest()))
    assert response.status == 200
    assert body(response) == {
        "skills": [
            {"id": "builtin:a.md", "source": "builtin", "relative_path": "a.md"},
            {
                "id": "user:nested/b.txt",
                "source": "user",
                "relative_path": "nested/b.txt",
            },
        ]
    }


def test_upload_route_returns_201(monkeypatch):
    import routes

    manager = FakeManager()
    monkeypatch.setattr(routes, "create_default_skill_manager", lambda: manager)
    response = asyncio.run(
        routes.upload_skill_handler(FakeRequest([FakeField(chunks=[b"abc", b"def"])]))
    )
    assert response.status == 201
    assert body(response) == {
        "id": "user:new.md",
        "source": "user",
        "relative_path": "new.md",
    }
    assert manager.saved == [("new.md", b"abcdef", False)]


def test_upload_with_overwrite(monkeypatch):
    import routes

    manager = FakeManager()
    monkeypatch.setattr(routes, "create_default_skill_manager", lambda: manager)
    field = FakeField(name="file", filename="custom.md", chunks=[b"data"])
    request = FakeRequest(fields=[field], query={"overwrite": "true"})
    response = asyncio.run(routes.upload_skill_handler(request))
    assert response.status == 201
    assert manager.saved == [("custom.md", b"data", True)]


def test_upload_missing_file_is_400(monkeypatch):
    import routes

    monkeypatch.setattr(routes, "create_default_skill_manager", FakeManager)
    response = asyncio.run(routes.upload_skill_handler(FakeRequest([])))
    assert response.status == 400


def test_upload_skill_validation_errors_are_400(monkeypatch):
    import routes

    manager = FakeManager()
    manager.save_error = SkillPromptError("Skill 读取", "bad extension")
    monkeypatch.setattr(routes, "create_default_skill_manager", lambda: manager)
    response = asyncio.run(
        routes.upload_skill_handler(FakeRequest([FakeField(filename="bad.exe")]))
    )
    assert response.status == 400
    assert "bad extension" in body(response)["error"]


def test_upload_larger_than_one_mib_is_413(monkeypatch):
    import routes

    monkeypatch.setattr(routes, "create_default_skill_manager", FakeManager)
    field = FakeField(chunks=[b"x" * (1024 * 1024), b"y"])
    response = asyncio.run(routes.upload_skill_handler(FakeRequest([field])))
    assert response.status == 413


def test_internal_error_is_generic_and_does_not_leak_details(monkeypatch):
    import routes

    manager = FakeManager()
    manager.list_error = RuntimeError("secret path and key")
    monkeypatch.setattr(routes, "create_default_skill_manager", lambda: manager)
    response = asyncio.run(routes.list_skills_handler(FakeRequest()))
    assert response.status == 500
    assert "secret" not in response.text


class FakeRoutes:
    def __init__(self):
        self.calls = []

    def get(self, path):
        return self._decorator("GET", path)

    def post(self, path):
        return self._decorator("POST", path)

    def delete(self, path):
        return self._decorator("DELETE", path)

    def _decorator(self, method, path):
        def register(handler):
            self.calls.append((method, path, handler))
            return handler

        return register


def test_route_registration_is_idempotent_for_same_server():
    import routes

    fake_routes = FakeRoutes()
    server = SimpleNamespace(instance=SimpleNamespace(routes=fake_routes))
    routes.register_routes(server)
    routes.register_routes(server)
    assert [(method, path) for method, path, _ in fake_routes.calls] == [
        ("GET", "/qwen_skill_prompt/skills"),
        ("POST", "/qwen_skill_prompt/upload"),
        ("POST", "/qwen_skill_prompt/delete"),
        ("DELETE", "/qwen_skill_prompt/skills"),
    ]


def test_delete_route_success(monkeypatch):
    import routes

    manager = FakeManager()
    monkeypatch.setattr(routes, "create_default_skill_manager", lambda: manager)
    request = FakeRequest(json_data={"id": "user:custom.md"})
    response = asyncio.run(routes.delete_skill_handler(request))
    assert response.status == 200
    assert body(response) == {"success": True, "id": "user:custom.md"}
    assert manager.deleted == ["user:custom.md"]


def test_delete_route_missing_id(monkeypatch):
    import routes

    manager = FakeManager()
    monkeypatch.setattr(routes, "create_default_skill_manager", lambda: manager)
    request = FakeRequest(json_data={})
    response = asyncio.run(routes.delete_skill_handler(request))
    assert response.status == 400
    assert "缺少 skill id" in body(response)["error"]


def test_delete_route_skill_prompt_error(monkeypatch):
    import routes

    manager = FakeManager()
    manager.delete_error = SkillPromptError("Skill 删除", "只能删除用户上传的 Skill")
    monkeypatch.setattr(routes, "create_default_skill_manager", lambda: manager)
    request = FakeRequest(json_data={"id": "builtin:a.md"})
    response = asyncio.run(routes.delete_skill_handler(request))
    assert response.status == 400
    assert "只能删除用户上传的 Skill" in body(response)["error"]
