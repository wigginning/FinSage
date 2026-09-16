"""结构化日志与 IO 埋点基座（T005）。

规则（规格全局执行规则）：
- 所有节点 IO 均需埋点：入参 / 出参 / 耗时 / 成败，便于问题定位；
- 敏感字段（密钥、token、password、secret 等）记日志前一律脱敏；
- 日志自动携带 request_id / trace_id（来自 observability.trace）。

用法：
    logger = get_logger(__name__)
    @io_point("provider", "get_quote")            # 同步
    def get_quote(code): ...

    @io_point("retrieval", "search")              # 异步
    async def search(q): ...
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import sys
import time
from collections.abc import Callable
from typing import Any, TypeVar, cast

from .trace import get_request_id, get_trace_id

# 需脱敏的字段名（不区分大小写）。
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "secret_key",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "private_key",
        "client_secret",
        "cookie",
        "ssn",
        "credit_card",
        "card_number",
    }
)
_MASK = "***"


def mask_value(value: Any) -> Any:
    """递归脱敏 dict/list 中命中敏感键的值；其它类型原样返回。"""
    if isinstance(value, dict):
        return {
            k: (
                _MASK
                if k.lower() in _SENSITIVE_KEYS and not isinstance(v, (dict, list, tuple))
                else mask_value(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [mask_value(v) for v in value]
    return value


def _snapshot(value: Any) -> Any:
    """对参数/返回值做可 JSON 化快照并脱敏；失败则降级为占位符，不抛异常。"""
    try:
        return mask_value(value)
    except Exception:  # pragma: no cover - 防御性降级
        return "<unserializable>"


class _JsonFormatter(logging.Formatter):
    """将日志记录序列化为单行 JSON，自动附加 request_id / trace_id。"""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D102
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
            "trace_id": get_trace_id(),
        }
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            payload["extra"] = mask_value(record.extra)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: int | str = logging.INFO) -> None:
    """初始化根 logger 为结构化 JSON 输出（同步到 stdout）。"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """获取子 logger；命名建议使用模块路径（如 'finsage.provider'）。"""
    return logging.getLogger(name)


F = TypeVar("F", bound=Callable[..., Any])


def io_point(component: str, operation: str, *, mask_args: bool = True) -> Callable[[F], F]:
    """IO 埋点装饰器：记录入参、出参、耗时、成败。

    同步函数与异步函数均适用；异常在软记录后重新抛出（不吞）。
    """

    def decorator(func: F) -> F:
        log = get_logger(func.__module__)
        is_async = inspect.iscoroutinefunction(func)

        @functools.wraps(func)
        def sync_wrap(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            inputs = _snapshot(kwargs) if mask_args else None
            log.info(
                "io.enter",
                extra={"extra": {"component": component, "operation": operation, "input": inputs}},
            )
            try:
                result = func(*args, **kwargs)
                log.info(
                    "io.exit",
                    extra={
                        "extra": {
                            "component": component,
                            "operation": operation,
                            "ms": round((time.monotonic() - start) * 1000, 2),
                            "success": True,
                            "output": _snapshot(result),
                        }
                    },
                )
                return result
            except Exception as exc:  # noqa: BLE001 - 埋点观察点需覆盖所有异常
                log.error(
                    "io.error",
                    exc_info=exc,
                    extra={
                        "extra": {
                            "component": component,
                            "operation": operation,
                            "ms": round((time.monotonic() - start) * 1000, 2),
                            "success": False,
                            "error": type(exc).__name__,
                        }
                    },
                )
                raise

        @functools.wraps(func)
        async def async_wrap(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            inputs = _snapshot(kwargs) if mask_args else None
            log.info(
                "io.enter",
                extra={"extra": {"component": component, "operation": operation, "input": inputs}},
            )
            try:
                result = await func(*args, **kwargs)
                log.info(
                    "io.exit",
                    extra={
                        "extra": {
                            "component": component,
                            "operation": operation,
                            "ms": round((time.monotonic() - start) * 1000, 2),
                            "success": True,
                            "output": _snapshot(result),
                        }
                    },
                )
                return result
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "io.error",
                    exc_info=exc,
                    extra={
                        "extra": {
                            "component": component,
                            "operation": operation,
                            "ms": round((time.monotonic() - start) * 1000, 2),
                            "success": False,
                            "error": type(exc).__name__,
                        }
                    },
                )
                raise

        if is_async:
            return cast(F, async_wrap)
        return cast(F, sync_wrap)

    return decorator
