"""口令哈希与恒定时间校验（ADR-0019 §4 登录端点）。

方案：``hashlib.pbkdf2_hmac("sha256", ...)`` + 每口令随机盐，编码为
``pbkdf2_sha256$<iterations>$<salt_b64url>$<hash_b64url>``。

约束与理由：

- **不引入第三方口令库**（bcrypt / argon2 等），遵循 AGENTS.md §1 技术栈冻结；
  PBKDF2-HMAC-SHA256 是标准库内可获得的最强口令派生函数（OWASP 亦认可其配置化使用）。
- 迭代次数取 600,000（OWASP 对 PBKDF2-HMAC-SHA256 的建议下限）。
- 校验用 ``hmac.compare_digest`` 做**恒定时间**比较，避免时序侧信道。
- ``DUMMY_HASH`` 用于**时序对齐**：账号不存在时也跑一次同等开销的派生，使
  "账号不存在"与"口令错误"的响应耗时不可区分，不泄露某个邮箱是否已注册。
- 调用方须自行限制口令长度（见 ``api.schemas.LoginRequest.password`` 的
  ``max_length``），避免超长口令造成 CPU DoS。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 600_000
_SALT_BYTES = 16
_HASH_BYTES = 32

# 预生成的诱饵哈希（对应一个随机口令，任何输入都校验失败）。
# 仅在账号不存在/无口令时用于时序对齐，绝不代表任何真实凭据。
DUMMY_HASH = (
    "pbkdf2_sha256$600000$J7-SEtCW3cYVxZEJuHquQw$"
    "CN_KvLk_T2JJsugRKmb4UOM_PhR3F3VPF6SV6cShrM8"
)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, *, iterations: int = _ITERATIONS) -> str:
    """生成口令哈希编码串。``iterations`` 仅供测试降开销，生产用默认值。"""
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, _HASH_BYTES
    )
    return f"{_ALGORITHM}${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """恒定时间校验口令。编码格式非法一律返回 False（不抛异常、不外泄原因）。"""
    try:
        algorithm, iterations_text, salt_text, hash_text = encoded.split("$", 3)
        if algorithm != _ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = _b64decode(salt_text)
        expected = _b64decode(hash_text)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, len(expected)
    )
    return hmac.compare_digest(actual, expected)


__all__ = ["DUMMY_HASH", "hash_password", "verify_password"]
