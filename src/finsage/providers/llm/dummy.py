"""确定性 Dummy LLM（m06 T609a —— 可插拔 stub 的默认实现）。

实际项目接入真实 LLM 前，节点经该实现跑通确定性路径：输出完全由输入推导，
无外部调用，供单元/工作流测试稳定运行。真实实现落地后替换注入即可。
"""
from __future__ import annotations

from pydantic import BaseModel

from finsage.observability.logger import get_logger

logger = get_logger(__name__)


class DummyLLMProvider:
    """确定性 dummy LLM：回显关键输入，保证可测且零外部依赖。"""

    name = "dummy"

    def complete(self, *, system: str, prompt: str) -> str:
        logger.info("llm.complete", extra={"extra": {"system": system[:60], "prompt": prompt[:60]}})
        return f"[dummy] {system} :: {prompt}"

    def complete_structured(self, *, system: str, prompt: str) -> str:
        return self.complete(system=system, prompt=prompt)

    def complete_typed(self, *, system: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
        """确定性 dummy 无法产出结构化输出，诚实抛错（ADR-0012），由调用方回退确定性推导。"""
        raise NotImplementedError("DummyLLMProvider 不支持结构化输出")


__all__ = ["DummyLLMProvider"]