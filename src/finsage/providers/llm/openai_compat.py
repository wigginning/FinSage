"""OpenAI 兼容 LLM Provider（m06 T609a 真实接入落地）。

基于 ``httpx`` 调用 OpenAI 兼容 ``/chat/completions`` 端点（如阿里云 MaaS
compatible-mode 网关 = ``<base_url>/chat/completions``）。读取 settings 注入
api_key / base_url / model；仅在有凭据时经 ``build_llm_provider`` 启用。

纪律（AGENTS.md §3/§10）：
- 本 Provider 只做叙事/总结性文本生成（draft_answer 等），**绝不参与财务算术**；
- 未配置凭据时回落确定性 Dummy，保证工作流在无外部依赖下仍可测可跑；
- 错误映射为 FIN 错误码（workflow 层捕获，不外抛打断图）。
"""
from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from finsage.exceptions import (
    ProviderBadResponseError,
    ProviderTimeoutError,
)
from finsage.observability.logger import get_logger

logger = get_logger(__name__)


class OpenAICompatibleLLMProvider:
    """OpenAI 兼容 chat/completions 调用实现（可插拔 cc stub 的真实替代）。"""

    name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def _url(self) -> str:
        return f"{self._base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def complete(self, *, system: str, prompt: str) -> str:
        """给定 system + user 提示，返回补全文本（确定性可解释输出）。"""
        return self._chat(system=system, prompt=prompt, json_mode=False)

    def complete_structured(self, *, system: str, prompt: str) -> str:
        """结构化输出补全：请求 response_format=json_object，返回 JSON 文本。"""
        return self._chat(system=system, prompt=prompt, json_mode=True)

    def complete_typed(self, *, system: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
        """结构化输出：返回 schema 绑定的 Pydantic 实例（ADR-0012）。

        请求 JSON 模式，解析并校验为 ``schema`` 实例；解析/校验失败抛
        ``ProviderBadResponseError``，由调用方回退确定性推导。
        """
        text = self._chat(system=system, prompt=prompt, json_mode=True)
        try:
            return schema.model_validate_json(text)
        except (ValidationError, ValueError) as exc:
            logger.warning(
                "llm.typed_validation_failed",
                extra={"extra": {"model": self._model, "schema": schema.__name__}},
            )
            raise ProviderBadResponseError("LLM 结构化输出校验失败") from exc

    def _chat(self, *, system: str, prompt: str, json_mode: bool) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,  # 研究叙事重可复现，禁用随机
            # 关闭思考/推理模式（DeepSeek 系模型在阿里 MaaS 默认开启，会显著拉长耗时）。
            "enable_thinking": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        logger.info(
            "llm.complete",
            extra={
                "extra": {
                    "model": self._model,
                    "json_mode": json_mode,
                    "system": system[:60],
                    "prompt": prompt[:60],
                }
            },
        )
        try:
            resp = httpx.post(
                self._url(),
                headers=self._headers(),
                json=payload,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            logger.warning(
                "llm.timeout",
                extra={"extra": {"model": self._model, "error": str(exc)}},
            )
            raise ProviderTimeoutError("LLM 请求超时") from exc
        except httpx.HTTPError as exc:
            logger.warning("llm.http_error", extra={"extra": {"error": str(exc)}})
            raise ProviderBadResponseError("LLM 请求失败") from exc

        if resp.status_code != 200:
            # 不把上游消息细节暴露；只记日志便于定位（绝不打印完整 key）。
            logger.error(
                "llm.non_200",
                extra={"extra": {"model": self._model, "status": resp.status_code}},
            )
            raise ProviderBadResponseError("LLM 返回异常状态")

        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            logger.error("llm.bad_body", extra={"extra": {"model": self._model}})
            raise ProviderBadResponseError("LLM 响应结构异常") from exc
        return text.strip()


__all__ = ["OpenAICompatibleLLMProvider"]