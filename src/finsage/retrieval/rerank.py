"""BGE-Reranker-v2-m3 重排（T211）。

模型资源策略同 BGE-M3（tasks/index.md）：
  1. 优先取本地预下载目录 model_local_dir（只读）；
  2. 本地缺失/损坏：在线下载到 model_cache_dir，成功缓存复用；
  3. 不更替冻结模型名。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from finsage.exceptions import RerankFailedError
from finsage.settings import Settings, get_settings

logger = logging.getLogger(__name__)

MODEL_NAME = "bge-reranker-v2-m3"


def _resolve_local_model(settings: Settings) -> Path | None:
    candidate = settings.model_local_path / MODEL_NAME
    if candidate.is_dir() and (candidate / "config.json").is_file():
        return candidate
    return None


def _resolve_cache_model(settings: Settings) -> Path:
    cache = settings.model_cache_path / MODEL_NAME
    cache.mkdir(parents=True, exist_ok=True)
    return cache


class BGEReranker:
    """BGE-Reranker-v2-m3 交叉编码重排器（进程级单例可复用）。"""

    def __init__(self, settings: Settings | None = None, *, rerank_k: int = 10) -> None:
        self.settings = settings or get_settings()
        self.rerank_k = rerank_k
        # 惰性加载的 FlagReranker（第三方无类型信息）。不标 Any 会被推断成 None 类型，
        # 使 _load() 之后的 compute_score 调用在类型层不可见。
        self._model: Any = None
        self._model_path: Path | None = None

    def _load(self) -> None:
        if self._model is not None:
            return
        local = _resolve_local_model(self.settings)
        if local is not None:
            self._model_path = local
            logger.info("reranker_use_local", extra={"extra": {"path": str(local)}})
        else:
            self._model_path = _resolve_cache_model(self.settings)
            logger.warning(
                "reranker_download_fallback",
                extra={"extra": {"cache": str(self._model_path)}},
            )
        from FlagEmbedding import FlagReranker

        self._model = FlagReranker(str(self._model_path), use_fp16=False, device="cpu")
        logger.info("reranker_loaded", extra={"extra": {"name": MODEL_NAME}})

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        """对候选（dict 列表）按 (query, text) 交叉编码打分并重排。

        入参 candidates 每条需含 "id" 与 "text"；返回按分数降序的候选（追加 rerank_score）。
        空候选直接返回 []，不空跑模型。
        """
        if not candidates:
            return []
        self._load()

        pairs = [(query, c["text"]) for c in candidates]
        try:
            scores = self._model.compute_score(pairs, normalize=True)
        except Exception as exc:  # noqa: BLE001
            raise RerankFailedError(
                f"BGE-Reranker-v2-m3 compute_score failed: {type(exc).__name__}"
            ) from exc

        if isinstance(scores, float):  # 单条输入时返回标量
            scores = [scores]

        ranked = [
            {**c, "rerank_score": float(score)}
            for c, score in zip(candidates, scores, strict=True)
        ]
        ranked.sort(key=lambda item: item["rerank_score"], reverse=True)
        return ranked[: self.rerank_k]