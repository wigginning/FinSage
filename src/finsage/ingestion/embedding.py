"""BGE-M3 Embedding（T207）。同一模型一次前向产出 dense(L2) 与 sparse(lexical)。

模型资源策略（tasks/index.md 全局规则）：
  1. 优先取本地预下载目录 model_local_dir（只读，不修改/覆盖）；
  2. 本地缺失/损坏时：在线下载到可配置缓存目录 model_cache_dir，成功缓存复用；
  3. 不更替冻结技术栈模型名（BGE-M3）。

注：encode 返回 numpy 结果不可 JSON 化，故不对原始出参套 io_point（避免 formatter 崩溃），
改为方法内记录维度/批次等轻量摘要日志，符合"所有节点 IO 埋点"精神。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from finsage.settings import Settings, get_settings

from .models import IndexedChunk

logger = logging.getLogger(__name__)

# BGE-M3 冻结模型标识（用于本地目录名与在线兜底标识）。
MODEL_NAME = "bge-m3"
DENSE_DIM = 1024


def _resolve_local_model(settings: Settings) -> Path | None:
    """定位本地预下载模型目录；存在且内含 config.json 才视为有效。"""
    candidate = settings.model_local_path / MODEL_NAME
    if candidate.is_dir() and (candidate / "config.json").is_file():
        return candidate
    return None


def _resolve_cache_model(settings: Settings) -> Path:
    """确定在线兜底下载的缓存目录（可创建，不属于只读预下载目录）。"""
    cache = settings.model_cache_path / MODEL_NAME
    cache.mkdir(parents=True, exist_ok=True)
    return cache


class BGE3Embedder:
    """BGE-M3 dense+sparse 向量生成器（进程级单例可复用）。"""

    def __init__(self, settings: Settings | None = None, *, batch_size: int = 32) -> None:
        self.settings = settings or get_settings()
        self.batch_size = batch_size
        # 惰性加载的 BGEM3FlagModel（第三方无类型信息）。不标 Any 会被推断成 None 类型，
        # 使 _load() 之后的 encode 调用在类型层不可见。
        self._model: Any = None
        self._model_path: Path | None = None

    def _load(self) -> None:
        if self._model is not None:
            return
        local = _resolve_local_model(self.settings)
        if local is not None:
            self._model_path = local
            logger.info("embedder_use_local", extra={"extra": {"path": str(local)}})
        else:
            self._model_path = _resolve_cache_model(self.settings)
            logger.warning(
                "embedder_download_fallback",
                extra={"extra": {"cache": str(self._model_path)}},
            )
        from FlagEmbedding import BGEM3FlagModel

        self._model = BGEM3FlagModel(
            str(self._model_path),
            use_fp16=False,
            device="cpu",
            normalize_embeddings=True,
        )
        logger.info(
            "embedder_loaded",
            extra={"extra": {"name": MODEL_NAME, "dense_dim": DENSE_DIM}},
        )

    def encode_chunks(self, chunks: list) -> list[IndexedChunk]:
        """对 Chunk 列表批量生成 dense+sparse，返回可索引记录。

        若 chunk 已携带向量（测试注入），透明走通而不重复调用模型。
        """
        if not chunks:
            return []
        if all(getattr(c, "_indexed", False) for c in chunks):
            return list(chunks)

        self._load()
        texts = [c.text for c in chunks]
        out = self._model.encode(
            texts,
            batch_size=min(self.batch_size, max(1, len(texts))),
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense = out["dense_vecs"]  # (n, 1024) numpy
        sparse = out["lexical_weights"]  # list[dict[str, float]]

        result: list[IndexedChunk] = []
        for i, chunk in enumerate(chunks):
            # lexical_weights 键为 sentencepiece vocab id（str），转为 int 供 Milvus sparse。
            sparse_vec = {int(k): float(v) for k, v in sparse[i].items()}
            result.append(
                IndexedChunk(
                    chunk=chunk,
                    dense_vector=[float(x) for x in dense[i].tolist()],
                    sparse_vector=sparse_vec,
                )
            )
        logger.info(
            "embed_ok",
            extra={
                "extra": {
                    "batch": len(texts),
                    "dense_dim": DENSE_DIM,
                    "sparse_nonzero": len(result[0].sparse_vector) if result else 0,
                }
            },
        )
        return result

    def encode_text(self, query: str) -> tuple[list[float], dict[int, float]]:
        """为检索 query 生成 (dense, sparse)。"""
        self._load()
        out = self._model.encode(
            [query],
            batch_size=1,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense = [float(x) for x in out["dense_vecs"][0].tolist()]
        sparse = {int(k): float(v) for k, v in out["lexical_weights"][0].items()}
        return dense, sparse