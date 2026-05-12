"""Regina Aude Leilões (www.reginaaudeleiloes.com.br) — 3 lotes falsos
positivos na baseline.

Mesmo template ASP.NET dos "satélites leilovia" (Casa de Leilões,
Leilões Online MS). Exposição real do leilão acontece em
leilovia.com.br via postback.

DIFERENÇA: o home tem cards `<a href="/leilao/<slug>/<id>">` (caixas
de leilão agrupado) — vale a pena seguir e tentar listar lotes desse
"super-card". Para v1, mantemos como noop e deixamos o spider futuro
do provider `leilovia` resolver o trabalho real.

# noop spider — genérico (após blocklist) elimina os falsos positivos.
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider


class ReginaAudeSpider(ProprioHtmlSpider):
    name = "regina_aude"
    provider_slug = "regina_aude"
    auctioneer_slug = "regina_aude"
