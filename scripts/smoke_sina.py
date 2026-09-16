"""C-10 真实连通冒烟（单次低频，合规）。通过 Registry 走 Sina 拉真实行情。"""

from __future__ import annotations

import asyncio

from finsage.providers.finance import SinaQuoteProvider


async def _main() -> None:
    sina = SinaQuoteProvider()
    q = await sina.get_quote("000001", "CN.SZ")
    print(
        f"sina get_quote -> {q.name}({q.symbol}) "
        f"price={q.price} currency={q.currency} market={q.market} src={q.source}"
    )
    h = await sina.health_check()
    print(f"sina health -> {h.status}")
    print("smoke OK")


if __name__ == "__main__":
    asyncio.run(_main())