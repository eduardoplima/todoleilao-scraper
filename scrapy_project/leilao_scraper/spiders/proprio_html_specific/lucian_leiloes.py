"""Lucian Leilões (www.lucianleiloes.com.br) — 12 lotes na baseline.

Gaps no genérico:
  - `market_value`: o body diz "Total da avaliação R$ X" (Total **antes**
    de Avaliação). A regex universal `_PRICE_AVALIACAO` espera
    `Avaliação (Judicial|Total)? R$` — não casa "Total da avaliação".
  - `images`: a maioria dos lotes não tem foto (markup mostra
    `/sem-imagem.png`). Não é gap; é dado real.
"""
from __future__ import annotations

import re

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider
from leilao_scraper.spiders.soleon import _brl_to_decimal


_RE_TOTAL_DA_AVALIACAO = re.compile(
    r"Total\s+(?:da|do)\s+avalia[çc][ãa]o\s*R\$\s*([\d.,]+)", re.I,
)


class LucianLeiloesSpider(ProprioHtmlSpider):
    name = "lucian_leiloes"
    provider_slug = "lucian_leiloes"
    auctioneer_slug = "lucian_leiloes"

    def _fixup_item(self, item, response, *, body_text: str, host: str) -> None:
        if not item.get("market_value"):
            m = _RE_TOTAL_DA_AVALIACAO.search(body_text)
            if m:
                try:
                    v = _brl_to_decimal(m.group(1))
                    if v and v > 0:
                        item["market_value"] = str(v)
                except Exception:
                    pass
