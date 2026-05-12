"""Biasi Leilões (www.biasileiloes.com.br) — 10 lotes na baseline.

URLs no formato `/sale/detail?id=N`. Markup usa `Lance Inicial - R$ X`
(traço entre o rótulo e o valor) — a regex universal espera
`Lance Inicial:` ou `Lance Inicial<espaço>R$`, e o traço quebra o match.

A página detalhe NÃO expõe valor de avaliação publicamente, então
`market_value` continuará vazio (limitação do site, não do spider).
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider
from leilao_scraper.spiders.proprio_html_specific._common import (
    extract_lance_min_with_dash,
)


class BiasiLeiloesSpider(ProprioHtmlSpider):
    name = "biasi_leiloes"
    provider_slug = "biasi_leiloes"
    auctioneer_slug = "biasi_leiloes"

    def _fixup_item(self, item, response, *, body_text: str, host: str) -> None:
        if not item.get("minimum_bid"):
            v = extract_lance_min_with_dash(body_text)
            if v:
                item["minimum_bid"] = str(v)
