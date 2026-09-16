"""唯一标识与链路追踪工具。

- uuid_str：生成 UUID4 字符串（对应数据库 CHAR(36) 字段，见规格 Master-Schema 约定）；
- request_id / trace_id：通过 ContextVar 在请求内传播，供日志埋点自动携带；
- 对外不暴露任何身份/敏感信息，仅用于链路定位。
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

# 链路上下文：跨异步任务也必须手动 propagate（见各 Async 用例）。
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_id_ctx: ContextVar[str | None] = ContextVar("trace_id", default=None)


def uuid_str() -> str:
    """生成一个 UUID4 字符串（36 位，含连字符），用作主键 / 外键。"""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """生成一个独立的 request_id（推荐用于一次性请求标识）。"""
    return uuid_str()


def new_trace_id() -> str:
    """生成一个独立的 trace_id（推荐用于跨服务/跨节点的一次研究链路）。"""
    return uuid_str()


def get_request_id() -> str | None:
    """读取当前上下文 request_id；无则 None。"""
    return request_id_ctx.get()


def get_trace_id() -> str | None:
    """读取当前上下文 trace_id；无则 None。"""
    return trace_id_ctx.get()


def set_request_id(value: str | None) -> None:
    """设置当前上下文 request_id（不校验格式，保持轻量）。"""
    request_id_ctx.set(value)


def set_trace_id(value: str | None) -> None:
    """设置当前上下文 trace_id（不校验格式，保持轻量）。"""
    trace_id_ctx.set(value)


class TraceToken:
    """一次性令牌，用于 reset 到此前状态，避免嵌套污染。"""

    __slots__ = ("_req", "_trace")

    def __init__(self, req: str | None, trace: str | None) -> None:
        self._req = req
        self._trace = trace


def trace_token() -> TraceToken:
    """快照当前上下文，返回令牌。"""
    return TraceToken(get_request_id(), get_trace_id())


def restore(token: TraceToken) -> None:
    """用令牌恢复上下文到快照时的状态。"""
    set_request_id(token._req)
    set_trace_id(token._trace)
