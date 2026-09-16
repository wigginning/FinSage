"""MCP server 启动脚本（ADR-0021）。

三个 MCP server 作为**外部工具面**以独立进程对外提供（供 MCP 客户端 / Agent 工具调用），
**不替换** graph 节点内部的 Milvus 直连检索（冻结架构，见 ADR-0021）。

用法（项目根运行；依赖 .env 或环境变量使对应 server 的运行时依赖就绪）：

    python scripts/serve_mcp.py --server financial
    python scripts/serve_mcp.py --server knowledge --transport sse
    python scripts/serve_mcp.py --server search

运行时依赖：
- financial : Provider SDK（akshare/efinance/pytdx/tushare 按需）
- knowledge : Milvus + BGE-M3 编码 + BGE-Reranker（m02 检索层）
- search    : 免费多引擎回退（仅出站 HTTP）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from finsage.mcp import (  # noqa: E402
    build_financial_server,
    build_knowledge_server,
    build_search_server,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve a FinSage MCP server")
    parser.add_argument(
        "--server", required=True, choices=["financial", "knowledge", "search"],
        help="要启动的 MCP server",
    )
    parser.add_argument(
        "--transport", default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="传输方式（默认 stdio）",
    )
    args = parser.parse_args()

    if args.server == "financial":
        server = build_financial_server()
    elif args.server == "knowledge":
        server = build_knowledge_server()
    else:
        server = build_search_server()

    # app.run 阻塞运行直到进程退出（Ctrl-C / SIGTERM）。
    server.app.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
