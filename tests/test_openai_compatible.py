import io
import json
from urllib.error import HTTPError

import pytest
from PIL import Image

from skill_prompt.backends.openai_compatible import (
    OpenAICompatibleBackend,
    normalize_chat_completions_url,
)
from skill_prompt.errors import SkillPromptError
from skill_prompt.types import PromptRequest


def _config(**overrides):
    config = {
        "base_url": "https://newapi.example/v1",
        "model": "qwen-vl",
        "api_key_env": "TEST_NEWAPI_KEY",
        "custom_headers": "{}",
        "timeout": 30,
        "api_max_image_side": 2048,
    }
    config.update(overrides)
    return config


def _request(images=()):
    return PromptRequest(
        system_prompt="SYSTEM RULES",
        task="Generate the final prompt",
        images=tuple(images),
        max_new_tokens=321,
        temperature=0.35,
        seed=42,
    )


class FakeResponse:
    def __init__(self, payload):
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.body


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://host", "https://host/v1/chat/completions"),
        ("https://host/", "https://host/v1/chat/completions"),
        ("https://host/v1", "https://host/v1/chat/completions"),
        ("https://host/prefix/v1/", "https://host/prefix/v1/chat/completions"),
        (
            "https://host/prefix/v1/chat/completions",
            "https://host/prefix/v1/chat/completions",
        ),
    ],
)
def test_normalize_chat_completions_url_appends_endpoint_once(base_url, expected):
    assert normalize_chat_completions_url(base_url) == expected


@pytest.mark.parametrize(
    "base_url",
    ["", "ftp://host/v1", "host/v1", "https:///v1", "https://host/v1?token=x"],
)
def test_normalize_chat_completions_url_rejects_invalid_urls(base_url):
    with pytest.raises(SkillPromptError) as error:
        normalize_chat_completions_url(base_url)

    assert error.value.stage == "请求发送"


def test_validate_accepts_environment_secret_and_safe_headers(monkeypatch):
    monkeypatch.setenv("TEST_NEWAPI_KEY", "secret")
    backend = OpenAICompatibleBackend(opener=lambda *args, **kwargs: None)

    backend.validate(_config(custom_headers='{"X-Provider": "newapi"}'), has_images=True)


@pytest.mark.parametrize(
    "overrides",
    [
        {"model": ""},
        {"custom_headers": "not-json"},
        {"custom_headers": "[]"},
        {"custom_headers": '{"Authorization": "Bearer stolen"}'},
        {"timeout": 0},
        {"api_max_image_side": -1},
    ],
)
def test_validate_rejects_invalid_api_configuration(monkeypatch, overrides):
    monkeypatch.setenv("TEST_NEWAPI_KEY", "secret")
    backend = OpenAICompatibleBackend(opener=lambda *args, **kwargs: None)

    with pytest.raises(SkillPromptError):
        backend.validate(_config(**overrides), has_images=False)


def test_validate_requires_named_environment_secret(monkeypatch):
    monkeypatch.delenv("MISSING_API_KEY", raising=False)
    backend = OpenAICompatibleBackend(opener=lambda *args, **kwargs: None)

    with pytest.raises(SkillPromptError, match="MISSING_API_KEY"):
        backend.validate(_config(api_key_env="MISSING_API_KEY"), has_images=False)


def test_cache_key_uses_normalized_endpoint_and_model(monkeypatch):
    monkeypatch.setenv("TEST_NEWAPI_KEY", "secret")
    backend = OpenAICompatibleBackend(opener=lambda *args, **kwargs: None)

    assert backend.cache_key(_config(base_url="https://host/v1/")) == (
        "online-api",
        "https://host/v1/chat/completions",
        "qwen-vl",
    )


def test_generate_sends_openai_multimodal_payload_and_safe_headers(monkeypatch):
    monkeypatch.setenv("TEST_NEWAPI_KEY", "top-secret")
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse({"choices": [{"message": {"content": "final result"}}]})

    backend = OpenAICompatibleBackend(opener=opener)
    image = Image.new("RGB", (2, 1), "red")

    result = backend.generate(
        _request([image]),
        _config(custom_headers='{"X-Provider": "newapi"}', api_max_image_side=1),
    )

    sent = captured["request"]
    payload = json.loads(sent.data.decode("utf-8"))
    headers = {key.casefold(): value for key, value in sent.header_items()}
    assert result == "final result"
    assert sent.full_url == "https://newapi.example/v1/chat/completions"
    assert captured["timeout"] == 30
    assert headers["authorization"] == "Bearer top-secret"
    assert headers["x-provider"] == "newapi"
    assert headers["content-type"] == "application/json"
    assert payload["model"] == "qwen-vl"
    assert payload["max_tokens"] == 321
    assert payload["temperature"] == 0.35
    assert payload["seed"] == 42
    assert payload["messages"][0] == {"role": "system", "content": "SYSTEM RULES"}
    image_block = payload["messages"][1]["content"][0]
    assert image_block["type"] == "image_url"
    assert image_block["image_url"]["url"].startswith("data:image/png;base64,")
    assert payload["messages"][1]["content"][-1] == {
        "type": "text",
        "text": "Generate the final prompt",
    }


def test_generate_accepts_text_block_array_response(monkeypatch):
    monkeypatch.setenv("TEST_NEWAPI_KEY", "secret")
    response = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "text", "text": "line one"},
                        {"type": "text", "text": "line two"},
                    ]
                }
            }
        ]
    }
    backend = OpenAICompatibleBackend(opener=lambda request, timeout: FakeResponse(response))

    assert backend.generate(_request(), _config()) == "line one\nline two"


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": []},
        b"not-json",
    ],
)
def test_generate_labels_malformed_responses(monkeypatch, payload):
    monkeypatch.setenv("TEST_NEWAPI_KEY", "secret")
    backend = OpenAICompatibleBackend(opener=lambda request, timeout: FakeResponse(payload))

    with pytest.raises(SkillPromptError) as error:
        backend.generate(_request(), _config())

    assert error.value.stage == "响应解析"


def test_generate_labels_timeout_as_request_error(monkeypatch):
    monkeypatch.setenv("TEST_NEWAPI_KEY", "secret")

    def timeout(request, timeout):
        raise TimeoutError("too slow")

    backend = OpenAICompatibleBackend(opener=timeout)

    with pytest.raises(SkillPromptError) as error:
        backend.generate(_request(), _config())

    assert error.value.stage == "请求发送"


def test_generate_redacts_and_limits_http_error_body(monkeypatch):
    secret = "secret-that-must-not-leak"
    monkeypatch.setenv("TEST_NEWAPI_KEY", secret)
    body = (f"Authorization: Bearer {secret}\n" + "x" * 5000).encode("utf-8")

    def fail(request, timeout):
        raise HTTPError(request.full_url, 500, "Server Error", None, io.BytesIO(body))

    backend = OpenAICompatibleBackend(opener=fail)

    with pytest.raises(SkillPromptError) as error:
        backend.generate(_request(), _config())

    rendered = str(error.value)
    assert error.value.stage == "请求发送"
    assert secret not in rendered
    assert "[REDACTED]" in rendered
    assert len(rendered) < 2200
