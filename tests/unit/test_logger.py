"""logger 冒烟：敏感值脱敏 + IO 埋点（入参/出参/耗时/成败）。"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from finsage.observability.logger import io_point, mask_value, setup_logging


def test_mask_value_scalars_and_nested() -> None:
    """命中的敏感键标量被脱敏，嵌套结构继续递归。"""
    data = {
        "api_key": "sk-secret-123",
        "password": "p@ss",
        "user": {"token": "abc", "name": "ok"},
        "items": [{"secret_key": "s1"}],
    }
    masked = mask_value(data)
    assert masked["api_key"] == "***"
    assert masked["password"] == "***"
    assert masked["user"]["token"] == "***"
    assert masked["user"]["name"] == "ok"
    assert masked["items"][0]["secret_key"] == "***"


def test_mask_value_records_emits_masked_json(capsys: pytest.CaptureFixture[str]) -> None:
    """io_point 记录埋点 JSON 中敏感字段已脱敏（不泄露真实值）。"""
    setup_logging(logging.DEBUG)

    @io_point("test", "op")
    def secret_op(token: str) -> dict:
        return {"secret_key": token}

    secret_op("REAL-SECRET")

    out = capsys.readouterr().out
    # 日志中只出现脱敏值，绝不出现原始真实密钥
    assert "REAL-SECRET" not in out
    assert "***" in out
    assert "io.enter" in out
    assert "io.exit" in out


def test_io_point_sync_success(capsys: pytest.CaptureFixture[str]) -> None:
    """同步成功路径：enter + exit(success=True)。"""
    setup_logging()

    @io_point("component-x", "compute")
    def add(a: int, b: int) -> int:
        return a + b

    assert add(1, 2) == 3
    out: str = capsys.readouterr().out
    parsed = [json.loads(line) for line in out.splitlines() if line.strip()]
    events = [p["message"] for p in parsed]
    assert "io.enter" in events and "io.exit" in events
    exit_evt = next(p for p in parsed if p["message"] == "io.exit")
    assert exit_evt["extra"]["success"] is True
    assert exit_evt["extra"]["component"] == "component-x"
    assert exit_evt["extra"]["operation"] == "compute"
    assert isinstance(exit_evt["extra"]["ms"], float)


def test_io_point_async_reraises(capsys: pytest.CaptureFixture[str]) -> None:
    """异步失败路径：soft 记录后重新抛出，异常不吞。"""
    setup_logging()

    @io_point("component-y", "boom")
    async def fail() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError):
        asyncio.run(fail())

    out: str = capsys.readouterr().out
    parsed = [json.loads(line) for line in out.splitlines() if line.strip()]
    err_evt = next(p for p in parsed if p["message"] == "io.error")
    assert err_evt["extra"]["success"] is False
    assert err_evt["extra"]["error"] == "ValueError"
