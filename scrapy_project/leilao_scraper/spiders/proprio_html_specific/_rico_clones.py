"""Spiders triviais sobre a plataforma "Rico Leilões" (Laravel/PHP).

Vários sites no Brasil rodam a mesma plataforma white-label de leilões
(URL pattern `/item/{id}/detalhes`, `/leilao/{N}/lotes`, h1 + #lance_inicial,
bloco "LEILOEIRO OFICIAL" com JUCESP). Cada site é subclass trivial de
`RicoLeiloesSpider`.

Heurística de detecção: presença simultânea de `/leilao/{id}/lotes` no
home e `/item/{id}/detalhes` no listing de leilão.
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html_specific.ricoleiloes import (
    RicoLeiloesSpider,
)
from leilao_scraper.spiders.proprio_html_specific.nossoleilao import (
    NossoLeilaoSpider,
)


class AmaralLeiloesSpider(NossoLeilaoSpider):
    name = "amaralleiloes"
    auctioneer_slug = "amaralleiloes"
    start_urls = ["https://www.amaralleiloes.com.br/"]


class FocoLeiloesSpider(NossoLeilaoSpider):
    name = "focoleiloes"
    auctioneer_slug = "focoleiloes"
    start_urls = ["https://www.focoleiloes.com.br/"]


class LottiLeiloesSpider(NossoLeilaoSpider):
    name = "lottileiloes"
    auctioneer_slug = "lottileiloes"
    start_urls = ["https://www.lottileiloes.com.br/"]
