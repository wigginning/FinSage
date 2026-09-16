"""``python -m finsage.mcp.financial_server`` 入口（ADR-0021）。"""
from __future__ import annotations

from finsage.mcp.financial_server import FinancialMCPServer

if __name__ == "__main__":
    FinancialMCPServer().serve()
