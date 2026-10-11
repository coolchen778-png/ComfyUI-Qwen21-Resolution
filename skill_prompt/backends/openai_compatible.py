import json
import os
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit

from ..errors import SkillPromptError, redact_secrets
from ..images import image_to_data_uri
from ..messages import build_openai_messages
from ..response import extract_assistant_text
from ..types import PromptRequest


def normalize_chat_completions_url(base_url: str) -> str:
    if not isinstance(base_url, str):
        raise SkillPromptError("请求发送", "Base URL 必须是字符串")
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
        raise SkillPromptError("请求发送", f"无效 Base URL: {base_url!r}")
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        endpoint = path
    elif path.endswith("/v1"):
        endpoint = f"{path}/chat/completions"
    else:
        endpoint = f"{path}/v1/chat/completions"
    return urlunsplit((parsed.scheme, parsed.netloc, endpoint, "", ""))


def _parse_headers(value: Any) -> dict[str, str]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise SkillPromptError("请求发送", "自定义 headers 必须是 JSON 对象") from exc
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in parsed.items()
    ):
        raise SkillPromptError("请求发送", "自定义 headers 必须是字符串键值 JSON 对象")
    credential_headers = {
        "authorization",
        "proxy-authorization",
        "api-key",
        "x-api-key",
    }
    if any(key.casefold() in credential_headers for key in parsed):
        raise SkillPromptError(
            "请求发送",
            "凭据 header 必须由 API 密钥环境变量生成",
        )
    return parsed


class OpenAICompatibleBackend:
    def __init__(self, opener: Callable = urllib.request.urlopen):
        self._opener = opener

    def validate(self, config: Mapping[str, Any], has_images: bool) -> None:
        normalize_chat_completions_url(config.get("base_url", ""))
        if not isinstance(config.get("model"), str) or not config["model"].strip():
            raise SkillPromptError("请求发送", "在线 API 模型名不能为空")
        env_name = config.get("api_key_env", "")
        if not isinstance(env_name, str) or not env_name.strip() or not os.environ.get(env_name):
            raise SkillPromptError("请求发送", f"API 密钥环境变量不存在: {env_name}")
        _parse_headers(config.get("custom_headers", "{}"))
        if not isinstance(config.get("timeout"), (int, float)) or config["timeout"] <= 0:
            raise SkillPromptError("请求发送", "请求超时必须大于 0")
        max_side = config.get("api_max_image_side")
        if not isinstance(max_side, int) or max_side < 0:
            raise SkillPromptError("请求发送", "在线图片最大边长必须是非负整数")

    def cache_key(self, config: Mapping[str, Any]) -> tuple[str, str, str]:
        return (
            "online-api",
            normalize_chat_completions_url(config.get("base_url", "")),
            str(config.get("model", "")).strip(),
        )

    def generate(self, request: PromptRequest, config: Mapping[str, Any]) -> str:
        self.validate(config, has_images=bool(request.images))
        env_name = config["api_key_env"]
        secret = os.environ[env_name]
        max_side = config["api_max_image_side"]
        payload = {
            "model": config["model"].strip(),
            "messages": build_openai_messages(
                request,
                lambda image: image_to_data_uri(image, max_side),
            ),
            "max_tokens": request.max_new_tokens,
            "temperature": request.temperature,
            "seed": request.seed,
        }
        headers = _parse_headers(config.get("custom_headers", "{}"))
        headers["Content-Type"] = "application/json"
        headers["Authorization"] = f"Bearer {secret}"
        http_request = urllib.request.Request(
            normalize_chat_completions_url(config["base_url"]),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with self._opener(http_request, timeout=config["timeout"]) as response:
                raw = response.read()
        except HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = str(exc)
            safe_body = redact_secrets(body, [secret])[:2000]
            raise SkillPromptError(
                "请求发送",
                f"HTTP {exc.code}: {safe_body}",
            ) from exc
        except (TimeoutError, URLError, OSError) as exc:
            safe_message = redact_secrets(str(exc), [secret])
            raise SkillPromptError("请求发送", safe_message) from exc

        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SkillPromptError("响应解析", "服务端返回的不是有效 JSON") from exc
        return extract_assistant_text(decoded)

    def unload(self, config: Mapping[str, Any]) -> None:
        return None
