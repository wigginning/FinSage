"""P0 认证升级：身份令牌签发/校验 与 Principal 解析测试（离线，不依赖 DB）。"""

from __future__ import annotations

import pytest

from finsage.api.context import ANONYMOUS, Principal
from finsage.api.identity_token import (
    parse_principal_payload,
    sign_token,
    verify_token,
)

_SECRET = "test-secret-key-123"


def test_sign_and_verify_roundtrip():
    token = sign_token(user_id="u1", tenant_id="t1", secret=_SECRET, roles=["admin"])
    payload = verify_token(token, secret=_SECRET)
    assert payload is not None
    assert payload["user_id"] == "u1"
    assert payload["tenant_id"] == "t1"
    assert payload["roles"] == ["admin"]
    assert "exp" in payload


def test_verify_wrong_secret_rejected():
    token = sign_token(user_id="u1", tenant_id="t1", secret=_SECRET)
    assert verify_token(token, secret="wrong-secret") is None


def test_verify_empty_secret_rejected():
    token = sign_token(user_id="u1", tenant_id="t1", secret=_SECRET)
    assert verify_token(token, secret="") is None


def test_verify_tampered_body_rejected():
    token = sign_token(user_id="u1", tenant_id="t1", secret=_SECRET)
    body_b64, sig = token.split(".", 1)
    # 篡改 user_id（保持 base64url 合法），签名不再匹配。
    import base64

    payload = {"user_id": "attacker", "tenant_id": "t1", "roles": [], "exp": 9999999999}
    forged = (
        base64.urlsafe_b64encode(
            __import__("json").dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )
        .rstrip(b"=")
        .decode()
    )
    assert verify_token(f"{forged}.{sig}", secret=_SECRET) is None


def test_verify_expired_token_rejected():
    token = sign_token(user_id="u1", tenant_id="t1", secret=_SECRET, ttl_seconds=-10)
    assert verify_token(token, secret=_SECRET) is None


def test_verify_garbage_rejected():
    assert verify_token("not-a-token", secret=_SECRET) is None
    assert verify_token("", secret=_SECRET) is None


def test_sign_empty_secret_raises():
    with pytest.raises(ValueError):
        sign_token(user_id="u1", tenant_id="t1", secret="")


def test_parse_principal_payload_normalizes_missing():
    fields = parse_principal_payload({"user_id": "u1", "tenant_id": ""})
    assert fields == {"user_id": "u1", "tenant_id": ""}
    fields = parse_principal_payload({})
    assert fields == {"user_id": "", "tenant_id": ""}


def test_principal_anonymous_and_tenant_scoped():
    assert ANONYMOUS.authenticated is False
    assert ANONYMOUS.tenant_scoped is False
    p = Principal(user_id="u1", tenant_id="t1", roles=frozenset({"admin"}))
    assert p.authenticated is True
    assert p.tenant_scoped is True
    assert p.require_tenant() == "t1"
    assert p.to_context() == {"user_id": "u1", "tenant_id": "t1"}
