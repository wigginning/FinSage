"""账号开通脚本（ADR-0019 §4 的运营依赖）。

登录端点只做"凭据 → 令牌"，**不提供开放注册**；本脚本由管理员使用，创建（或重置）
用户、确保其归属到指定租户并赋予角色，使账号可被 ``POST /api/v1/auth/login`` 使用。

前置条件：数据库已初始化（表结构由 alembic 迁移创建）。建议先跑一次：

    python scripts/init_db.py

用法（在项目根运行，依赖 .env 中的 FIN_DB_URL）：

    # 交互式输入口令（推荐，避免口令出现在进程列表/历史）
    python scripts/create_user.py --email alice@corp.com --tenant acme --role admin

    # 非交互（管道/自动化）：从 stdin 读取口令
    echo "s3cret-pass" | python scripts/create_user.py -e alice@corp.com -t acme -r member

    # 重置既有账号口令与角色
    python scripts/create_user.py -e alice@corp.com -t acme -r member --reset-password

退出码：0 成功；1 参数/校验错误；2 数据库写入失败。
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from finsage.persistence.db import session_scope  # noqa: E402
from finsage.provisioning import VALID_ROLES, ProvisionError, provision_user  # noqa: E402

_IMG = "create_user"


def _read_password(*, explicit: str | None) -> str:
    """取口令：优先显式参数；TTY 用 getpass 隐藏输入；否则读 stdin 一行。"""
    if explicit is not None:
        return explicit
    if sys.stdin.isatty():
        return getpass.getpass("Password: ")
    return sys.stdin.readline().rstrip("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="FinSage 账号开通：创建/重置用户、绑定租户并赋角色"
    )
    parser.add_argument("-e", "--email", required=True, help="用户邮箱（唯一标识）")
    parser.add_argument("-t", "--tenant", required=True, help="归属租户名（不存在则创建）")
    parser.add_argument(
        "-r",
        "--role",
        default="member",
        choices=VALID_ROLES,
        help="在该租户内的角色（默认 member）",
    )
    parser.add_argument("-n", "--display-name", default=None, help="显示名（默认取邮箱前缀）")
    parser.add_argument(
        "-p",
        "--password",
        default=None,
        help="口令（不安全，会进入进程列表/历史）；省略则从 stdin/TTY 读取",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="若用户已存在，重置其口令并覆盖角色（默认拒绝覆盖既有账号）",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    password = _read_password(explicit=args.password)
    if not password:
        print(f"[{_IMG}] 错误：口令为空。", file=sys.stderr)
        return 1

    try:
        with session_scope() as session:
            result = provision_user(
                session,
                email=args.email,
                password=password,
                tenant_name=args.tenant,
                role=args.role,
                display_name=args.display_name,
                reset_password=args.reset_password,
            )
    except ProvisionError as exc:
        print(f"[{_IMG}] 校验失败：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # 数据库不可用、约束冲突等
        print(f"[{_IMG}] 开通失败：{exc}", file=sys.stderr)
        return 2

    print(
        f"[{_IMG}] 开通完成：user_id={result.user_id} "
        f"tenant={result.tenant_name}({result.tenant_id}) role={result.role} "
        f"created_user={result.created_user} created_tenant={result.created_tenant} "
        f"created_membership={result.created_membership}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
