"""Cencin (cencin.com.br) — mesma plataforma que Rico/Nosso Leilão.

URL pattern `/item/{id}/detalhes`. Listagem `/lotes/imovel` funciona
no cencin (testado: 8+ items). Reusa RicoLeiloesSpider.
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html_specific.ricoleiloes import (
    RicoLeiloesSpider,
)


class CencinSpider(RicoLeiloesSpider):
    name = "cencin"
    auctioneer_slug = "cencin"
    start_urls = [
        "https://www.cencin.com.br/lotes/imovel",
    ]
