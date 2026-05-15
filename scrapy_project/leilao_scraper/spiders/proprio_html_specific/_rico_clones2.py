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


class CasaMartilloSpider(NossoLeilaoSpider):
    """26 leiloeiros high — maior site da long-tail."""
    name = "casamartillo"
    auctioneer_slug = "casamartillo"
    start_urls = ["https://www.casamartillo.com.br/"]


# ----- Outros clones detectados em batch (2026-05-14) ---------------------
# Heurística: presença de `/item/N/detalhes` ou `/leilao/N/lotes` no HTML
# da home. Todos respondem ao crawler do NossoLeilaoSpider sem alterações.


class ClicLeiloesSpider(NossoLeilaoSpider):
    name = "clicleiloes"
    auctioneer_slug = "clicleiloes"
    start_urls = ["https://www.clicleiloes.com.br/"]


class RJLeiloesSpider(NossoLeilaoSpider):
    name = "rjleiloes"
    auctioneer_slug = "rjleiloes"
    start_urls = ["https://www.rjleiloes.com.br/"]


class CargneluttiLeiloesSpider(NossoLeilaoSpider):
    name = "cargneluttileiloes"
    auctioneer_slug = "cargneluttileiloes"
    start_urls = ["https://www.cargneluttileiloes.com.br/"]


class LeiloesAguiarSpider(NossoLeilaoSpider):
    name = "leiloesaguiar"
    auctioneer_slug = "leiloesaguiar"
    start_urls = ["https://www.leiloesaguiar.com.br/"]


class MaraUrzedoLeilaoSpider(NossoLeilaoSpider):
    name = "maraurzedoleilao"
    auctioneer_slug = "maraurzedoleilao"
    start_urls = ["https://www.maraurzedoleilao.com.br/"]


class LancESpider(NossoLeilaoSpider):
    name = "lancese"
    auctioneer_slug = "lancese"
    start_urls = ["https://www.lancese.com.br/"]


class RealizaLeiloesSpider(NossoLeilaoSpider):
    name = "realizaleiloes"
    auctioneer_slug = "realizaleiloes"
    start_urls = ["https://www.realizaleiloes.com.br/"]


class PatioRochaLeiloesSpider(NossoLeilaoSpider):
    name = "patiorochaleiloes"
    auctioneer_slug = "patiorochaleiloes"
    start_urls = ["https://www.patiorochaleiloes.com.br/"]


class MullerLeiloesSpider(NossoLeilaoSpider):
    """Coincide com 'muller.py' existente; usar nome diferente para Scrapy."""
    name = "mullerleiloes_rico"
    auctioneer_slug = "mullerleiloes_rico"
    start_urls = ["https://www.mullerleiloes.com.br/"]


class CCJLeiloesSpider(NossoLeilaoSpider):
    name = "ccjleiloes"
    auctioneer_slug = "ccjleiloes"
    start_urls = ["https://www.ccjleiloes.com.br/"]


class JGCargneluttiLeiloesSpider(NossoLeilaoSpider):
    name = "jgcargneluttileiloes"
    auctioneer_slug = "jgcargneluttileiloes"
    start_urls = ["https://www.jgcargneluttileiloes.com.br/"]


class PimentelLeiloesSpider(NossoLeilaoSpider):
    name = "pimentelleiloes"
    auctioneer_slug = "pimentelleiloes"
    start_urls = ["https://www.pimentelleiloes.com.br/"]


class TresTorresLeiloesSpider(NossoLeilaoSpider):
    name = "tresttorresleiloes"
    auctioneer_slug = "tresttorresleiloes"
    start_urls = ["https://www.3torresleiloes.com.br/"]


class VictorDortaLeiloesSpider(NossoLeilaoSpider):
    name = "victordortaleiloes"
    auctioneer_slug = "victordortaleiloes"
    start_urls = ["https://www.victordortaleiloes.com.br/"]
