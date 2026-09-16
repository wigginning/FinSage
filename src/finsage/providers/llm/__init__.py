"""LLM Provider（m06 stub：契约 + 确定性 dummy + OpenAI 兼容真实实现）。

``build_llm_provider`` 依据 settings 路由：已配置 api_key/base_url/model → 返回
OpenAI 兼容真实 Provider；否则回落确定性 Dummy。节点经注入的 ``LLMProvider``
调用，不在节点内硬编码厂商 SDK（AGENTS.md §4 精神）。
"""
from __future__ import annotations

from finsage.settings import Settings

from .base import LLMProvider
from .dummy import DummyLLMProvider
from .openai_compat import OpenAICompatibleLLMProvider
from .registry import LLMProviderRegistry

__all__ = [
    "LLMProvider",
    "DummyLLMProvider",
    "OpenAICompatibleLLMProvider",
    "LLMProviderRegistry",
    "build_llm_provider",
    "build_llm_registry",
]


def build_llm_provider(settings: Settings | None = None) -> LLMProvider:
    """按配置解析 LLM Provider：有凭据走真实 OpenAI 兼容，否则回退 Dummy。"""
    s = settings or Settings()
    if s.llm_api_key and s.llm_base_url and s.llm_model:
        return OpenAICompatibleLLMProvider(
            api_key=s.llm_api_key,
            base_url=s.llm_base_url,
            model=s.llm_model,
            timeout=s.llm_timeout,
        )
    return DummyLLMProvider()


def build_llm_registry(settings: Settings | None = None) -> LLMProviderRegistry:
    """构建命名 LLM 注册表（ADR-0014）。

    - ``default``：``build_llm_provider`` 结果（真实或 Dummy）；
    - ``adversarial``：独立模型家族（仅当对抗凭据齐全时注册，否则缺省）。
    """
    s = settings or Settings()
    registry = LLMProviderRegistry()
    registry.register("default", build_llm_provider(s))
    if s.llm_adversarial_api_key and s.llm_adversarial_base_url and s.llm_adversarial_model:
        registry.register(
            "adversarial",
            OpenAICompatibleLLMProvider(
                api_key=s.llm_adversarial_api_key,
                base_url=s.llm_adversarial_base_url,
                model=s.llm_adversarial_model,
                timeout=s.llm_timeout,
            ),
        )
    return registry