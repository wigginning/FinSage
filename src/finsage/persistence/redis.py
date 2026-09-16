"""Redis 客户端封装（T106）。

按规格用途封装三类能力（§4 缓存 / 限流 / 临时态），全部带 IO 埋点：
- 缓存：get / set(带 TTL) / delete；
- 限流：rate_limit 基于 INCR + EXPIRE 的固定窗口计数；
- 临时态：临时键 set_nx（仅当不存在时写入，可用于幂等/分布式锁的前置）。

所有方法接受外部注入 client，便于测试用 fakeredis；无真实 Redis 时调用方自行保证
连接可用。
"""
from __future__ import annotations

import json
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from finsage.observability.logger import get_logger, io_point
from finsage.settings import Settings, get_settings

logger = get_logger(__name__)


class ConnectionUnavailableError(RuntimeError):
    """Redis 连接不可用。"""


class FinRedis:
    """Redis 封装：缓存 / 限流 / 临时态。"""

    def __init__(self, client: Redis | None = None, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self._client = client or Redis.from_url(settings.redis_url, decode_responses=True)

    @property
    def client(self) -> Redis:
        """底层 Redis 客户端（测试注入/特殊场景可用）。"""
        return self._client

    @io_point("cache", "redis_ping")
    def ping(self) -> bool:
        """健康检查。"""
        try:
            return bool(self._client.ping())
        except RedisError as exc:  # pragma: no cover - 依赖环境
            logger.warning("redis.ping 失败: %s", exc)
            return False

    # ---- 缓存 ----

    @io_point("cache", "cache_get")
    def cache_get(self, key: str) -> str | None:
        """读取缓存；不存在返回 None。

        构造时强制 ``decode_responses=True``，故实际返回 str；stub 仍把
        ``Redis.get`` 定型为 ``bytes | str | None``，这里显式收窄到 ``str | None``。
        """
        raw = self._client.get(key)
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else raw

    @io_point("cache", "cache_set")
    def cache_set(self, key: str, value: str, ttl: int | None = None) -> bool:
        """写入缓存，可选 TTL（秒）。"""
        if ttl is not None:
            return bool(self._client.set(key, value, ex=ttl))
        return bool(self._client.set(key, value))

    @io_point("cache", "cache_delete")
    def cache_delete(self, key: str) -> bool:
        """删除缓存。"""
        return bool(self._client.delete(key))

    @io_point("cache", "cache_get_json")
    def cache_get_json(self, key: str) -> Any:
        """读取并解析 JSON 缓存；缺失/解析失败返回 None。"""
        raw = self._client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None

    @io_point("cache", "cache_set_json")
    def cache_set_json(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """序列化写入 JSON 缓存。"""
        payload = json.dumps(value, ensure_ascii=False, default=str)
        return self.cache_set(key, payload, ttl=ttl)

    # ---- 限流（固定窗口，INCR + EXPIRE）----

    @io_point("cache", "cache_incr")
    def rate_limit_add(self, key: str, window_seconds: int, step: int = 1) -> int:
        """固定窗口计数：对 key 自增，首次写入时设置过期窗口。返回当前计数。"""
        n = self._client.incr(key, step)
        if n == step:
            self._client.expire(key, window_seconds)
        return int(n)

    @io_point("cache", "cache_ttl")
    def ttl(self, key: str) -> int:
        """剩余 TTL（秒）；键不存在返回 -2，无过期返回 -1。"""
        return int(self._client.ttl(key))

    # ---- 临时态（仅当不存在时写入）----

    @io_point("cache", "cache_set_nx")
    def set_nx(self, key: str, value: str, ttl: int | None = None) -> bool:
        """NX 写入：键不存在才成功（幂等/临时锁前置）。"""
        return bool(self._client.set(key, value, nx=True, ex=ttl))


def get_fin_redis(client: Redis | None = None) -> FinRedis:
    """获取 Redis 封装（可用测试 client 注入覆盖）。"""
    return FinRedis(client=client)