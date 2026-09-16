"""数据库连接与会话工厂（T101）。

- 统一从 settings.db_url 创建同步 SQLAlchemy engine（FROZEN: MySQL 8 + pymysql）；
- SessionLocal 会话工厂：disable autoflush、expire_on_commit=False；
- ensure_database：应用启动/开发时连接实例（不带库名）自动建库 finsage（utf8mb4_0900_ai_ci，
  规格 §5.1）；容器内建库由 docker-compose 的 MYSQL_DATABASE 完成，本函数仅作兜底。
- 所有节点 IO 埋点（见 observability.logger.io_point）。
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from finsage.observability.logger import get_logger, io_point
from finsage.settings import Settings, get_settings

logger = get_logger(__name__)

_DATABASE_CHARSET = "utf8mb4"
_DATABASE_COLLATE = "utf8mb4_0900_ai_ci"  # 规格 §5.1 冻结


@io_point("persistence", "create_engine")
def create_db_engine(settings: Settings | None = None, *, url: str | URL | None = None) -> Engine:
    """按配置创建数据库引擎（含连接池健康探测）。

    可传 `url`（str 或 URL 对象）覆盖 settings.db_url。
    注意：SQLAlchemy 的 ``str(URL)`` 会把口令渲染为 ``***``，凡需保留真实口令的
    server/无库连接必须传 URL 对象而非其字符串序列化，否则口令会丢失。
    """
    settings = settings or get_settings()
    target = url if url is not None else settings.db_url
    engine: Engine = create_engine(
        target,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=10,
        max_overflow=20,
        echo=False,
        future=True,
    )
    return engine


def _server_url(db_url: str) -> URL:
    """去掉路径中的库名，得到连接 MySQL 实例（不含数据库）的 URL，用于建库。"""
    url = make_url(db_url)
    return url.set(database="")


@io_point("persistence", "ensure_database")
def ensure_database(settings: Settings | None = None) -> None:
    """兜底建库：若 finsage 库不存在则自动创建（utf8mb4 / utf8mb4_0900_ai_ci）。

    注：建库需要足够权限（本地开发用 root 或具 CREATE DATABASE 的用户）；
    生产/容器初始化建议由 docker-compose 的 MYSQL_DATABASE 负责，避免强依赖本函数。
    """
    settings = settings or get_settings()
    url = make_url(settings.db_url)
    database = url.database or "finsage"
    server = create_db_engine(url=_server_url(settings.db_url))
    try:
        with server.connect() as conn, conn.begin():
            stmt = (
                f"CREATE DATABASE IF NOT EXISTS `{database}` "
                f"CHARACTER SET {_DATABASE_CHARSET} COLLATE {_DATABASE_COLLATE}"
            )
            conn.execute(text(stmt))
    finally:
        server.dispose()


def build_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """构建会话工厂；默认绑定全局引擎。"""
    return sessionmaker(bind=engine or get_engine(), autoflush=False, expire_on_commit=False)


class _EngineHolder:
    """惰性单例持有 engine 与 SessionLocal。"""

    def __init__(self) -> None:
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = create_db_engine()
        return self._engine

    def session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is None:
            self._session_factory = build_session_factory(self.engine())
        return self._session_factory


_holder = _EngineHolder()


def get_engine() -> Engine:
    """全局 engine 单例。"""
    return _holder.engine()


def get_session_factory() -> sessionmaker[Session]:
    """全局会话工厂单例。"""
    return _holder.session_factory()


@io_point("persistence", "session_scope")
@contextmanager
def session_scope() -> Iterator[Session]:
    """会话上下文：成功提交，异常回滚；配合 IO 埋点便于定位。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def close_engine() -> None:
    """释放全局 engine 连接池（测试/进程退出时调用）。"""
    if _holder._engine is not None:
        _holder._engine.dispose()
        _holder._engine = None
        _holder._session_factory = None