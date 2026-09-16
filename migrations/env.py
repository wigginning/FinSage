"""Alembic 迁移环境（T102）。

- 注入数据库 URL：优先取 settings（FIN_DB_URL / .env），再回落到 alembic.ini 的 sqlalchemy.url；
- target_metadata 绑定全部 ORM 模型的 Base.metadata（导入 models 包即注册 19 张表，与 §5 一致）；
- 迁移文件由 scripts/gen_migrations.py 离线生成，保证逐列与模型一致。
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# 保证 import finsage.* 可用（即使未安装为包，也能从 src 加载）。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from finsage.persistence import models as _models_module  # noqa: E402,F401  # 注册全部表
from finsage.persistence.base import Base  # noqa: E402
from finsage.settings import get_settings  # noqa: E402

# 显式引用以便 lint 识别用途（导入 models 的目的是让 Base.metadata 汇聚 19 张表）。
_ = _models_module

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# 用应用配置覆盖数据库 URL（不允许在 alembic.ini 里写死连接串/密文）。
target_metadata = Base.metadata
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().db_url)


def run_migrations_offline() -> None:
    """离线模式：仅依据 URL 生成 SQL，不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=False,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()