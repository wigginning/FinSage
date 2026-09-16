"""仓储基类（T104）。

- 通用 CRUD 泛型基类：get / list / add / delete；
- 明确纪律：任何仓储方法只返回『ORM 域对象』（Mapped model），跨层禁止裸 dict 传递（§4）；
- 分页/筛选仅做受控参数与白名单字段等值过滤，禁止拼接任意 SQL（安全：最小暴露面）；
- DB 读写均走 IO 埋点，便于定位。
"""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from finsage.observability.logger import io_point

M = TypeVar("M")


class BaseRepository:
    """通用仓储。子类设置 model 为目标 ORM 模型。"""

    # 具体仓储将 model 设为 SQLAlchemy ORM 类；其属性（如 .id）是动态的，
    # 用 Any 以允许 `.id` / `getattr(model, key)` 等反射式访问，避免误报。
    model: Any

    def __init__(self, session: Session, *, check_permissions: bool = True) -> None:
        self._session = session
        # 最小权限：默认开启权限范围过滤（由具体仓储重写 _scope 应用 tenant/owner 限制）。
        self.check_permissions = check_permissions

    def _scope(self, stmt: Select[Any]) -> Select[Any]:
        """权限范围钩子：具体仓储可重写以注入 tenant_id / owner 过滤（最小权限）。"""
        return stmt

    @io_point("persistence", "repo_get")
    def get(self, entity_id: str):
        """按主键取回域对象；不存在返回 None。"""
        stmt = self._scope(select(self.model).where(self.model.id == entity_id))
        return self._session.execute(stmt).scalars().first()

    @io_point("persistence", "repo_list")
    def list(self, *, limit: int = 100, offset: int = 0) -> list[Any]:
        """分页列出（默认最多 100 条，限制防失控查询）。"""
        stmt = self._scope(select(self.model)).limit(limit).offset(offset)
        return list(self._session.execute(stmt).scalars().all())

    @io_point("persistence", "repo_add")
    def add(self, obj: Any) -> Any:
        """将待持久化对象加入会话（提交由外层 session_scope 负责）。返回原对象。"""
        self._session.add(obj)
        return obj

    @io_point("persistence", "repo_delete")
    def delete(self, obj: Any) -> None:
        """从会话删除对象（提交由外层 session_scope 负责）。"""
        self._session.delete(obj)


class FilteredRepository(BaseRepository):
    """带安全筛选的仓储：仅允许 allow_filters 白名单内的字段做等值过滤，防注入。"""

    allow_filters: frozenset[str] = frozenset()

    def filter(self, **filters: Any) -> Select[Any]:
        """仅按白名单字段做等值过滤，返回未执行的 Select。"""
        if self.check_permissions:
            invalid = set(filters) - set(self.allow_filters)
            if invalid:
                raise ValueError(f"不允许的筛选字段: {sorted(invalid)}")
        stmt: Select[Any] = select(self.model)
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        return self._scope(stmt)

    def find_one(self, **filters: Any):
        """白名单等值筛选取首条（域对象或 None）。"""
        return self._session.execute(self.filter(**filters).limit(1)).scalars().first()

    def find_many(self, *, limit: int = 100, offset: int = 0, **filters: Any) -> list[Any]:
        """白名单等值筛选分页取列表。"""
        stmt = self.filter(**filters).limit(limit).offset(offset)
        return list(self._session.execute(stmt).scalars().all())


class TenantScopedRepository(FilteredRepository):
    """按租户隔离的仓储：所有查询自动附加 tenant_id 过滤（最小权限）。

    构造时注入当前租户 id；未注入则放开租户过滤（通常仅限系统级/管理用途）。
    实体必须含 tenant_id 列。
    """

    tenant_id_field = "tenant_id"

    def __init__(
        self,
        session: Session,
        *,
        check_permissions: bool = True,
        tenant_id: str | None = None,
    ) -> None:
        super().__init__(session, check_permissions=check_permissions)
        self._tenant_id = tenant_id

    def _scope(self, stmt: Select[Any]) -> Select[Any]:
        if self._tenant_id is not None:
            stmt = stmt.where(getattr(self.model, self.tenant_id_field) == self._tenant_id)
        return stmt
