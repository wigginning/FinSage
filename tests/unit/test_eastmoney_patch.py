"""eastmoney_patch 契约测试（opt-in 东财反爬补丁）。

验证：
- apply_eastmoney_patch 幂等；
- 补丁仅对东财域名生效，其它请求原样透传；
- Provider 仅在 enable_eastmoney_patch=True 时应用补丁。
"""

from __future__ import annotations

import requests

from finsage.providers.finance import AKShareProvider, EFinanceProvider
from finsage.providers.finance.eastmoney_patch import apply_eastmoney_patch, is_patched


def _reset_patch() -> None:
    """重置补丁全局状态，避免测试间相互污染。"""
    import finsage.providers.finance.eastmoney_patch as mod

    mod._patched = False
    mod._original_request = requests.Session.request


def test_apply_patch_is_idempotent() -> None:
    _reset_patch()
    try:
        assert apply_eastmoney_patch() is True  # 首次应用
        assert apply_eastmoney_patch() is False  # 幂等：再次调用不重复应用
        assert is_patched() is True
    finally:
        _reset_patch()


def test_patch_replaces_session_request() -> None:
    _reset_patch()
    try:
        original = requests.Session.request
        apply_eastmoney_patch()
        # 补丁应全局替换 requests.Session.request。
        assert requests.Session.request is not original
    finally:
        _reset_patch()


def test_provider_applies_patch_only_when_enabled() -> None:
    _reset_patch()
    try:
        # 默认不启用：不应用补丁
        EFinanceProvider()
        assert is_patched() is False
        AKShareProvider()
        assert is_patched() is False
        # 显式启用：应用补丁
        EFinanceProvider(enable_eastmoney_patch=True)
        assert is_patched() is True
    finally:
        _reset_patch()
