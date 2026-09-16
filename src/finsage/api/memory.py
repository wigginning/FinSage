"""会话记忆管线（P0 —— §2.4 Memory 接线；上下文压缩见 ADR-0023）。

把既有但从未被消费的 ``sessions`` / ``messages`` 模型接线到对话流程：
- ``SessionMemory`` 契约：``append`` 落库用户/助手消息，``history`` 按会话取历史；
- MySQL 实现经 ``MessageRepository`` / ``SessionRepository``（TenantScopedRepository，
  自动按租户隔离）；未启用持久化时回退内存实现（诚实：进程内，重启即失）。

上下文窗口三层预算（ADR-0023）：
1. 条数上限 ``memory_history_limit``；
2. token 预算 ``memory_token_budget``（粗估 ~2 字符/token）；
3. **溢出摘要**：预算外的旧消息压缩为一条 ``system`` 摘要置于最前（需开
   ``memory_summary_enabled`` 且注入 ``ContextSummarizer``）。摘要器缺失/失败一律
   回退"丢弃最旧"——**绝不**用模板伪造摘要（AGENTS.md §10：假记忆比失忆更有害）。

工作流侧：runner 在调用图前加载 ``session_id`` 历史注入 ``init_state["chat_history"]``，
answer/claim 节点据此让 LLM 拿到上下文（跨轮续聊），不再把 ``session_id`` 当摆设。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol

from finsage.observability.logger import get_logger
from finsage.persistence.repositories.chat import MessageRepository
from finsage.settings import get_settings

logger = get_logger(__name__)

# 上下文窗口：单次注入助手的历史消息上限（防无限增长）。
_DEFAULT_HISTORY_LIMIT = 20

# 摘要消息的角色与前缀（下游节点无需特殊处理即可看到）。
_SUMMARY_ROLE = "system"
_SUMMARY_PREFIX = "早前对话摘要："

# 摘要提示词：只允许概括已出现内容，禁止推断/补充（防编造上下文）。
_SUMMARY_SYSTEM = (
    "你是对话摘要助手。请把给定的历史对话压缩为简洁摘要，"
    "只概括其中**已出现**的事实、用户诉求与已确认的结论。"
    "严禁推断、严禁补充未出现的信息、严禁给出新的结论或建议。"
    "若历史内容不足以形成摘要，直接返回空字符串。"
)


def _estimate_tokens(text: str) -> int:
    """粗估 token 数：中文约 1.5 字/token、英文约 4 字符/token，折中按 ~2 字符/token。

    仅用于上下文窗口预算控制，不作为计费/精确统计依据。
    """
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 2))


# ---- 第三层：溢出摘要（ADR-0023）----


class ContextSummarizer(Protocol):
    """溢出消息压缩契约（同步；I/O 由调用方 ``to_thread`` 包裹）。

    返回空串表示"无法摘要"，调用方据此回退到丢弃最旧。
    """

    def summarize(self, messages: list[dict[str, str]]) -> str: ...


@dataclass
class LLMContextSummarizer:
    """经注入的 ``LLMProvider`` 压缩溢出消息。

    失败（provider 抛错 / 返回空）时返回空串，由 ``_compress`` 回退丢弃最旧——
    不做任何模板兜底，避免把编造的"记忆"喂给模型。
    """

    provider: Any
    max_chars: int = 800

    def summarize(self, messages: list[dict[str, str]]) -> str:
        if not messages:
            return ""
        transcript = "\n".join(
            f"{m.get('role', '')}: {m.get('content', '')}" for m in messages
        )
        try:
            text = self.provider.complete(system=_SUMMARY_SYSTEM, prompt=transcript)
        except Exception as exc:  # noqa: BLE001 —— 摘要失败不得影响主链路
            logger.warning(
                "memory.summary_failed",
                extra={"extra": {"error": type(exc).__name__, "messages": len(messages)}},
            )
            return ""
        text = (text or "").strip()
        return text[: self.max_chars]


def _split_by_budget(
    messages: list[dict[str, str]], budget: int
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """从最新一端向前累加到预算上限，返回 ``(溢出的旧消息, 保留的近期消息)``。

    与旧实现的差异只在于"溢出部分被返回而非丢掉"，保留窗口的选取规则完全一致。
    """
    kept: list[dict[str, str]] = []
    used = 0
    for message in reversed(messages):
        cost = _estimate_tokens(message.get("content", ""))
        if kept and used + cost > budget:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    overflow = messages[: len(messages) - len(kept)]
    return overflow, kept


def _compress(
    messages: list[dict[str, str]],
    budget: int,
    *,
    summarizer: ContextSummarizer | None = None,
    summary_max_chars: int = 800,
) -> list[dict[str, str]]:
    """按 token 预算裁剪历史；有摘要器时把溢出部分压缩为一条 system 摘要。

    - 总量在预算内：原样返回；
    - 超预算且无摘要器（或摘要为空/失败）：丢弃最旧（既有行为）；
    - 超预算且摘要可用：``[system 摘要] + 近期消息``，摘要也计入预算
      （必要时再从近期一端腾出空间，保证注入总量始终受控）。
    """
    total = sum(_estimate_tokens(m.get("content", "")) for m in messages)
    if total <= budget:
        return messages

    overflow, kept = _split_by_budget(messages, budget)
    if not overflow or summarizer is None:
        return kept

    # 摘要是**增强**而非必需：任何注入实现抛错都不得穿透到主链路
    # （LLMContextSummarizer 自己已兜一层，这里对任意第三方实现再兜一层）。
    try:
        summary = summarizer.summarize(overflow)
    except Exception as exc:  # noqa: BLE001 —— 摘要失败即降级为丢弃最旧
        logger.warning(
            "memory.summarizer_error",
            extra={"extra": {"error": type(exc).__name__, "overflow": len(overflow)}},
        )
        return kept
    if not summary:
        return kept  # 诚实回退：没有真实摘要就不造一个

    summary_text = f"{_SUMMARY_PREFIX}{summary[:summary_max_chars]}"
    summary_cost = _estimate_tokens(summary_text)
    # 摘要占预算：从近期一端最旧处腾空间，直到总量回到预算内。
    while kept and summary_cost + sum(
        _estimate_tokens(m.get("content", "")) for m in kept
    ) > budget:
        kept.pop(0)
    return [{"role": _SUMMARY_ROLE, "content": summary_text}, *kept]


def _resolve_budget(token_budget: int | None) -> int:
    return token_budget if token_budget is not None else get_settings().memory_token_budget


class SessionMemory(Protocol):
    """会话记忆契约（可注入替身）。"""

    def append(
        self, session_id: str, role: str, content: str, *, tenant_id: str = ""
    ) -> None: ...
    def history(
        self,
        session_id: str,
        *,
        limit: int = _DEFAULT_HISTORY_LIMIT,
        token_budget: int | None = None,
    ) -> list[dict[str, str]]: ...


@dataclass
class InMemorySessionMemory:
    """进程内会话记忆（开发/未启用持久化时使用；重启即失）。"""

    summarizer: ContextSummarizer | None = None
    summary_max_chars: int = 800
    _store: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def append(
        self, session_id: str, role: str, content: str, *, tenant_id: str = ""
    ) -> None:
        self._store.setdefault(session_id, []).append({"role": role, "content": content})

    def history(
        self,
        session_id: str,
        *,
        limit: int = _DEFAULT_HISTORY_LIMIT,
        token_budget: int | None = None,
    ) -> list[dict[str, str]]:
        messages = list(self._store.get(session_id, []))[-limit:]
        return _compress(
            messages,
            _resolve_budget(token_budget),
            summarizer=self.summarizer,
            summary_max_chars=self.summary_max_chars,
        )


class MySQLSessionMemory:
    """MySQL 会话记忆：messages / sessions 落库（TenantScoped 隔离）。"""

    def __init__(
        self,
        *,
        summarizer: ContextSummarizer | None = None,
        summary_max_chars: int = 800,
    ) -> None:
        from finsage.persistence.db import session_scope

        self._session_scope = session_scope
        self.summarizer = summarizer
        self.summary_max_chars = summary_max_chars

    def append(self, session_id: str, role: str, content: str, *, tenant_id: str = "") -> None:
        from finsage.persistence.models.chat import Message

        with self._session_scope() as session:
            session.add(Message(session_id=session_id, role=role, content=content))

    def history(
        self,
        session_id: str,
        *,
        limit: int = _DEFAULT_HISTORY_LIMIT,
        token_budget: int | None = None,
    ) -> list[dict[str, str]]:
        """取会话**最近** limit 条（时间正序）并按预算压缩。

        ADR-0023 修正：原用 ``list_for_session``（升序 + LIMIT）取到的是最旧 N 条，
        长会话里近期上下文永远进不了窗口；改用 ``list_recent_for_session``。
        """
        with self._session_scope() as session:
            repo = MessageRepository(session)
            rows = repo.list_recent_for_session(session_id, limit=limit)
            messages = [
                {"role": getattr(r, "role", ""), "content": getattr(r, "content", "")}
                for r in rows
            ]
        return _compress(
            messages,
            _resolve_budget(token_budget),
            summarizer=self.summarizer,
            summary_max_chars=self.summary_max_chars,
        )


def build_context_summarizer(settings: Any = None, *, llm_provider: Any = None) -> Any:
    """按配置构造摘要器（ADR-0023）；关闭或无 provider 时返回 ``None``。

    返回 ``None`` 表示"无摘要能力"，``_compress`` 据此回退丢弃最旧（诚实降级）。
    """
    s = settings or get_settings()
    if not getattr(s, "memory_summary_enabled", False):
        return None
    provider = llm_provider
    if provider is None:
        try:
            from finsage.providers.llm import build_llm_provider

            provider = build_llm_provider(s)
        except Exception as exc:  # noqa: BLE001 —— LLM 装配失败不阻塞记忆链路
            logger.warning(
                "memory.summarizer_unavailable", extra={"extra": {"error": type(exc).__name__}}
            )
            return None
    return LLMContextSummarizer(
        provider=provider, max_chars=getattr(s, "memory_summary_max_chars", 800)
    )


def build_session_memory(
    *, persistence_enabled: bool, summarizer: ContextSummarizer | None = None
) -> SessionMemory:
    """按持久化开关选择会话记忆实现（MySQL 落库 vs 内存）。

    ``summarizer`` 未注入时按配置尝试构造（``memory_summary_enabled`` 关闭则为 None）。
    """
    if summarizer is None:
        summarizer = build_context_summarizer()
    max_chars = get_settings().memory_summary_max_chars
    if persistence_enabled:
        return MySQLSessionMemory(summarizer=summarizer, summary_max_chars=max_chars)
    return InMemorySessionMemory(summarizer=summarizer, summary_max_chars=max_chars)


__all__ = [
    "SessionMemory",
    "ContextSummarizer",
    "LLMContextSummarizer",
    "InMemorySessionMemory",
    "MySQLSessionMemory",
    "build_context_summarizer",
    "build_session_memory",
    "_DEFAULT_HISTORY_LIMIT",
]
