"""Alfa Leilões (www.alfaleiloes.com) — 14 lotes na baseline.

Gaps relevantes sobre o genérico:

1. Documentos: `a[href$='.pdf']` não casa porque Alfa hospeda editais em S3
   com signed URLs `...Edital.pdf?X-Amz-Signature=...`. Coleta via helper
   que ignora a query string.

2. Preços: o template Alfa renderiza um carrossel de "lotes relacionados"
   (`div.card-lances`) na MESMA página do lote. Cada card mostra
   `LANCE MÍNIMO: R$ X` de OUTRO lote. Quando o spider varre `body_text`
   inteiro, o regex pode casar com o card antes de chegar no bloco
   principal — produzindo lotes com `minimum_bid` ~ R$ 20-80k para imóveis
   de R$ milhões (bug observado em produção: 10/12 lotes ruins do site
   eram alfa). Override de `_fixup_item` re-extrai preços escopados ao
   container `div.lote-wrapper` quando ele existe.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider
from leilao_scraper.spiders.proprio_html_specific._common import (
    collect_pdfs_with_query,
)
from leilao_scraper.spiders.soleon import _brl_to_decimal


_PRICE_AVALIACAO_SCOPED = re.compile(
    r"(?:Valor\s+da\s+)?Avalia[çc][ãa]o[^\d]*R\$\s*([\d.,]+)", re.I,
)
_PRICE_LANCE_MIN_SCOPED = re.compile(
    r"Lance\s+M[íi]nimo[^\d]*R\$\s*([\d.,]+)", re.I,
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

        # 1) Re-extrai preços escopados ao bloco principal do lote.
        # `div.lote-wrapper` contém os <strong> com "Valor da Avaliação"
        # e "Lance Mínimo" do lote atual; o carrossel lateral fica fora.
        wrapper_text = " ".join(
            response.css("div.lote-wrapper *::text").getall()
        )
        wrapper_text = re.sub(r"\s+", " ", wrapper_text).strip()
        if wrapper_text:
            m_av = _PRICE_AVALIACAO_SCOPED.search(wrapper_text)
            if m_av:
                try:
                    v = _brl_to_decimal(m_av.group(1))
                    if v and v > 0:
                        item["market_value"] = str(v)
                except Exception:
                    pass
            m_min = _PRICE_LANCE_MIN_SCOPED.search(wrapper_text)
            if m_min:
                try:
                    v = _brl_to_decimal(m_min.group(1))
                    if v and v > 0:
                        item["minimum_bid"] = str(v)
                except Exception:
                    pass

        # 2) Defesa contra cards de lotes relacionados: se o minimum_bid
        # atual aparece em algum `div.card-lances` (carrossel de outros
        # lotes), o valor é contaminação — limpa pra pipeline rotular.
        mb = item.get("minimum_bid")
        if mb:
            cards_text = " ".join(
                response.css("div.card-lances *::text").getall()
            )
            try:
                mb_decimal = Decimal(str(mb))
                for m in re.finditer(r"R?\$?\s*([\d.,]+)", cards_text):
                    try:
                        card_val = _brl_to_decimal(m.group(1))
                    except Exception:
                        continue
                    if card_val and card_val == mb_decimal:
                        # Veio do carrossel — não confiável.
                        item["minimum_bid"] = None
                        break
            except Exception:
                pass
