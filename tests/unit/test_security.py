"""口令哈希与校验单测（ADR-0019 §4）。

测试一律用低迭代次数（``iterations=1000``）以控制耗时；生产默认值见
``finsage.security._ITERATIONS``（600,000，OWASP 对 PBKDF2-HMAC-SHA256 的建议下限）。
"""
from __future__ import annotations

from finsage.security import DUMMY_HASH, hash_password, verify_password

# 测试专用低开销参数（生产默认 600k 太慢，且不影响逻辑正确性）。
_ITERS = 1000


def test_hash_verify_roundtrip() -> None:
    encoded = hash_password("s3cret-pass", iterations=_ITERS)
    assert verify_password("s3cret-pass", encoded) is True
    assert verify_password("wrong-pass", encoded) is False


def test_hash_uses_random_salt() -> None:
    """相同口令两次哈希结果不同（每口令随机盐），防止彩虹表与跨账号比对。"""
    assert hash_password("same", iterations=_ITERS) != hash_password("same", iterations=_ITERS)


def test_encoded_format_carries_iterations() -> None:
    encoded = hash_password("p", iterations=_ITERS)
    algorithm, iterations, _salt, _digest = encoded.split("$", 3)
    assert algorithm == "pbkdf2_sha256"
    assert int(iterations) == _ITERS


def test_verify_rejects_malformed_encodings() -> None:
    """格式非法一律返回 False（不抛异常、不外泄原因）。"""
    assert verify_password("x", "") is False
    assert verify_password("x", "garbage") is False
    assert verify_password("x", "other_algo$1000$abc$def") is False  # 算法名不匹配
    assert verify_password("x", "pbkdf2_sha256$notanint$abc$def") is False  # 迭代次数非整数


def test_dummy_hash_never_verifies() -> None:
    """诱饵哈希（时序对齐用）对任何输入都校验失败，绝不成为可用凭据。"""
    assert verify_password("anything", DUMMY_HASH) is False
    assert verify_password("", DUMMY_HASH) is False


def test_dummy_hash_uses_production_iterations() -> None:
    """诱饵必须与生产同开销，否则时序仍会泄露"账号是否存在"。"""
    assert int(DUMMY_HASH.split("$", 3)[1]) >= 600_000
