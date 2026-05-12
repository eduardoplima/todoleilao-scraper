"""Leonardo Veiga Leilões (www.leonardoveigaleiloes.com.br) — 3 lotes
na baseline. Mesma plataforma serrana-api do lorrana/leiloesnovaserrana.
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html_specific._serrana_api_base import (
    SerranaApiBaseSpider,
)


class LeonardoVeigaSpider(SerranaApiBaseSpider):
    name = "leonardo_veiga"
    provider_slug = "leonardo_veiga"
    auctioneer_slug = "leonardo_veiga"
