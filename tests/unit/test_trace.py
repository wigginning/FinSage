"""trace 冒烟：UUID 格式、request_id/trace_id 传播与恢复。"""

from __future__ import annotations

import uuid

from finsage.observability.trace import (
    get_request_id,
    get_trace_id,
    new_request_id,
    new_trace_id,
    restore,
    set_request_id,
    set_trace_id,
    trace_token,
    uuid_str,
)


def test_uuid_str_is_uuid4() -> None:
    """uuid_str 返回合法 UUID4 字符串（36 位含连字符）。"""
    value = uuid_str()
    parsed = uuid.UUID(value, version=4)
    assert str(parsed) == value
    assert len(value) == 36


def test_ids_are_unique_and_distinct() -> None:
    """request_id / trace_id 产出各自唯一且互不相同。"""
    req_a, req_b = new_request_id(), new_request_id()
    trace = new_trace_id()
    assert req_a != req_b
    assert req_a != trace


def test_context_set_get_and_restore() -> None:
    """set/get 生效，trace_token + restore 恢复旧值。"""
    set_request_id("r1")
    set_trace_id("t1")
    token = trace_token()

    set_request_id("r2")
    set_trace_id("t2")
    assert get_request_id() == "r2"
    assert get_trace_id() == "t2"

    restore(token)
    assert get_request_id() == "r1"
    assert get_trace_id() == "t1"
