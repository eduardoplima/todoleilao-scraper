"""Lorrana Leilões (www.lorranaleiloes.com.br) — 3 lotes falsos
positivos na baseline (capturava `/lotes/132` que é página de leilão,
não detalhe).

Frontend Vue + backend `api.serranaleiloes.com.br` (compartilhado com
leonardoveiga e leiloesnovaserrana).
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html_specific._serrana_api_base import (
    SerranaApiBaseSpider,
)


class LorranaLeiloesSpider(SerranaApiBaseSpider):
    name = "lorrana_leiloes"
    provider_slug = "lorrana_leiloes"
    auctioneer_slug = "lorrana_leiloes"
