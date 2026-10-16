from dataclasses import asdict
from typing import Any

try:
    from .skill_prompt.errors import SkillPromptError
    from .skill_prompt.node import create_default_skill_manager
except ImportError:
    from skill_prompt.errors import SkillPromptError
    from skill_prompt.node import create_default_skill_manager


MAX_SKILL_BYTES = 1024 * 1024
_registered_server_ids: set[int] = set()


def _json_response(payload: dict[str, Any], status: int = 200):
    from aiohttp import web

    return web.json_response(payload, status=status)


async def list_skills_handler(request):
    try:
        entries = create_default_skill_manager().list_skills()
        return _json_response({"skills": [asdict(entry) for entry in entries]})
    except SkillPromptError as exc:
        return _json_response({"error": str(exc)}, status=400)
    except Exception:
        return _json_response({"error": "无法读取 Skill 列表"}, status=500)


async def upload_skill_handler(request):
    try:
        overwrite = False
        query = getattr(request, "query", {})
        if query and query.get("overwrite", "").lower() in ("true", "1", "yes"):
            overwrite = True

        reader = await request.multipart()
        file_field = None
        while True:
            field = await reader.next()
            if field is None:
                break
            name = getattr(field, "name", None)
            if name == "file":
                file_field = field
                break
            elif name == "overwrite":
                val = await field.read()
                if val.decode("utf-8").strip().lower() in ("true", "1", "yes"):
                    overwrite = True

        if file_field is None or not getattr(file_field, "filename", None):
            return _json_response({"error": "缺少 multipart file 字段"}, status=400)

        content = bytearray()
        while True:
            chunk = await file_field.read_chunk()
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > MAX_SKILL_BYTES:
                return _json_response(
                    {"error": "Skill 文件不能超过 1 MiB"}, status=413
                )
        entry = create_default_skill_manager().save_upload(
            file_field.filename, bytes(content), overwrite=overwrite
        )
        return _json_response(asdict(entry), status=201)
    except SkillPromptError as exc:
        return _json_response({"error": str(exc)}, status=400)
    except Exception:
        return _json_response({"error": "Skill 上传失败"}, status=500)


async def delete_skill_handler(request):
    try:
        data = await request.json()
        skill_id = data.get("id")
        if not skill_id or not isinstance(skill_id, str):
            return _json_response({"error": "缺少 skill id 参数"}, status=400)
        create_default_skill_manager().delete_skill(skill_id)
        return _json_response({"success": True, "id": skill_id})
    except SkillPromptError as exc:
        return _json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        return _json_response({"error": f"Skill 删除失败: {exc}"}, status=500)


def register_routes(prompt_server=None) -> bool:
    if prompt_server is None:
        try:
            from server import PromptServer
        except ImportError:
            return False
        prompt_server = PromptServer
    instance = getattr(prompt_server, "instance", None)
    route_table = getattr(instance, "routes", None)
    if instance is None or route_table is None:
        return False
    server_id = id(instance)
    if server_id in _registered_server_ids:
        return True
    route_table.get("/qwen_skill_prompt/skills")(list_skills_handler)
    route_table.post("/qwen_skill_prompt/upload")(upload_skill_handler)
    route_table.post("/qwen_skill_prompt/delete")(delete_skill_handler)
    route_table.delete("/qwen_skill_prompt/skills")(delete_skill_handler)
    _registered_server_ids.add(server_id)
    return True
