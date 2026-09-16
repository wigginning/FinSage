"""MySQL 仓储纯函数测试（P1：重复上传同内容 500 修复）。

覆盖：``_document_id`` 按 (租户, 内容) 寻址 —— 同租户同内容稳定、跨租户互不冲突。
真实 MySQL 往返（幂等 register）由 tests/integration/test_mysql.py 覆盖。
"""

from __future__ import annotations

from finsage.api.mysql_stores import _document_id


def test_document_id_stable_for_same_tenant_and_content() -> None:
    """同租户同内容 → 相同 id（幂等去重的前提）。"""
    assert _document_id("t-a", "hash-1") == _document_id("t-a", "hash-1")


def test_document_id_distinct_across_tenants() -> None:
    """跨租户上传相同内容 → 不同 id（不再主键冲突）。"""
    assert _document_id("t-a", "hash-1") != _document_id("t-b", "hash-1")


def test_document_id_distinct_for_different_content() -> None:
    """同租户不同内容 → 不同 id。"""
    assert _document_id("t-a", "hash-1") != _document_id("t-a", "hash-2")


def test_document_id_is_36_chars() -> None:
    """id 保持 CHAR(36) 长度契约（与 IdMixin 一致）。"""
    assert len(_document_id("t-a", "hash-1")) == 36


def test_default_tenant_name_reads_from_settings(monkeypatch) -> None:
    """占位租户名不再硬编码字面量，统一从 settings.default_tenant 读取。"""
    from finsage.api import mysql_stores

    class _FakeSettings:
        default_tenant = "custom-tenant"

    monkeypatch.setattr(mysql_stores, "get_settings", lambda: _FakeSettings())
    assert mysql_stores._default_tenant_name() == "custom-tenant"
