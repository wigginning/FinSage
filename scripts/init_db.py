"""数据库初始化脚本（T101）。

功能：
  1. 兜底建库：连接 MySQL 实例（不含库名），若 finsage 库不存在则按 utf8mb4_0900_ai_ci 创建；
  2. 建库后自动执行 alembic 迁移（upgrade head），使全部表与规格 §5 对齐。

用法（在项目根运行，依赖 .env 中的 FIN_DB_URL）：
    python scripts/init_db.py
    python scripts/init_db.py --skip-migrate   # 仅建库，不跑迁移
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from finsage.persistence.db import ensure_database  # noqa: E402

_IMG = "init_db"


def main() -> int:
    parser = argparse.ArgumentParser(description="FinSage 数据库初始化：建库并执行迁移")
    parser.add_argument("--skip-migrate", action="store_true", help="仅建库，不执行 alembic 迁移")
    args = parser.parse_args()

    ensure_database()
    print(f"[{_IMG}] 建库完成（utf8mb4_0900_ai_ci）。")

    if args.skip_migrate:
        return 0

    # 迁移依赖 alembic 配置（alembic.ini 的 sqlalchemy.url 来自 settings/FIN_DB_URL）
    print(f"[{_IMG}] 执行 alembic upgrade head ...")
    subprocess.run(["python", "-m", "alembic", "upgrade", "head"], cwd=PROJECT_ROOT, check=True)
    print(f"[{_IMG}] 迁移完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())