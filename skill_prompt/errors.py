import re
from collections.abc import Iterable


class SkillPromptError(RuntimeError):
    def __init__(self, stage: str, message: str):
        self.stage = stage
        self.message = message
        super().__init__(f"[{stage}] {message}")


_SENSITIVE_HEADER = re.compile(
    r"(?im)\b(authorization|api-key|x-api-key)\s*[:=]\s*([^\r\n,}]+)"
)


def redact_secrets(value: str, secrets: Iterable[str]) -> str:
    redacted = str(value)
    for secret in sorted((str(item) for item in secrets if item), key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    return _SENSITIVE_HEADER.sub(lambda match: f"{match.group(1)}: [REDACTED]", redacted)
