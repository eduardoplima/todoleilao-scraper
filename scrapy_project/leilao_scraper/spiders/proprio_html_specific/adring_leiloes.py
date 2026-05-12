"""Adring Leilões (www.adringleiloes.com.br) — 3 lotes na baseline.

Mesma plataforma CakePHP do Casa Do Leilão; markup com
`Avaliação: R$ A` / `Lance Mínimo: R$ B`. Genérico já cobre.
Fixup defensivo via `extract_casa_platform_prices` para cobrir
variantes de Primeiro/Segundo Leilão se o tenant migrar.
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider
from leilao_scraper.spiders.proprio_html_specific._common import (
    extract_casa_platform_prices,
)


class AdringLeiloesSpider(ProprioHtmlSpider):
    name = "adring_leiloes"
    provider_slug = "adring_leiloes"
    auctioneer_slug = "adring_leiloes"

    def _fixup_item(self, item, response, *, body_text: str, host: str) -> None:
        market, minimum = extract_casa_platform_prices(body_text)
        if minimum is not None and not item.get("minimum_bid"):
            item["minimum_bid"] = str(minimum)
        if market is not None and not item.get("market_value"):
            item["market_value"] = str(market)
