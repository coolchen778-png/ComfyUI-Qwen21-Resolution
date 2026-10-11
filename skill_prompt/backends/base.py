import threading
from collections.abc import Callable, Hashable, Mapping
from typing import Any, Protocol

from ..errors import SkillPromptError
from ..types import PromptRequest


class BackendAdapter(Protocol):
    def validate(self, config: Mapping[str, Any], has_images: bool) -> None: ...

    def cache_key(self, config: Mapping[str, Any]) -> Hashable: ...

    def generate(self, request: PromptRequest, config: Mapping[str, Any]) -> str: ...

    def unload(self, config: Mapping[str, Any]) -> None: ...


class BackendRegistry:
    def __init__(self):
        self._adapters: dict[str, BackendAdapter] = {}

    def register(self, name: str, adapter: BackendAdapter) -> None:
        self._adapters[name] = adapter

    def get(self, name: str) -> BackendAdapter:
        try:
            return self._adapters[name]
        except KeyError as exc:
            raise SkillPromptError("模型加载", f"未知后端: {name}") from exc


class ModelCache:
    def __init__(self):
        self._guard = threading.RLock()
        self._instances: dict[Hashable, Any] = {}
        self._locks: dict[Hashable, threading.RLock] = {}

    def _lock_for(self, key: Hashable) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(key, threading.RLock())

    def get_or_load(self, key: Hashable, loader: Callable[[], Any]) -> Any:
        with self._guard:
            if key in self._instances:
                return self._instances[key]
        with self._lock_for(key):
            with self._guard:
                if key in self._instances:
                    return self._instances[key]
            instance = loader()
            with self._guard:
                self._instances[key] = instance
            return instance

    def generation_lock(self, key: Hashable) -> threading.RLock:
        return self._lock_for(key)

    def unload(self, key: Hashable, closer: Callable[[Any], None]) -> None:
        with self._lock_for(key):
            with self._guard:
                instance = self._instances.pop(key, None)
            if instance is not None:
                closer(instance)
