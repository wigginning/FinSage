"""Tests for the MCP serve launcher (ADR-0021).

Covers argument parsing + correct server selection without actually binding a
transport (``app.run`` is monkeypatched to a no-op so the test never blocks).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "serve_mcp.py"


def _load_module() -> object:
    spec = importlib.util.spec_from_file_location("serve_mcp_test", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeApp:
    def __init__(self, name: str) -> None:
        self.name = name
        self.last_transport: str | None = None

    def run(self, transport: str = "stdio") -> None:  # pragma: no cover - entry point
        self.last_transport = transport


class _FakeServer:
    def __init__(self, name: str) -> None:
        self.name = name
        self.app = _FakeApp(name)


def _patch_builders(m, called: dict) -> None:
    def _financial():
        called["server"] = "financial"
        return _FakeServer("financial")

    def _knowledge():
        called["server"] = "knowledge"
        return _FakeServer("knowledge")

    def _search():
        called["server"] = "search"
        return _FakeServer("search")

    # 捕获 search server 的 transport，验证透传。
    _search_server = _FakeServer("search")
    real_run = _search_server.app.run

    def _search_run(transport: str = "stdio") -> None:
        called["transport"] = transport
        return real_run(transport)

    _search_server.app.run = _search_run  # type: ignore[assignment]

    def _search_capture():
        called["server"] = "search"
        return _search_server

    m.build_financial_server = _financial  # type: ignore[attr-defined]
    m.build_knowledge_server = _knowledge  # type: ignore[attr-defined]
    m.build_search_server = _search_capture  # type: ignore[attr-defined]


def test_serve_financial_runs(monkeypatch) -> None:  # noqa: ANN001
    m = _load_module()
    called: dict[str, str] = {}
    _patch_builders(m, called)
    monkeypatch.setattr(sys, "argv", ["serve_mcp.py", "--server", "financial"])
    assert m.main() == 0
    assert called["server"] == "financial"


def test_serve_search_with_sse(monkeypatch) -> None:  # noqa: ANN001
    m = _load_module()
    called: dict[str, str] = {}
    _patch_builders(m, called)
    monkeypatch.setattr(
        sys, "argv", ["serve_mcp.py", "--server", "search", "--transport", "sse"]
    )
    assert m.main() == 0
    assert called["server"] == "search"
    assert called["transport"] == "sse"
