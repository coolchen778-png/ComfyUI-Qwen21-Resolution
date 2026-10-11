import re
from collections.abc import Mapping
from typing import Any

from .errors import SkillPromptError


_LEADING_THINK = re.compile(r"^\s*<think>(.*?)</think>\s*", re.DOTALL | re.IGNORECASE)
_UNCLOSED_LEADING_THINK = re.compile(r"^\s*<think>", re.IGNORECASE)


def extract_assistant_text(payload: Mapping[str, Any]) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SkillPromptError("响应解析", "响应缺少助手文本") from exc

    if isinstance(content, str) and content.strip():
        return content

    if isinstance(content, list):
        text_blocks = [
            block["text"]
            for block in content
            if isinstance(block, Mapping)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
            and block["text"].strip()
        ]
        if text_blocks:
            return "\n".join(text_blocks)

    raise SkillPromptError("响应解析", "响应缺少助手文本")


def strip_leading_think(text: str) -> str:
    match = _LEADING_THINK.match(text)
    if match:
        return text[match.end():].strip()
    if _UNCLOSED_LEADING_THINK.match(text):
        return ""
    return text
