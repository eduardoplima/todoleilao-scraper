"""Casa Do Leilão (www.casadoleilao.com) — 11 lotes na baseline.

Plataforma CakePHP "casa-do-leilão" usada também por marquesbarretoleiloes,
adringleiloes e dearaujoleiloes. Mas o markup de preço **varia** entre
estes tenants:

  - Casa Do Leilão: `Primeiro Leilão: R$ A` / `Segundo Leilão: R$ B`
  - Marques Barreto: `Avaliação: R$ A` / `Lance Mínimo: R$ B`
  - Adring: `Avaliação: R$ A` / `Lance Mínimo: R$ B`

Esta classe trata o markup específico do Casa Do Leilão (Primeiro/Segundo
Leilão). As demais herdam de `CasaDoLeilaoVariantSpider` para variante
Marques-style.

Gap principal do genérico: `minimum_bid` ficou em 0/11 porque
"Segundo Leilão" não casa nenhuma das regex universais.
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider
from leilao_scraper.spiders.proprio_html_specific._common import (
    extract_casa_platform_prices,
)


class CasaDoLeilaoSpider(ProprioHtmlSpider):
    name = "casa_do_leilao"
    provider_slug = "casa_do_leilao"
    auctioneer_slug = "casa_do_leilao"

    def _fixup_item(self, item, response, *, body_text: str, host: str) -> None:
        market, minimum = extract_casa_platform_prices(body_text)
        if minimum is not None and not item.get("minimum_bid"):
            item["minimum_bid"] = str(minimum)
        if market is not None and not item.get("market_value"):
            item["market_value"] = str(market)
