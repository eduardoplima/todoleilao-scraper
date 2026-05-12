"""Leilões Nova Serrana (www.leiloesnovaserrana.com.br) — 3 lotes na
baseline. Mesma plataforma serrana-api dos demais (provavelmente o
tenant "raiz" que dá nome ao backend).
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html_specific._serrana_api_base import (
    SerranaApiBaseSpider,
)


class LeiloesNovaSerranaSpider(SerranaApiBaseSpider):
    name = "leiloes_nova_serrana"
    provider_slug = "leiloes_nova_serrana"
    auctioneer_slug = "leiloes_nova_serrana"
