"""C-8 前置探针：Milvus 集合 + Registry 真实可用性（单次，低频，合规）。"""

from __future__ import annotations

import asyncio

from finsage.providers.finance import build_registry
from finsage.retrieval.client import MilvusClientManager
from finsage.retrieval.schema import COLLECTION_NAME


async def _main() -> None:
    # Milvus 集合
    manager = MilvusClientManager()
    try:
        exists = manager.has_collection(COLLECTION_NAME)
        print(f"milvus collection '{COLLECTION_NAME}' exists: {exists}")
        if exists:
            stats = manager.client.get_collection_stats(COLLECTION_NAME)
            print(f"  collection stats: {stats}")
    except Exception as exc:  # noqa: BLE001
        print(f"milvus probe error: {type(exc).__name__}: {str(exc)[:120]}")
    finally:
        manager.close()

    # Registry 真实健康
    reg = build_registry()
    print("registered:", reg.names())
    for name in reg.names():
        try:
            prov = reg.get(name)
            h = await prov.health_check()
            print(f"  {name} health={h.status}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {name} health ERROR {type(exc).__name__}: {str(exc)[:100]}")


if __name__ == "__main__":
    asyncio.run(_main())