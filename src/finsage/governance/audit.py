"""Audit 事件构建与持久化抽象（§16.15 / §25 —— 确定性，secret 永不入 audit）。

``AuditSink`` 为可注入容器接口；默认 ``InMemoryAuditSink`` 便于工作流测试零外部依赖。
审计字段对齐 §25（trace_id/request_id/stage/actor/status/error_code/timestamp/摘要）。
入参出参摘要一律经 mask_value 脱敏（AGENTS.md §7）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from finsage.observability.logger import mask_value

# status 取值与 §16 阶段语义。
AuditStatus = str  # "success" | "error" | "timeout" | "skipped"


@dataclass
class AuditEntry:
    """单条审计记录（§25 字段对齐）。"""

    trace_id: str
    request_id: str
    stage: str
    actor: str
    status: str
    input_summary: Any = None
    output_summary: Any = None
    error_code: str | None = None
    latency_ms: int | None = None
    warnings: list[str] = field(default_factory=list)
    timestamp: str = ""  # ISO UTC，生成时填充
    model: str | None = None
    tool: str | None = None
    provider: str | None = None


class AuditSink(Protocol):
    """审计写入契约。"""

    def record(self, entry: AuditEntry) -> None: ...


def build_entry(
    *,
    state: dict,
    stage: str,
    actor: str,
    status: str,
    input_summary: Any = None,
    output_summary: Any = None,
    error_code: str | None = None,
    latency_ms: int | None = None,
    model: str | None = None,
    tool: str | None = None,
    provider: str | None = None,
) -> AuditEntry:
    """由 state + 阶段信息构建 AuditEntry，入参出参自动脱敏。"""
    return AuditEntry(
        trace_id=state.get("trace_id", ""),
        request_id=state.get("request_id", ""),
        stage=stage,
        actor=actor,
        status=status,
        input_summary=mask_value(input_summary),
        output_summary=mask_value(output_summary),
        error_code=error_code,
        latency_ms=latency_ms,
        warnings=list(state.get("warnings", []) or []),
        model=model,
        tool=tool,
        provider=provider,
    )


class InMemoryAuditSink:
    """内存审计容器（测试默认）。"""

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


class PersistentAuditWriter:
    """持久化 Audit writer（§25 全字段，T708）。

    把 ``AuditEntry`` 映射为 m01 ``audit_events`` 的 ORM ``AuditEvent``，经
    ``AuditEventRepository.add`` 入会话（提交由外层 session_scope 负责）。
    入参出参已由 build_entry 脱敏；此处不再触碰敏感字段（secret 永不入库）。
    """

    def __init__(self, repo: Any, *, tenant_id: str | None = None) -> None:
        self._repo = repo
        self._tenant_id = tenant_id

    def record(self, entry: AuditEntry) -> None:
        event = self._repo.model(
            tenant_id=self._tenant_id,
            trace_id=entry.trace_id,
            request_id=entry.request_id,
            stage=entry.stage,
            actor=entry.actor,
            model=entry.model,
            tool=entry.tool,
            provider=entry.provider,
            input_json=entry.input_summary,
            output_json=entry.output_summary,
            latency_ms=entry.latency_ms,
            status=entry.status,
            error_code=entry.error_code,
        )
        if entry.timestamp:
            event.timestamp = entry.timestamp
        self._repo.add(event)


class _Timer:
    """轻量耗时记录（毫秒）。"""

    def __init__(self) -> None:
        self._start = time.monotonic()

    def ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)


__all__ = [
    "AuditEntry",
    "AuditSink",
    "InMemoryAuditSink",
    "PersistentAuditWriter",
    "build_entry",
    "_Timer",
]