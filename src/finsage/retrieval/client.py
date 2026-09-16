"""Milvus Client 封装（T201）。pymilvus 3.0 的 MilvusClient 生命周期与管理。

说明：本地装的是 pymilvus 3.0（兼容服务端 v2.4.6，已实测可连），ORM 风格 API
（connections/utility）在 3.1 移除，本模块统一改用 MilvusClient（新模型 API）。
"""

from __future__ import annotations

from finsage.exceptions import RetrievalError
from finsage.observability.logger import get_logger, io_point
from finsage.settings import Settings, get_settings

logger = get_logger(__name__)


class MilvusClientManager:
    """管理 MilvusClient 连接；提供集合存在性 / 清理等元操作。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = None
        self.uri = f"http://{self.settings.milvus_host}:{self.settings.milvus_port}"

    @property
    def client(self):
        self.ensure_connected()
        return self._client

    def ensure_connected(self):
        if self._client is None:
            from pymilvus import MilvusClient

            try:
                self._client = MilvusClient(uri=self.uri)
                logger.info("milvus_connected", extra={"extra": {"uri": self.uri}})
            except Exception as exc:  # noqa: BLE001 - 连接失败统一归检索错误
                raise RetrievalError(f"milvus connect failed: {type(exc).__name__}") from exc
        return self._client

    @io_point("retrieval", "milvus_has_collection")
    def has_collection(self, name: str) -> bool:
        try:
            return bool(self.client.has_collection(name))
        except RetrievalError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RetrievalError(f"milvus has_collection failed: {type(exc).__name__}") from exc

    @io_point("retrieval", "milvus_drop_collection")
    def drop_collection(self, name: str) -> None:
        try:
            self.client.drop_collection(name)
        except Exception as exc:  # noqa: BLE001
            raise RetrievalError(f"milvus drop_collection failed: {type(exc).__name__}") from exc

    @io_point("retrieval", "milvus_close")
    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None