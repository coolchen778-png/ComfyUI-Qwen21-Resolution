from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptRequest:
    system_prompt: str
    task: str
    images: tuple[Any, ...]
    max_new_tokens: int
    temperature: float
    seed: int
