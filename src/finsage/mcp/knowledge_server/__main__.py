"""``python -m finsage.mcp.knowledge_server`` 入口（ADR-0021）。"""
from __future__ import annotations

from finsage.mcp.knowledge_server import KnowledgeMCPServer

if __name__ == "__main__":
    KnowledgeMCPServer().serve()
