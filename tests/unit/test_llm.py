"""LLM Provider 单测（m06 T609a / C-7）。

用 mock 的 httpx 拦截，不真调网络：验证 OpenAI 兼容 provider 的
- 正确路径解析（响应 body → 补全文本）；
- 结构化模式（response_format=json_object，返回 JSON 文本）；
- 错误映射（超时 → ProviderTimeoutError；非 200 / 坏 body → ProviderBadResponseError）；
- ``build_llm_provider`` 路由（配凭据 → 真实；否则 → Dummy）。
"""
from __future__ import annotations

from unittest import mock

import httpx
import pytest
from pydantic import BaseModel

from finsage.exceptions import (
    ProviderBadResponseError,
    ProviderTimeoutError,
)
from finsage.providers.llm import (
    DummyLLMProvider,
    LLMProviderRegistry,
    OpenAICompatibleLLMProvider,
    build_llm_provider,
    build_llm_registry,
)


class _Schema(BaseModel):
    text: str
    count: int = 0


def _provider() -> OpenAICompatibleLLMProvider:
    return OpenAICompatibleLLMProvider(
        api_key="test-key",
        base_url="https://gateway.example/v1",
        model="qwen3.7-plus",
    )


def test_complete_parses_content() -> None:
    p = _provider()
    resp = mock.Mock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": "  合成的叙事  "}}]}
    with mock.patch("httpx.post", return_value=resp) as post:
        out = p.complete(system="系统", prompt="提示")
    assert out == "合成的叙事"
    # 请求打到 <base>/chat/completions 且带鉴权头、禁用温度。
    assert post.call_args[0][0].endswith("/chat/completions")
    headers = post.call_args.kwargs["headers"]
    assert headers["Authorization"] == "Bearer test-key"
    assert post.call_args.kwargs["json"]["temperature"] == 0.0


def test_complete_structured_requests_json_object() -> None:
    p = _provider()
    resp = mock.Mock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": '{"ok": true}'}}]}
    with mock.patch("httpx.post", return_value=resp) as post:
        out = p.complete_structured(system="s", prompt="p")
    assert out == '{"ok": true}'
    assert post.call_args.kwargs["json"]["response_format"] == {"type": "json_object"}


def test_complete_typed_parses_schema() -> None:
    p = _provider()
    resp = mock.Mock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": '{"text": "hi", "count": 3}'}}]}
    with mock.patch("httpx.post", return_value=resp):
        out = p.complete_typed(system="s", prompt="p", schema=_Schema)
    assert isinstance(out, _Schema)
    assert out.text == "hi" and out.count == 3


def test_complete_typed_invalid_json_maps_to_bad_response() -> None:
    p = _provider()
    resp = mock.Mock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": "not json"}}]}
    with mock.patch("httpx.post", return_value=resp), pytest.raises(ProviderBadResponseError):
        p.complete_typed(system="s", prompt="p", schema=_Schema)


def test_complete_typed_validation_failure_maps_to_bad_response() -> None:
    p = _provider()
    resp = mock.Mock()
    resp.status_code = 200
    # 缺必填 text 且 count 非法 -> 校验失败。
    resp.json.return_value = {"choices": [{"message": {"content": '{"count": "abc"}'}}]}
    with mock.patch("httpx.post", return_value=resp), pytest.raises(ProviderBadResponseError):
        p.complete_typed(system="s", prompt="p", schema=_Schema)


def test_dummy_complete_typed_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        DummyLLMProvider().complete_typed(system="s", prompt="p", schema=_Schema)


def test_timeout_maps_to_provider_timeout() -> None:
    p = _provider()
    with (
        mock.patch("httpx.post", side_effect=httpx.TimeoutException("boom")),
        pytest.raises(ProviderTimeoutError),
    ):
        p.complete(system="s", prompt="p")


def test_non_200_maps_to_bad_response() -> None:
    p = _provider()
    resp = mock.Mock()
    resp.status_code = 401
    with mock.patch("httpx.post", return_value=resp), pytest.raises(ProviderBadResponseError):
        p.complete(system="s", prompt="p")


def test_bad_body_maps_to_bad_response() -> None:
    p = _provider()
    resp = mock.Mock()
    resp.status_code = 200
    resp.json.side_effect = ValueError("bad json")
    with mock.patch("httpx.post", return_value=resp), pytest.raises(ProviderBadResponseError):
        p.complete(system="s", prompt="p")


def test_build_llm_provider_with_creds_returns_real() -> None:
    s = _settings(api_key="k", base_url="https://gw/v1", model="qwen3.7-max")
    assert isinstance(build_llm_provider(s), OpenAICompatibleLLMProvider)


def test_build_llm_provider_without_creds_returns_dummy() -> None:
    s = _settings(api_key=None, base_url=None, model="")
    assert isinstance(build_llm_provider(s), DummyLLMProvider)


def test_build_llm_provider_partial_creds_returns_dummy() -> None:
    s = _settings(api_key="k", base_url="https://gw/v1", model="")
    assert isinstance(build_llm_provider(s), DummyLLMProvider)


def _settings(
    *,
    api_key,
    base_url,
    model,
    adv_api_key=None,
    adv_base_url=None,
    adv_model="",
):
    s = mock.Mock()
    s.llm_api_key = api_key
    s.llm_base_url = base_url
    s.llm_model = model
    s.llm_timeout = 90.0
    s.llm_adversarial_api_key = adv_api_key
    s.llm_adversarial_base_url = adv_base_url
    s.llm_adversarial_model = adv_model
    return s


def test_registry_register_get_names() -> None:
    r = LLMProviderRegistry()
    r.register("a", DummyLLMProvider())
    assert r.get("a").name == "dummy"
    assert r.get_or_none("missing") is None
    assert r.names() == ["a"]


def test_registry_get_missing_raises() -> None:
    r = LLMProviderRegistry()
    with pytest.raises(KeyError):
        r.get("missing")


def test_build_llm_registry_default_only() -> None:
    s = _settings(api_key=None, base_url=None, model="")
    r = build_llm_registry(s)
    assert r.names() == ["default"]
    assert isinstance(r.get("default"), DummyLLMProvider)
    assert r.get_or_none("adversarial") is None


def test_build_llm_registry_with_adversarial() -> None:
    s = _settings(
        api_key="k",
        base_url="https://gw/v1",
        model="qwen",
        adv_api_key="ak",
        adv_base_url="https://gw2/v1",
        adv_model="gpt-4o",
    )
    r = build_llm_registry(s)
    assert r.names() == ["default", "adversarial"]
    assert isinstance(r.get("adversarial"), OpenAICompatibleLLMProvider)