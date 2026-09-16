"""Milvus 集合 Schema（T202）。按规格 §6.1–6.3 落建 finsage_chunks。

字段/索引契约 FROZEN，不自行改字段或 metric；
值与索引类型按所选 Milvus 版本（服务端 v2.4.6 + pymilvus 3.0 MilvusClient）落地。
"""

from __future__ import annotations

from typing import Any

from finsage.exceptions import RetrievalError
from finsage.observability.logger import get_logger, io_point

from .client import MilvusClientManager

logger = get_logger(__name__)

COLLECTION_NAME = "finsage_chunks"

# 密集向量维度 = BGE-M3 输出维度（§6.2/§2）。
DENSE_DIM = 1024

# 字符串/标量字段上限（VARCHAR 需显式 max_length）。
_TENANT_ID_MAX = 64
_ID_MAX = 64
_TEXT_MAX = 65535  # text 以 String(65535) 承载（§6.2 dynamic text 亦可用该上限）
_COMPANY_MAX = 255
_TICKER_MAX = 64
_MARKET_MAX = 32
_DOCTYPE_MAX = 64
_PERIOD_MAX = 32
_PK_MAX = 128


def escape_expr_str(value: str) -> str:
    """转义 Milvus filter 表达式中的字符串字面量（P2 注入防护，审计 §2.1）。

    外部传入的 document_id/tenant_id 等拼接进 Milvus expr 时，先反转义 ``\\`` 与
    双引号，阻止通过引号逃逸构造越权过滤（跨租户检索）。
    """
    if value is None:
        return ""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _new_client() -> Any:
    """惰性导入并构造一个 MilvusClient 以复用其 Schema/IndexParams 构造器（不连接）。

    返回 Any 而非 object：pymilvus 惰性导入且未提供类型信息，标 object 会让
    ``create_schema`` / ``prepare_index_params`` 等构造器方法在类型层不可见。
    """
    from pymilvus import MilvusClient

    return MilvusClient(uri="http://127.0.0.1:19730")


def _build_schema():
    """构造 §6.2 集合 Schema（15 字段，pymilvus 3.0 新式 API）。"""
    from pymilvus import DataType

    client = _new_client()
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)

    schema.add_field(
        field_name="pk", datatype=DataType.VARCHAR, is_primary=True, max_length=_PK_MAX
    )
    schema.add_field(field_name="document_id", datatype=DataType.VARCHAR, max_length=_ID_MAX)
    schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, max_length=_ID_MAX)
    schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=_TEXT_MAX)
    schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=DENSE_DIM)
    schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
    schema.add_field(field_name="tenant_id", datatype=DataType.VARCHAR, max_length=_TENANT_ID_MAX)
    schema.add_field(field_name="company", datatype=DataType.VARCHAR, max_length=_COMPANY_MAX)
    schema.add_field(field_name="ticker", datatype=DataType.VARCHAR, max_length=_TICKER_MAX)
    schema.add_field(field_name="market", datatype=DataType.VARCHAR, max_length=_MARKET_MAX)
    schema.add_field(field_name="document_type", datatype=DataType.VARCHAR, max_length=_DOCTYPE_MAX)
    schema.add_field(field_name="report_period", datatype=DataType.VARCHAR, max_length=_PERIOD_MAX)
    schema.add_field(field_name="published_at_ts", datatype=DataType.INT64)
    schema.add_field(field_name="page", datatype=DataType.INT64)
    schema.add_field(field_name="authority_tier", datatype=DataType.INT64)
    return schema


def _build_index_params():
    """构造 §6.3 索引：dense=COSINE，sparse=IP（BM25 兼容），均用 2.4 有效类型。"""
    client = _new_client()
    idx = client.prepare_index_params()
    idx.add_index(
        field_name="dense_vector",
        index_type="AUTOINDEX",
        metric_type="COSINE",
        index_name="idx_dense",
    )
    idx.add_index(
        field_name="sparse_vector",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="IP",
        index_name="idx_sparse",
    )
    return idx


@io_point("retrieval", "milvus_ensure_collection")
def ensure_collection(manager: MilvusClientManager, *, force_recreate: bool = False) -> None:
    """按 §6 确保集合存在；force_recreate 时先删后建（仅测试/初始化用）。"""
    client = manager.client
    if manager.has_collection(COLLECTION_NAME):
        if not force_recreate:
            return
        client.drop_collection(COLLECTION_NAME)

    try:
        schema = _build_schema()
        index_params = _build_index_params()
        client.create_collection(
            collection_name=COLLECTION_NAME,
            schema=schema,
            index_params=index_params,
        )
        logger.info("milvus_collection_ready", extra={"extra": {"name": COLLECTION_NAME}})
    except Exception as exc:  # noqa: BLE001
        raise RetrievalError(f"milvus ensure collection failed: {type(exc).__name__}") from exc