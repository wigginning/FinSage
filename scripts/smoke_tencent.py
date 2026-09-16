"""C-10 真实连通冒烟（单次低频，合规）。通过 Registry 走 Tencent 拉真实行情。"""

from __future__ import annotations

import asyncio

from finsage.providers.finance import TencentQuoteProvider, build_registry


async def _main() -> None:
    registry = build_registry()
    print("registered:", registry.names())
    # Tencent Provider 直连路径（真实单次低频请求）
    tencent = TencentQuoteProvider()
    q = await tencent.get_quote("000001", "CN.SZ")
    print(
        f"tencent get_quote -> {q.name}({q.symbol}) "
        f"price={q.price} currency={q.currency} market={q.market} src={q.source}"
    )
    h = await tencent.health_check()
    print(f"tencent health -> {h.status}")
    print("smoke OK")


if __name__ == "__main__":
    asyncio.run(_main())