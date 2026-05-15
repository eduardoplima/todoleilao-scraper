"""Nosso Leilão (nossoleilao.com.br) — mesma plataforma que Rico Leilões.

URL pattern `/item/{id}/detalhes` e `/leilao/{id}/lotes`. Reusa
heurísticas do RicoLeiloesSpider. v1 não filtra apenas imóveis (porque
o tenant raramente expõe imóveis ativos); spider deixa o filtro de
imóvel acontecer no parse_property via `_RE_IMOVEL`.

Estratégia: começa do home (que lista TODOS os leilões), segue cada
`/leilao/N/lotes` e processa os itens com filtro de imóvel.
"""
from __future__ import annotations

from typing import Iterable
import re

import scrapy

from leilao_scraper.spiders.proprio_html_specific.ricoleiloes import (
    RicoLeiloesSpider,
    _ITEM_HREF_RE,
)


_LEILAO_HREF_RE = re.compile(r"/leilao/(\d+)/lotes")


class NossoLeilaoSpider(RicoLeiloesSpider):
    name = "nossoleilao"
    auctioneer_slug = "nossoleilao"
    start_urls = [
        "https://www.nossoleilao.com.br/",
    ]

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        # 1) Tenta achar /item/{id}/detalhes diretamente (caso lotes/imovel
        #    funcione no futuro).
        kept_items = 0
        for href in response.css("a::attr(href)").getall():
            m = _ITEM_HREF_RE.search(href or "")
            if not m:
                continue
            item_id = m.group(1)
            if item_id in self._seen_items:
                continue
            self._seen_items.add(item_id)
            kept_items += 1
            yield scrapy.Request(
                response.urljoin(href),
                callback=self.parse_property,
                meta={"source_listing_url": response.url, "source_lot_code": item_id},
            )

        # 2) Se for home/categoria que só tem leilões, segue cada leilão.
        if kept_items == 0:
            leilao_ids: set[str] = set()
            for href in response.css("a::attr(href)").getall():
                m = _LEILAO_HREF_RE.search(href or "")
                if m:
                    leilao_ids.add(m.group(1))
            self.log_event(
                "nl_home_leiloes", url=response.url, count=len(leilao_ids),
            )
            for leilao_id in leilao_ids:
                yield scrapy.Request(
                    response.urljoin(f"/leilao/{leilao_id}/lotes"),
                    callback=self.parse,
                    meta={"source_listing_url": response.url},
                )
        else:
            self.log_event("nl_listing_done", url=response.url, kept=kept_items)
