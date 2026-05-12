"""Portalax (portalax.com.br) — 4 lotes na baseline.

Compartilha o template do Araújo (mesma estrutura HTML/CSS,
provavelmente a mesma agência de desenvolvimento). Os fixes são
idênticos: título em `<h2>`, preço via `Lance Nº Leilão R$ X`,
imagens via `background:url()` shorthand.
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html_specific.araujo_leiloes import (
    AraujoLeiloesSpider,
)


class PortalaxSpider(AraujoLeiloesSpider):
    name = "portalax"
    provider_slug = "portalax"
    auctioneer_slug = "portalax"
