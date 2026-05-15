"""Mais clones da plataforma "Rico Leilões".

ConceitoLeiloes: testado 2026-05-14 — leilões ativos só com veículos
(0 items extraídos no smoke). Spider mantido pronto para quando o
tenant publicar imóveis.

DesantiLeiloes: 0 leilões na home no momento do recon. Spider
mantido como placeholder.
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html_specific.nossoleilao import (
    NossoLeilaoSpider,
)


class ConceitoLeiloesSpider(NossoLeilaoSpider):
    name = "conceitoleiloes"
    auctioneer_slug = "conceitoleiloes"
    start_urls = ["https://www.conceitoleiloes.com.br/"]


class DesantiLeiloesSpider(NossoLeilaoSpider):
    name = "desantileiloes"
    auctioneer_slug = "desantileiloes"
    start_urls = ["https://www.desantileiloes.com.br/"]
