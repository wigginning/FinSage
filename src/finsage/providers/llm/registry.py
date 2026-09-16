"""LLM Provider 注册表（ADR-0014）。

名称 → ``LLMProvider`` 的薄容器，支持按名路由（如 ``default`` 建设性视角 /
``adversarial`` 对抗视角，实现 ADR-0009 的跨模型家族隔离）。不引入新协议，
仅承载已实现 ``LLMProvider`` 契约的实例。
"""
from __future__ import annotations

from .base import LLMProvider

__all__ = ["LLMProviderRegistry"]


class LLMProviderRegistry:
    """按名称路由的 LLM Provider 容器。"""

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}

    def register(self, name: str, provider: LLMProvider) -> None:
        """注册（或覆盖）一个命名 provider。"""
        self._providers[name] = provider

    def get(self, name: str) -> LLMProvider:
        """按名取 provider；未注册抛 ``KeyError``。"""
        return self._providers[name]

    def get_or_none(self, name: str) -> LLMProvider | None:
        """按名取 provider；未注册返回 ``None``。"""
        return self._providers.get(name)

    def names(self) -> list[str]:
        """已注册的 provider 名称（插入序）。"""
        return list(self._providers)
