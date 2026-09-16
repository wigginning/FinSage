"""C-8 LLM 连通性探针（单次低频，合规，不加随机）。遍历候选模型验证可用性。

读取 settings 的 FIN_LLM_API_KEY / FIN_LLM_BASE_URL；先探 CLI 传入或默认模型。
仅打印可达性结论，不打印任何密钥。对每个模型发一次极短请求，避免浪费额度。
"""

from __future__ import annotations

import asyncio
import sys

from finsage.providers.llm.openai_compat import OpenAICompatibleLLMProvider
from finsage.settings import Settings

# 候选测试模型（用户提供，临时测试用途）
CANDIDATES = [
    "qwen3.7-plus-2026-05-26",
    "qwen3.7-plus",
    "qwen3.7-max-2026-05-17",
    "qwen3.7-max-2026-06-08",
    "glm-5.2",
]


async def _probe_one(provider: OpenAICompatibleLLMProvider | None, model: str) -> str:
    if provider is None or provider._model != model:  # noqa: SLF001 —— 探针直接构造
        provider = OpenAICompatibleLLMProvider(
            api_key=provider._api_key if provider else "x",  # noqa: SLF001
            base_url=provider._base_url if provider else "x",  # noqa: SLF001
            model=model,
            timeout=45,
        )
    try:
        text = provider.complete(
            system="你是 FinSage 评测探针。只回复两个字。",
            prompt="连通性测试：请回复 OK",
        )
        return f"OK  resp={text[:40]!r}"
    except Exception as exc:  # noqa: BLE001 —— 探针需汇总任意失败
        return f"FAIL {type(exc).__name__}: {str(exc)[:120]}"


async def _main() -> None:
    s = Settings(_env_file=None)
    s = Settings()  # 读取 .env
    if not (s.llm_api_key and s.llm_base_url):
        print("ERROR: 未配置 FIN_LLM_API_KEY / FIN_LLM_BASE_URL")
        sys.exit(1)
    base = OpenAICompatibleLLMProvider(
        api_key=s.llm_api_key,
        base_url=s.llm_base_url,
        model=s.llm_model or CANDIDATES[0],
    )
    # CLI: 可传单个模型名（如 --model=...）精确测试；否则默认探 base 模型
    target = None
    for arg in sys.argv[1:]:
        if arg.startswith("--model="):
            target = arg.split("=", 1)[1]
    models = [target] if target else CANDIDATES
    print(f"base_url={s.llm_base_url}（密钥隐藏）")
    for m in models:
        print(f"[{m}] " + await _probe_one(base, m))


if __name__ == "__main__":
    asyncio.run(_main())