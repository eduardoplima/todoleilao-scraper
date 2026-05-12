"""Alfa Leilões (www.alfaleiloes.com) — 14 lotes na baseline.

Único gap relevante: o genérico usa `a[href$='.pdf']` para coletar
documentos, mas o Alfa hospeda editais em S3 com signed URLs do tipo
`...Edital.pdf?X-Amz-Algorithm=...&X-Amz-Signature=...` — o `$=`
não casa.

Demais campos (título, preço via `2ª Praça`, endereço, imagens,
descrição) o genérico já cobre.
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider
from leilao_scraper.spiders.proprio_html_specific._common import (
    collect_pdfs_with_query,
)


class AlfaLeiloesSpider(ProprioHtmlSpider):
    name = "alfa_leiloes"
    provider_slug = "alfa_leiloes"
    auctioneer_slug = "alfa_leiloes"

    def _fixup_item(self, item, response, *, body_text: str, host: str) -> None:
        if not item.get("documents"):
            docs = collect_pdfs_with_query(response)
            if docs:
                item["documents"] = docs
