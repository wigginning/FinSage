"""检索参数与权重（§21.2–21.4 —— FROZEN）。

候选/重排 K 值与初始权重为契约默认值；权重必须进入 Evaluation，
允许经配置覆盖，不得在此硬编码改写冻结契约。
"""

from __future__ import annotations

# §21.2 Default Retrieval
CANDIDATE_K = 50
RERANK_K = 10

# §21.3 Semantic Query 初始权重
SEMANTIC_DENSE_WEIGHT = 0.7
SEMANTIC_SPARSE_WEIGHT = 0.3

# §21.4 Numeric Query 初始权重
NUMERIC_DENSE_WEIGHT = 0.4
NUMERIC_SPARSE_WEIGHT = 0.6

# 上层检索时默认按语义权重（Evaluation 阶段再按查询类型覆盖）。
DEFAULT_DENSE_WEIGHT = SEMANTIC_DENSE_WEIGHT
DEFAULT_SPARSE_WEIGHT = SEMANTIC_SPARSE_WEIGHT

# 混合检索各通道（dense/sparse）单独召回数：融合取并集，故放大避免并集不足。
_CHANNEL_MULTIPLIER = 3


def channel_k(candidate_k: int = CANDIDATE_K) -> int:
    """各通道召回条数（融合前）。"""
    return candidate_k * _CHANNEL_MULTIPLIER