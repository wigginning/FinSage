"""``python -m finsage.mcp.search_server`` 入口（ADR-0021）。"""
from __future__ import annotations

from finsage.mcp.search_server import SearchMCPServer

if __name__ == "__main__":
    SearchMCPServer().serve()
