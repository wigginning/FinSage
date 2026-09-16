"""T106 Redis 封装单测（注入 fakeredis，无需真实 Redis）。"""

from __future__ import annotations

import fakeredis

from finsage.persistence.redis import FinRedis


def _build() -> FinRedis:
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    return FinRedis(client=client)


def test_ping() -> None:
    assert _build().ping() is True


def test_cache_set_get_delete() -> None:
    r = _build()
    assert r.cache_get("k") is None
    assert r.cache_set("k", "v") is True
    assert r.cache_get("k") == "v"
    assert r.cache_delete("k") is True
    assert r.cache_get("k") is None


def test_cache_ttl() -> None:
    r = _build()
    assert r.ttl("missing") == -2
    r.cache_set("k", "v", ttl=100)
    assert 0 < r.ttl("k") <= 100


def test_cache_json_roundtrip() -> None:
    r = _build()
    assert r.cache_set_json("j", {"a": 1, "b": [True, None]}) is True
    assert r.cache_get_json("j") == {"a": 1, "b": [True, None]}
    assert r.cache_get_json("not-json") is None


def test_rate_limit_fixed_window() -> None:
    r = _build()
    for expected in (1, 2, 3):
        assert r.rate_limit_add("rl:bob", window_seconds=60) == expected
    assert 0 < r.ttl("rl:bob") <= 60


def test_rate_limit_new_window() -> None:
    r = _build()
    r.rate_limit_add("rl:new", window_seconds=1)
    r.client.delete("rl:new")
    assert r.rate_limit_add("rl:new", window_seconds=1, step=5) == 5


def test_set_nx_only_once() -> None:
    r = _build()
    assert r.set_nx("lock:x", "1", ttl=10) is True
    assert r.set_nx("lock:x", "2", ttl=10) is False
    assert r.cache_get("lock:x") == "1"