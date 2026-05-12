"""Base compartilhada entre lorrana, leonardoveiga e leiloesnovaserrana.

Os 3 tenants são front-ends Vue.js que consomem o mesmo backend
`api.serranaleiloes.com.br`. A página estática é um `<div id="app">`
quase vazio — Playwright é obrigatório.

Tudo que difere de um spider para o outro é o `name`, `provider_slug`
e `auctioneer_slug`. A lógica de extração é idêntica: o Vue popula
páginas `/lote/<id>` com markup HTML estável (não SSR mas
post-render).

Gap no genérico:
  - O `_LOT_PATH_PATTERNS` aceita `/lotes/<id>` (plural), que neste
    SPA é a página da **leilão** (lista de lotes), não do lote
    individual. Filtramos isso.
  - O `_LOT_PATH_PATTERNS` correto seria `/lote/<id>` (singular),
    o que já é coberto pelo regex de lote do genérico (lote[s]? mais
    dígitos). Mas o spider genérico ainda confundia listing com
    detail. Aqui
    descartamos URLs que casam `/lotes/<id>` no `parse_listing_fallback`.
"""
from __future__ import annotations

import re

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider

_LOTES_LISTING_RE = re.compile(r"/lotes/\d+(?:[/?]|$)")


class SerranaApiBaseSpider(ProprioHtmlSpider):
    """Não setar `name` concreto — subclasses (lorrana, leonardoveiga,
    leiloesnovaserrana) setam name/slug. Damos um name fictício pra
    evitar conflito com `proprio_html` herdado."""

    name = "_serrana_api_base_abstract"  # nunca rodar via crawl direto

    # Markup `/lotes/<id>` na verdade é página de leilão (listing),
    # não detalhe. Sobrescreve `_extract_lot_links` para filtrar.
    def _extract_lot_links(self, response, host):
        links = super()._extract_lot_links(response, host)
        return [u for u in links if not _LOTES_LISTING_RE.search(u)]
