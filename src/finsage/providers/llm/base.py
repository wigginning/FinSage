"""LLM Provider 契约（m06 T609a —— 可插拔 stub，真实接入点预留）。

规格未冻结具体 LLM 厂商；本包只定义调用契约，节点经注入的 ``LLMProvider``
调用，不在节点内硬编码厂商 SDK（AGENTS.md §4 精神：数据访问走 Provider 抽象）。

契约保持最小：``complete`` 给定 system+prompt，返回确定性可解释的文本。真实实现
（如接到 OpenAI/Anthropic）需要时再落地，本阶段保证测试可跑（见 ``dummy``）。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class LLMProvider(Protocol):
    """LLM 文本生成契约（stub）。"""

    name: str

    def complete(self, *, system: str, prompt: str) -> str:
        """给定系统提示与用户提示，返回补全文本。"""

    def complete_structured(self, *, system: str, prompt: str) -> str:
        """结构化输出补全（返回 JSON 文本，由调用方解析）。"""

    def complete_typed(self, *, system: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
        """结构化输出：返回 schema 绑定的 Pydantic 实例；解析/校验失败抛异常（ADR-0012）。"""


__all__ = ["LLMProvider"]