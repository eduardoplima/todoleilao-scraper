"""Spiders Playwright-genéricos para 7 providers SPA pendentes.

Cada provider tem um SaaS distinto mas todos compartilham o mesmo
problema técnico (SPA puro ou CDN-blocked) — herdar de
ProprioHtmlSpider com `provider_slug` apropriado resolve. As
heurísticas universais já cobrem os padrões dominantes (/lote, /item,
/produto, /categoria/...). Quando alguém precisar de extração mais
fina, basta sobrescrever `parse_property` na subclasse específica.

Providers cobertos:
  - sishp (6 sites — JS navigation, ISO-8859-1)
  - softgt (8 sites — SPA via leilao.js)
  - palacio_dos_leiloes (5 sites — camada_ajax SPA)
  - leiloesweb (3 sites — SPA puro)
  - wix (3 sites — Wix CMS)
  - leiloesbr (6 sites — backend leiloesbr.com.br compartilhado)
  - sodre_santoro (1 site — Azion CDN bloqueia HTTP simples)

Total: 32 sites adicionais.
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider


class SishpSpider(ProprioHtmlSpider):
    name = "sishp"
    provider_slug = "sishp"
    auctioneer_slug = "sishp"


class SoftgtSpider(ProprioHtmlSpider):
    name = "softgt"
    provider_slug = "softgt"
    auctioneer_slug = "softgt"


class PalacioDosLeiloesSpider(ProprioHtmlSpider):
    name = "palacio_dos_leiloes"
    provider_slug = "palacio_dos_leiloes"
    auctioneer_slug = "palacio_dos_leiloes"


class LeiloeswebSpider(ProprioHtmlSpider):
    name = "leiloesweb"
    provider_slug = "leiloesweb"
    auctioneer_slug = "leiloesweb"


class WixSpider(ProprioHtmlSpider):
    name = "wix"
    provider_slug = "wix"
    auctioneer_slug = "wix"


class LeiloesbrSpider(ProprioHtmlSpider):
    name = "leiloesbr"
    provider_slug = "leiloesbr"
    auctioneer_slug = "leiloesbr"


class SodreSantoroSpider(ProprioHtmlSpider):
    name = "sodre_santoro"
    provider_slug = "sodre_santoro"
    auctioneer_slug = "sodre_santoro"
