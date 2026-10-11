import math
from collections.abc import Callable
from typing import Any

from PIL import Image

from .errors import SkillPromptError
from .types import PromptRequest


def build_openai_messages(
    request: PromptRequest,
    image_encoder: Callable[[Image.Image], str],
) -> list[dict[str, Any]]:
    if len(request.images) > 5:
        raise SkillPromptError("图片转换", "最多支持 5 张参考图")
    content: list[dict[str, Any]] = [
        {
            "type": "image_url",
            "image_url": {"url": image_encoder(image)},
        }
        for image in request.images
    ]
    content.append({"type": "text", "text": request.task})
    return [
        {"role": "system", "content": request.system_prompt},
        {"role": "user", "content": content},
    ]


def estimate_text_tokens(*texts: str) -> int:
    byte_count = sum(len(text.encode("utf-8")) for text in texts)
    return math.ceil(byte_count / 3)
