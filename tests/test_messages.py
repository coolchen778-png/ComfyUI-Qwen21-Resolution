import pytest
from PIL import Image

from skill_prompt.errors import SkillPromptError
from skill_prompt.messages import build_openai_messages, estimate_text_tokens
from skill_prompt.types import PromptRequest


def _request(images=()):
    return PromptRequest(
        system_prompt="You generate prompts.\n\n<skill>RULES</skill>",
        task="Use the references",
        images=tuple(images),
        max_new_tokens=256,
        temperature=0.2,
        seed=9,
    )


def test_build_openai_messages_keeps_image_order_before_task_text():
    images = [Image.new("RGB", (1, 1), color) for color in ("red", "blue", "green")]
    labels = {id(image): f"data:image/png;base64,image-{index}" for index, image in enumerate(images, 1)}

    messages = build_openai_messages(_request(images), lambda image: labels[id(image)])

    assert messages == [
        {
            "role": "system",
            "content": "You generate prompts.\n\n<skill>RULES</skill>",
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,image-1"},
                },
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,image-2"},
                },
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,image-3"},
                },
                {"type": "text", "text": "Use the references"},
            ],
        },
    ]


def test_build_openai_messages_without_images_has_only_text_block():
    messages = build_openai_messages(_request(), lambda image: "unused")

    assert messages[1]["content"] == [{"type": "text", "text": "Use the references"}]


def test_build_openai_messages_rejects_sixth_image():
    images = [Image.new("RGB", (1, 1)) for _ in range(6)]

    with pytest.raises(SkillPromptError, match="最多支持 5 张"):
        build_openai_messages(_request(images), lambda image: "uri")


def test_estimate_text_tokens_uses_combined_utf8_bytes():
    assert estimate_text_tokens("abc", "规则") == 3
    assert estimate_text_tokens("") == 0
