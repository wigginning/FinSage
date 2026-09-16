"""上下文窗口压缩测试（ADR-0023）：溢出摘要 + 诚实降级 + 最近 N 条修正。

覆盖：
- 预算内不压缩、无摘要器时保持"丢弃最旧"既有行为；
- 有摘要器时溢出压缩为一条 system 摘要且注入总量仍受预算约束；
- 摘要器失败 / 返回空 → 回退丢弃最旧（**不伪造摘要**）；
- ``build_context_summarizer`` 开关语义；
- ``MessageRepository.list_recent_for_session`` 取最近 N 条并还原时间正序（SQLite 内存库）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from finsage.api.memory import (
    InMemorySessionMemory,
    LLMContextSummarizer,
    build_context_summarizer,
    build_session_memory,
)
from finsage.settings import Settings

_SUMMARY_PREFIX = "早前对话摘要："


@dataclass
class FakeSummarizer:
    """记录被压缩的消息，返回固定摘要文本。"""

    text: str = "用户询问了三家公司的营收"
    seen: list[list[dict[str, str]]] = field(default_factory=list)

    def summarize(self, messages: list[dict[str, str]]) -> str:
        self.seen.append(list(messages))
        return self.text


class EmptySummarizer:
    """摘要不可用（返回空串）——应触发诚实回退。"""

    def summarize(self, messages: list[dict[str, str]]) -> str:
        return ""


class BoomSummarizer:
    """摘要器抛错——不得影响主链路。"""

    def summarize(self, messages: list[dict[str, str]]) -> str:
        raise RuntimeError("llm down")


def _fill(mem: InMemorySessionMemory, count: int, size: int = 1000) -> None:
    for i in range(count):
        mem.append("s1", "user", f"{i}" + "x" * (size - 1))


# ---- 无摘要器：既有行为不变 ----


def test_no_summarizer_keeps_drop_oldest():
    mem = InMemorySessionMemory()
    _fill(mem, 5)
    hist = mem.history("s1", limit=10, token_budget=1000)
    assert all(h["role"] == "user" for h in hist)  # 无 system 摘要
    assert len(hist) < 5
    assert hist[-1]["content"].startswith("4")  # 保留最新


def test_under_budget_is_untouched():
    mem = InMemorySessionMemory(summarizer=FakeSummarizer())
    mem.append("s1", "user", "短消息")
    mem.append("s1", "assistant", "短回答")
    hist = mem.history("s1", token_budget=1000)
    assert [h["role"] for h in hist] == ["user", "assistant"]


# ---- 有摘要器：溢出压缩 ----


def test_overflow_is_summarized_into_system_message():
    summarizer = FakeSummarizer()
    mem = InMemorySessionMemory(summarizer=summarizer)
    _fill(mem, 5)

    hist = mem.history("s1", limit=10, token_budget=1000)

    assert hist[0]["role"] == "system"
    assert hist[0]["content"].startswith(_SUMMARY_PREFIX)
    assert summarizer.text in hist[0]["content"]
    # 最新消息仍在窗口内。
    assert hist[-1]["content"].startswith("4")
    # 被摘要的正是溢出的旧消息（最旧的先进摘要）。
    assert summarizer.seen[0][0]["content"].startswith("0")


def test_summary_counts_against_budget():
    """摘要本身计入预算：注入总量不得超过 token_budget。"""
    summarizer = FakeSummarizer(text="摘" * 400)
    mem = InMemorySessionMemory(summarizer=summarizer, summary_max_chars=800)
    _fill(mem, 6, size=400)

    hist = mem.history("s1", limit=10, token_budget=500)

    total = sum(max(1, (len(h["content"]) + 1) // 2) for h in hist)
    assert total <= 500, [len(h["content"]) for h in hist]
    assert hist[0]["role"] == "system"


def test_summary_max_chars_truncates():
    mem = InMemorySessionMemory(summarizer=FakeSummarizer(text="长" * 5000), summary_max_chars=50)
    _fill(mem, 5)
    hist = mem.history("s1", limit=10, token_budget=2000)
    assert hist[0]["role"] == "system"
    assert len(hist[0]["content"]) <= len(_SUMMARY_PREFIX) + 50


# ---- 诚实降级 ----


def test_empty_summary_falls_back_to_drop_oldest():
    mem = InMemorySessionMemory(summarizer=EmptySummarizer())
    _fill(mem, 5)
    hist = mem.history("s1", limit=10, token_budget=1000)
    assert all(h["role"] == "user" for h in hist)  # 不造假摘要
    assert len(hist) < 5


def test_summarizer_exception_falls_back(caplog):
    """LLM 抛错时 LLMContextSummarizer 返回空串，链路降级但不崩。"""
    summarizer = LLMContextSummarizer(provider=_BoomProvider(), max_chars=100)
    assert summarizer.summarize([{"role": "user", "content": "x"}]) == ""

    mem = InMemorySessionMemory(summarizer=BoomSummarizer())
    _fill(mem, 5)
    try:
        hist = mem.history("s1", limit=10, token_budget=1000)
    except RuntimeError:  # pragma: no cover —— 摘要器异常必须由记忆层兜住
        raise AssertionError("summarizer exception must not escape history()") from None
    assert all(h["role"] == "user" for h in hist)


class _BoomProvider:
    def complete(self, *, system: str, prompt: str) -> str:
        raise RuntimeError("provider down")


def test_llm_summarizer_uses_provider_and_truncates():
    class Provider:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def complete(self, *, system: str, prompt: str) -> str:
            self.calls.append((system, prompt))
            return "摘要内容" * 100

    provider = Provider()
    summarizer = LLMContextSummarizer(provider=provider, max_chars=20)
    out = summarizer.summarize(
        [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "回答"}]
    )
    assert len(out) == 20
    # 提示词包含转录，且禁止推断的约束在 system 中。
    assert "问题" in provider.calls[0][1] and "回答" in provider.calls[0][1]
    assert "严禁推断" in provider.calls[0][0]


def test_llm_summarizer_empty_messages_short_circuits():
    summarizer = LLMContextSummarizer(provider=_BoomProvider())
    assert summarizer.summarize([]) == ""  # 未调用 provider，故不抛错


# ---- 开关语义 ----


def test_build_context_summarizer_disabled_by_default():
    assert build_context_summarizer(Settings()) is None


def test_build_context_summarizer_enabled_returns_summarizer():
    settings = Settings(memory_summary_enabled=True, memory_summary_max_chars=123)
    summarizer = build_context_summarizer(settings, llm_provider=_BoomProvider())
    assert isinstance(summarizer, LLMContextSummarizer)
    assert summarizer.max_chars == 123


def test_build_session_memory_without_summary_has_none():
    mem = build_session_memory(persistence_enabled=False)
    assert isinstance(mem, InMemorySessionMemory)
    assert mem.summarizer is None


def test_build_session_memory_accepts_injected_summarizer():
    summarizer = FakeSummarizer()
    mem = build_session_memory(persistence_enabled=False, summarizer=summarizer)
    assert mem.summarizer is summarizer


# ---- 仓储：最近 N 条（SQLite 内存库，不依赖 MySQL）----


def test_list_recent_for_session_returns_newest_in_chronological_order():
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from finsage.persistence.base import Base
    from finsage.persistence.models.chat import Message
    from finsage.persistence.repositories.chat import MessageRepository

    engine = create_engine("sqlite://")
    Message.__table__.create(engine)
    assert Base is not None  # 确保元数据已加载

    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as session:
        for i in range(10):
            session.add(
                Message(
                    session_id="s1",
                    role="user",
                    content=str(i),
                    created_at=base_time + timedelta(minutes=i),
                )
            )
        session.commit()

        repo = MessageRepository(session)
        recent = repo.list_recent_for_session("s1", limit=3)
        assert [m.content for m in recent] == ["7", "8", "9"]  # 最近 3 条，时间正序

        # 对照：升序分页取到的是最旧 3 条（原缺陷来源，语义保留）。
        oldest = repo.list_for_session("s1", limit=3)
        assert [m.content for m in oldest] == ["0", "1", "2"]
