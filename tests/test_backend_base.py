import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from skill_prompt.backends.base import BackendRegistry, ModelCache
from skill_prompt.errors import SkillPromptError


def test_registry_returns_registered_backend_and_latest_registration_wins():
    registry = BackendRegistry()
    first = object()
    second = object()

    registry.register("api", first)
    registry.register("api", second)

    assert registry.get("api") is second


def test_registry_rejects_unknown_backend():
    with pytest.raises(SkillPromptError) as error:
        BackendRegistry().get("missing")

    assert error.value.stage == "模型加载"
    assert "missing" in str(error.value)


def test_cache_reuses_same_key_and_keeps_different_keys_independent():
    cache = ModelCache()
    calls = []

    first = cache.get_or_load("a", lambda: calls.append("a") or object())
    same = cache.get_or_load("a", lambda: calls.append("wrong") or object())
    other = cache.get_or_load("b", lambda: calls.append("b") or object())

    assert first is same
    assert first is not other
    assert calls == ["a", "b"]


def test_cache_calls_loader_once_for_concurrent_same_key():
    cache = ModelCache()
    loader_started = threading.Event()
    allow_finish = threading.Event()
    calls = 0
    instance = object()

    def loader():
        nonlocal calls
        calls += 1
        loader_started.set()
        assert allow_finish.wait(1)
        return instance

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(cache.get_or_load, "shared", loader)
        assert loader_started.wait(1)
        second = executor.submit(cache.get_or_load, "shared", loader)
        allow_finish.set()

    assert first.result() is instance
    assert second.result() is instance
    assert calls == 1


def test_loader_failure_does_not_poison_cache():
    cache = ModelCache()

    with pytest.raises(ValueError, match="load failed"):
        cache.get_or_load("model", lambda: (_ for _ in ()).throw(ValueError("load failed")))

    recovered = object()
    assert cache.get_or_load("model", lambda: recovered) is recovered


def test_generation_lock_serializes_same_key():
    cache = ModelCache()
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first_job():
        with cache.generation_lock("model"):
            first_entered.set()
            assert release_first.wait(1)

    def second_job():
        with cache.generation_lock("model"):
            second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_job)
        assert first_entered.wait(1)
        second = executor.submit(second_job)
        assert not second_entered.wait(0.05)
        release_first.set()
        first.result()
        second.result()

    assert second_entered.is_set()


def test_unload_calls_closer_and_allows_reload():
    cache = ModelCache()
    instance = object()
    closed = []
    cache.get_or_load("model", lambda: instance)

    cache.unload("model", closed.append)
    replacement = object()

    assert closed == [instance]
    assert cache.get_or_load("model", lambda: replacement) is replacement


def test_unload_missing_key_is_a_noop():
    cache = ModelCache()
    closed = []

    cache.unload("missing", closed.append)

    assert closed == []
