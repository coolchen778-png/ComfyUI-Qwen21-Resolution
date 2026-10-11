import pytest

from skill_prompt.errors import SkillPromptError, redact_secrets
from skill_prompt.response import extract_assistant_text, strip_leading_think
from skill_prompt.types import PromptRequest


def test_prompt_request_preserves_generation_inputs():
    request = PromptRequest(
        system_prompt="rules",
        task="make a prompt",
        images=("image-1",),
        max_new_tokens=512,
        temperature=0.4,
        seed=7,
    )

    assert request.system_prompt == "rules"
    assert request.task == "make a prompt"
    assert request.images == ("image-1",)
    assert request.max_new_tokens == 512
    assert request.temperature == 0.4
    assert request.seed == 7


def test_extract_assistant_text_accepts_string_content():
    payload = {"choices": [{"message": {"content": "final prompt"}}]}

    assert extract_assistant_text(payload) == "final prompt"


def test_extract_assistant_text_joins_text_blocks_only():
    payload = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "reasoning", "text": "hidden"},
                        {"type": "text", "text": "first"},
                        {"type": "text", "text": "second"},
                    ]
                }
            }
        ]
    }

    assert extract_assistant_text(payload) == "first\nsecond"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": []}}]},
        {"choices": [{"message": {"content": [{"type": "reasoning", "text": "x"}]}}]},
    ],
)
def test_extract_assistant_text_rejects_missing_text(payload):
    with pytest.raises(SkillPromptError) as error:
        extract_assistant_text(payload)

    assert error.value.stage == "响应解析"


def test_strip_leading_think_removes_complete_reasoning_block():
    text = "  \n<think>private reasoning</think>\n\nFinal prompt"

    assert strip_leading_think(text) == "Final prompt"


def test_strip_leading_think_removes_unclosed_leading_reasoning_block():
    assert strip_leading_think("<think>unfinished reasoning") == ""


@pytest.mark.parametrize(
    "text",
    [
        "Use <think> as a literal token",
        "<prompt><think>style</think></prompt>",
        "Plain final prompt",
    ],
)
def test_strip_leading_think_preserves_nonleading_tags(text):
    assert strip_leading_think(text) == text


def test_redact_secrets_hides_header_values_and_known_secret():
    value = (
        "Authorization: Bearer super-secret\n"
        "api-key: another-secret\n"
        "x-api-key: third-secret\n"
        "detail=super-secret"
    )

    redacted = redact_secrets(value, ["super-secret"])

    assert "super-secret" not in redacted
    assert "another-secret" not in redacted
    assert "third-secret" not in redacted
    assert redacted.count("[REDACTED]") >= 4
