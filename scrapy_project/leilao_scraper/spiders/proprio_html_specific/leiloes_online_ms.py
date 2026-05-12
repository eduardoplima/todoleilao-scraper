"""Leilões Online MS (www.leiloesonlinems.com.br) — 5 lotes falsos
positivos na baseline.

Landing page estático ASP.NET, mesmo padrão do Casa de Leilões e
Regina Aude — delega leilões para leilovia.com.br. Baseline pegava
`texto.aspx?cod=N` confundindo com lote.

# noop spider — genérico (após blocklist) já é correto.
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider


class LeiloesOnlineMsSpider(ProprioHtmlSpider):
    name = "leiloes_online_ms"
    provider_slug = "leiloes_online_ms"
    auctioneer_slug = "leiloes_online_ms"
