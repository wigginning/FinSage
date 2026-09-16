"""exceptions 冒烟：FIN 错误码枚举、retryable、HTTP 映射、异常层级。"""

from __future__ import annotations

import pytest

from finsage.exceptions import (
    ErrorCode,
    FinSageError,
    NoEvidenceError,
    ProviderError,
    RateLimitedError,
    raise_for_code,
)

# §8.1 冻结基线的 25 个错误码（ADR 授权扩展前）。改动或删除其中任何一个都属破坏冻结契约。
_FROZEN_BASELINE: set[str] = {
    "FIN-1001",
    "FIN-1002",
    "FIN-1003",
    "FIN-1004",
    "FIN-1101",
    "FIN-1102",
    "FIN-2001",
    "FIN-2002",
    "FIN-2003",
    "FIN-2004",
    "FIN-2101",
    "FIN-2102",
    "FIN-2201",
    "FIN-3001",
    "FIN-3002",
    "FIN-3003",
    "FIN-3101",
    "FIN-3102",
    "FIN-4001",
    "FIN-4002",
    "FIN-4101",
    "FIN-5001",
    "FIN-5002",
    "FIN-5003",
    "FIN-6001",
}

# 经 ADR 显式授权的新增码（ADR-0020 §7：API 层限流）。新增码须先出 ADR 再登记到此处。
_ADR_EXTENSIONS: set[str] = {"FIN-1005"}


def test_error_code_values_frozen() -> None:
    """枚举值即 §8.1 冻结的 FIN 错误码字符串。"""
    assert ErrorCode.INVALID_REQUEST == "FIN-1001"
    assert ErrorCode.PROVIDER_RATE_LIMITED == "FIN-2003"
    assert ErrorCode.INTERNAL_ERROR == "FIN-6001"
    # FIN-1005 是 ADR-0020 §7 授权的受控扩展（API 层限流）。
    assert ErrorCode.RATE_LIMITED == "FIN-1005"
    # §8.1 冻结基线（25）+ ADR 授权扩展（1）
    assert len(ErrorCode) == len(_FROZEN_BASELINE) + len(_ADR_EXTENSIONS)


def test_frozen_baseline_unchanged() -> None:
    """§8.1 冻结基线的每个码仍然存在——新增不得改动或删除既有码。"""
    current = {c.value for c in ErrorCode}
    missing = _FROZEN_BASELINE - current
    assert not missing, f"既有错误码被删除或改名: {sorted(missing)}"


def test_no_unauthorized_error_codes() -> None:
    """除 ADR 显式授权的扩展外，不允许出现新的错误码（守住冻结契约）。"""
    current = {c.value for c in ErrorCode}
    unexpected = current - _FROZEN_BASELINE - _ADR_EXTENSIONS
    assert not unexpected, f"未经 ADR 授权的错误码: {sorted(unexpected)}"


def test_mapping_tables_cover_all_codes() -> None:
    """ADR-0020 §7 实施约束：两张映射表必须对 ErrorCode 全覆盖。

    否则 ``FinSageError.http_status`` / ``retryable`` 会抛 ``KeyError``。
    """
    from finsage.exceptions import _HTTP_STATUS, _RETRY_FLAG

    assert set(_HTTP_STATUS) == set(ErrorCode)
    assert set(_RETRY_FLAG) == set(ErrorCode)


def test_rate_limited_semantics() -> None:
    """FIN-1005（ADR-0020 §7）：429 + 可重试 + 携带 Retry-After。

    与 FIN-2003（上游数据源限流）区分：本码表示客户端请求频率超限。
    """
    exc = RateLimitedError(retry_after=42)
    assert exc.code is ErrorCode.RATE_LIMITED
    assert exc.code == "FIN-1005"
    assert exc.http_status == 429
    assert exc.retryable is True
    assert exc.retry_after == 42


def test_retryable_flags() -> None:
    """retryable 按 §8.1 Retry 列：可重试 True / 不可重试 False。"""
    assert ProviderError("x").retryable is True  # FIN-2002 yes
    assert NoEvidenceError("x").retryable is False  # FIN-3003 no
    assert FinSageError("x").retryable is False  # FIN-6001 no


def test_explicit_retryable_override() -> None:
    """业务可用 retryable 参数显式覆盖 conditional 语义。"""
    assert FinSageError("conditional", retryable=True).retryable is True


def test_http_status_mapping() -> None:
    """对外 HTTP 状态码映射与 §8 约束一致。"""
    assert ProviderError("x").http_status == 503
    assert NoEvidenceError("x").http_status == 200
    assert FinSageError("x").http_status == 500


def test_exception_subclass_and_raise_for_code() -> None:
    """raise_for_code 落到对应默认异常类型。"""
    with pytest.raises(NoEvidenceError):
        raise_for_code(ErrorCode.NO_EVIDENCE)
    with pytest.raises(FinSageError) as exc:
        raise_for_code(ErrorCode.RESOURCE_NOT_FOUND)
    assert exc.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert exc.value.http_status == 404
