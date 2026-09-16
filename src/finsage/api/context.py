"""请求身份上下文（m08，§7 / §5.3–5.6 —— P0 权限数据面基础）。

``Principal`` 描述当前已认证身份：``user_id`` 与 ``tenant_id``（来自
users / user_tenants / sessions 模型）。所有需要最小权限的接口都应解析出
``Principal`` 并经 request.state 向下透传，仓储/检索层据此强制租户过滤。

设计要点：
- ``user_id``/``tenant_id`` 为空表示未识别身份（如开发放行或系统调用）；
- 对外不暴露敏感信息；本模块仅承载身份语义与判定，不触碰凭据校验
  （校验见 ``finsage.api.auth``）。
- 遵循 AGENTS.md §2：不臆造接口 —— 所有字段与 users/tenants/user_tenants
  模型对齐，判定逻辑有单测覆盖。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 未识别身份 / 开发放行时的占位（与既有仓储缺省一致，见 mysql_stores）。
_ANONYMOUS_USER = ""
_ANONYMOUS_TENANT = ""


@dataclass(frozen=True)
class Principal:
    """已认证身份的不可变描述。"""

    user_id: str = _ANONYMOUS_USER
    tenant_id: str = _ANONYMOUS_TENANT
    roles: frozenset[str] = field(default_factory=frozenset)

    @property
    def authenticated(self) -> bool:
        """是否携带可识别的用户身份。"""
        return bool(self.user_id)

    @property
    def tenant_scoped(self) -> bool:
        """是否携带租户作用域（用于强制租户隔离）。"""
        return bool(self.tenant_id)

    def require_tenant(self) -> str:
        """取租户 id；无租户作用域时返回空串（由调用方决定是否放行）。"""
        return self.tenant_id

    def to_context(self) -> dict[str, Any]:
        """把身份信息映射为可透传到仓储/检索的上下文（最小字段集）。"""
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
        }


ANONYMOUS = Principal()


__all__ = ["Principal", "ANONYMOUS"]
