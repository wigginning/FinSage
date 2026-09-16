"""签名身份令牌（m08，§7 —— P0 认证升级）。

在既有静态 ``api_token`` 之上，为需要身份/租户语义的接口提供可解析的签名令牌：
载体 = ``{"user_id", "tenant_id", "roles", "exp"}``，用 ``HMAC-SHA256(secret)``
签名后以 URL-safe Base64 编码。仅用标准库（hmac/hashlib/base64/json），
不引入额外依赖（AGENTS.md §1 技术栈冻结）。

安全约束：
- secret 不得为空（空 secret 一律拒绝签发/校验，诚实失败而非降级）；
- 令牌含 ``exp``（Unix 秒）到期时间，过期视为无效；
- 解析失败/篡改 → 返回 None（由调用方按未认证处理），不外泄内部错误。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

# 载荷字段名（FROZEN，与 Principal / models.auth 对齐）。
_USER = "user_id"
_TENANT = "tenant_id"
_ROLES = "roles"
_EXP = "exp"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def sign_token(
    *,
    user_id: str,
    tenant_id: str,
    secret: str,
    roles: list[str] | None = None,
    ttl_seconds: int = 3600,
) -> str:
    """签发身份令牌。secret 为空抛 ValueError（拒绝降级签发）。"""
    if not secret:
        raise ValueError("identity token secret must not be empty")
    payload: dict[str, Any] = {
        _USER: user_id,
        _TENANT: tenant_id,
        _ROLES: roles or [],
        _EXP: int(time.time()) + int(ttl_seconds),
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return f"{_b64url(body)}.{_b64url(sig)}"


def verify_token(token: str, *, secret: str) -> dict[str, Any] | None:
    """校验并解析令牌；无效/过期/secret 空返回 None。"""
    if not secret or not token:
        return None
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = _b64url_decode(body_b64)
        sig = _b64url_decode(sig_b64)
    except Exception:  # noqa: BLE001 - 格式非法视为无效
        return None
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    exp = payload.get(_EXP)
    if not isinstance(exp, int) or exp <= int(time.time()):
        return None
    return payload


def parse_principal_payload(payload: dict[str, Any]) -> dict[str, str]:
    """从已验证载荷提取 Principal 字段（缺失字段归一为空串）。"""
    return {
        "user_id": str(payload.get(_USER) or ""),
        "tenant_id": str(payload.get(_TENANT) or ""),
    }


__all__ = ["sign_token", "verify_token", "parse_principal_payload"]
