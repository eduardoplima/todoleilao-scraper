"""Spider para Mega Leilões.

2 sites em data/intermediate/site_providers.csv:
  - https://www.megaleiloes.com.br/
  - https://www.megaleiloes.com.br/ms (segmento Mato Grosso do Sul)

URL canônica do lote (rica):
  /imoveis/{categoria}/{uf}/{cidade}/{slug}-{code}
  onde code = j######  (judicial) ou x######  (extrajudicial)

Listagem por categoria em /imoveis/{categoria}, paginação ?page=N.

Detail page é server-side e traz no body:
  - "Valor inicial R$ N"           — 2ª praça (40% abaixo da avaliação)
  - "Valor de Avaliação R$ N"      — avaliação
  - "1ª Praça: DD/MM/YYYY às HH:MM"
  - "2ª Praça: DD/MM/YYYY às HH:MM"
  - Imagens em cdn1.megaleiloes.com.br/batches/{code}/*.jpg
  - PDFs (edital, laudo, matrícula) no mesmo CDN

Uso:
    scrapy crawl mega_leiloes -a sites=1
    scrapy crawl mega_leiloes -a sites=all
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import scrapy

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _detail_is_imovel,
    _dedup_clauses,
    _extract_auctioneer,
    _find_edital_url,
    _normalize_text,
    _parse_auction_clauses,
    _pdf_to_text,
)


_LOT_URL_RE = re.compile(r"/imoveis/[^/]+/[a-z]{2}/[^/]+/[^?]+-([jxJX]\d+)")
_VALOR_AVAL_RE = re.compile(r"Valor\s+de\s+Avalia[çc][ãa]o[^R]{0,30}R\$\s*([\d.,]+)", re.I)
_VALOR_INI_RE = re.compile(r"Valor\s+inicial[^R]{0,30}R\$\s*([\d.,]+)", re.I)
_PRACA_1A_RE = re.compile(
    r"1[ªa]?\s*Pra[çc]a[:\s]*(\d{2}/\d{2}/\d{4})\s*[àa]s\s*(\d{2}:\d{2})", re.I
)
_PRACA_2A_RE = re.compile(
    r"2[ªa]?\s*Pra[çc]a[:\s]*(\d{2}/\d{2}/\d{4})\s*[àa]s\s*(\d{2}:\d{2})", re.I
)
# Extrajudicial (x-codes): sem "Praça", usa "Início:" e "Data:" no painel
# da instância ativa. Início = abertura do leilão, Data = encerramento.
# IMPORTANTE: o detail page tem cards de "outros lotes" abaixo com os
# mesmos rótulos; filtramos restringindo a busca ao bloco antes do
# carrossel de relacionados.
_INICIO_RE = re.compile(
    r"In[íi]cio\s*:\s*(\d{2}/\d{2}/\d{4})\s*[àa]s\s*(\d{2}:\d{2})", re.I
)
_DATA_LABEL_RE = re.compile(
    r"\bData\s*:\s*(\d{2}/\d{2}/\d{4})\s*[àa]s\s*(\d{2}:\d{2})", re.I
)
# Marker do início da seção "outros lotes": col-sm-6 col-md-4 col-lg-3
# (grid de cards). Antes disso, tudo pertence ao lote atual.
_RELATED_LOTS_MARKER = 'class="col-sm-6 col-md-4 col-lg-3"'


# Mapping de slug → unit_kind (parcial; SQL classify_lot_kind cobre o resto)
_CATEGORIA_TO_KIND = {
    "apartamentos": "apartamento",
    "casas": "casa",
    "terrenos-e-lotes": "terreno_urbano",
    "imoveis-rurais": "rural",
    "imoveis-comerciais": "comercial",
    "salas-comerciais": "sala_comercial",
    "galpoes": "galpao",
    "predios": "predio_inteiro",
}


class MegaLeiloesSpider(ProviderSpider):
    name = "mega_leiloes"
    provider_slug = "mega_leiloes"
    auctioneer_slug = "mega_leiloes"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
    }

    MAX_PAGES_PER_CAT = 30
    CATEGORIES = [
        "apartamentos",
        "casas",
        "terrenos-e-lotes",
        "imoveis-rurais",
        "imoveis-comerciais",
        "salas-comerciais",
        "galpoes",
        "predios",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._host_seen: dict[str, set[str]] = {}

    def start_requests(self) -> Iterable[scrapy.Request]:
        self._open_incremental_db()
        yield from super().start_requests()

    def closed(self, reason: str) -> None:
        self.close_incremental_db()

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        # Dispatcha listing por categoria
        for cat in self.CATEGORIES:
            yield self.make_request(
                response.urljoin(f"/imoveis/{cat}"),
                callback=self.parse_listing,
                meta={"host": host, "category": cat, "page": 1},
            )

    def parse_listing(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = response.meta["host"]
        cat = response.meta["category"]
        seen = self._host_seen.setdefault(host, set())
        kept = 0
        for href in response.css("a[href*='/imoveis/']::attr(href)").getall():
            if not _LOT_URL_RE.search(href):
                continue
            # tira utm_*; usa URL canônica
            absolute = response.urljoin(href.split("?")[0])
            if self.host_of(absolute) != host:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            kept += 1
            m_code = _LOT_URL_RE.search(absolute)
            lot_code = m_code.group(1).upper() if m_code else None
            if lot_code and self.lot_exists(host, lot_code):
                yield self.make_listing_only_item(
                    url=absolute,
                    source_lot_code=lot_code,
                    auctioneer=f"mega_leiloes::{host}",
                )
                continue
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url, "host": host,
                      "category": cat},
            )
        page = response.meta.get("page", 1)
        self.log_event("ml_listing_done", host=host, category=cat, page=page,
                       kept=kept)
        # Paginação
        if kept > 0 and page < self.MAX_PAGES_PER_CAT:
            base = response.url.split("?")[0]
            yield self.make_request(
                f"{base}?page={page + 1}",
                callback=self.parse_listing,
                meta={"host": host, "category": cat, "page": page + 1},
            )

    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("host", self.host_of(response.url))
        category = response.meta.get("category", "")

        og_title = response.css("meta[property='og:title']::attr(content)").get() or ""
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""
        h1 = (response.css("h1::text").get() or "").strip()
        title = h1 or og_title

        body_text = _normalize_text(" ".join(response.css("body *::text").getall()))
        if not _detail_is_imovel(title, og_desc + " " + body_text[:2000]):
            self.log_event("ml_lote_dropped_non_imovel", url=response.url,
                           title=title[:80])
            return

        loader = self.new_loader(response)
        auctioneer = _extract_auctioneer(response)
        if auctioneer and auctioneer.get("full_name"):
            loader.replace_value("auctioneer", auctioneer["full_name"])
            loader.add_value("auctioneer_data", auctioneer)
        else:
            loader.replace_value("auctioneer", f"mega_leiloes::{host}")

        m_code = _LOT_URL_RE.search(response.url)
        if m_code:
            loader.add_value("source_lot_code", m_code.group(1).upper())

        if title:
            loader.add_value("title", title.strip())

        # property_type via categoria
        kind = _CATEGORIA_TO_KIND.get(category)
        if kind:
            from leilao_scraper.spiders.degrau_publicidade import _kind_to_property_type
            loader.add_value("property_type", _kind_to_property_type(kind))

        # description — bloco específico ou og_desc
        desc_block = " ".join(response.css(
            "div.descricao *::text, "
            "section#descricao *::text, "
            "div[class*='descricao'] *::text"
        ).getall())
        desc = _normalize_text(desc_block) or og_desc
        if desc:
            loader.add_value("description", desc[:10000])

        # status — div.card-status contém badge oficial ("Aberto para
        # lances", "Encerrado", "Arrematado"). Edital traz a palavra
        # "arrematado" como adjetivo em condições gerais, então regex
        # genérico no body inteiro produz falso positivo.
        status_badge = (response.css("div.card-status::text").get() or "").strip().lower()
        if "arrematad" in status_badge:
            status = "arrematado"
        elif "encerrad" in status_badge or "finalizad" in status_badge:
            status = "desconhecido"
        elif "suspens" in status_badge:
            status = "suspenso"
        elif "cancelad" in status_badge:
            status = "cancelado"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Preços
        m_av = _VALOR_AVAL_RE.search(body_text)
        if m_av:
            try:
                v = _brl_to_decimal(m_av.group(1))
                # Sites publicam "R$ 0,00" quando avaliação não foi informada
                if v and v > 0:
                    loader.add_value("market_value", str(v))
            except Exception:
                pass

        m_min = _VALOR_INI_RE.search(body_text)
        if m_min:
            try:
                loader.add_value("minimum_bid", str(_brl_to_decimal(m_min.group(1))))
            except Exception:
                pass

        # Praças — 2 templates:
        #   judicial (j-codes): "1ª Praça: DD/MM/YYYY às HH:MM" e
        #                       "2ª Praça: DD/MM/YYYY às HH:MM" no corpo
        #   extrajudicial (x-codes): "Início: DD/MM/YYYY às HH:MM" (abertura)
        #                            "Data: DD/MM/YYYY às HH:MM" (encerramento)
        # Para extrajudicial, restringir ao detail block antes do carrossel
        # de lotes relacionados (que repete labels "Data:" para outros lots).
        m_1a = _PRACA_1A_RE.search(body_text)
        m_2a = _PRACA_2A_RE.search(body_text)
        if m_1a:
            loader.add_value("first_auction_date",
                             f"{m_1a.group(1)} {m_1a.group(2)}")
        if m_2a:
            loader.add_value("second_auction_date",
                             f"{m_2a.group(1)} {m_2a.group(2)}")
            loader.add_value("auction_phase", "2a_praca")
        elif m_1a:
            loader.add_value("auction_phase", "1a_praca")

        # Fallback extrajudicial: Início: + Data: no detail block
        if not (m_1a or m_2a):
            detail_html = response.text
            cut = detail_html.find(_RELATED_LOTS_MARKER)
            detail_html = detail_html[:cut] if cut > 0 else detail_html
            detail_text = _normalize_text(re.sub(r"<[^>]+>", " ", detail_html))
            m_inicio = _INICIO_RE.search(detail_text)
            m_data = _DATA_LABEL_RE.search(detail_text)
            if m_inicio:
                loader.add_value(
                    "first_auction_date",
                    f"{m_inicio.group(1)} {m_inicio.group(2)}",
                )
            if m_data:
                loader.add_value(
                    "second_auction_date",
                    f"{m_data.group(1)} {m_data.group(2)}",
                )
                loader.add_value("auction_phase", "2a_praca")
            elif m_inicio:
                loader.add_value("auction_phase", "1a_praca")

        # Endereço — URL traz uf+cidade, parsing direto
        m_loc = re.search(r"/imoveis/[^/]+/([a-z]{2})/([^/]+)/", response.url)
        addr: dict[str, Any] = {"raw_text": title[:300]}
        if m_loc:
            uf = m_loc.group(1).upper()
            cidade_slug = m_loc.group(2)
            cidade = cidade_slug.replace("-", " ").title()
            addr["municipality_name"] = cidade
            addr["uf"] = uf
        if any(v for v in addr.values()):
            loader.add_value("address", addr)

        # Imagens — CDN cdn{N}.megaleiloes.com.br/batches/{code}/...
        img_urls = response.css(
            "img[src*='cdn'][src*='.megaleiloes.com.br/batches/']::attr(src), "
            "img[data-mfp-src*='cdn'][data-mfp-src*='.megaleiloes.com.br/batches/']::attr(data-mfp-src)"
        ).getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            if not u:
                continue
            absolute = response.urljoin(u)
            # prefere alta resolução (_1024x768) sobre thumb (_670x380)
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs)

        # Documentos: edital, laudo, matrícula em cdn{N}/batches/{code}/
        docs: list[dict] = []
        seen_doc_urls: set[str] = set()
        for a in response.css(
            "a[href*='megaleiloes.com.br/batches/'][href$='.pdf'], "
            "a[href*='cdn'][href*='.megaleiloes.com.br'][href$='.pdf']"
        ):
            url = a.css("::attr(href)").get()
            label = _normalize_text(" ".join(a.css("*::text").getall())) or None
            if not url:
                continue
            abs_url = response.urljoin(url)
            if abs_url in seen_doc_urls:
                continue
            seen_doc_urls.add(abs_url)
            # Detecta kind do nome do arquivo
            low = abs_url.lower()
            if "edital" in low:
                label = label or "edital"
            elif "laudo" in low:
                label = label or "laudo"
            elif "matricula" in low:
                label = label or "matrícula"
            docs.append({"name": label or "documento", "url": abs_url})
        if docs:
            loader.add_value("documents", docs)

        payment_options, encumbrances = _parse_auction_clauses(body_text)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event("ml_lote_extracted", url=response.url, host=host,
                       status=item.get("status"), min_bid=item.get("minimum_bid"),
                       mkt=item.get("market_value"))
        yield item

        edital_url = _find_edital_url(item)
        if edital_url:
            yield self.make_request(
                edital_url,
                callback=self._merge_edital_clauses,
                cb_kwargs={"item_html": item},
                errback=self._on_edital_error,
                meta={"handle_httpstatus_list": [403, 404], "dont_obey_robotstxt": True},
            )

    def _on_edital_error(self, failure):
        item_html = failure.request.cb_kwargs.get("item_html")
        if item_html is not None:
            yield item_html

    def _merge_edital_clauses(self, response: scrapy.http.Response, item_html):
        if response.status >= 400:
            yield item_html
            return
        try:
            text = _pdf_to_text(response.body)
        except Exception:
            yield item_html
            return
        pdf_pay, pdf_enc = _parse_auction_clauses(text) if text else ([], [])
        if not pdf_pay and not pdf_enc:
            yield item_html
            return
        existing_pay = list(item_html.get("payment_options") or [])
        existing_enc = list(item_html.get("encumbrances") or [])
        merged_pay = _dedup_clauses(existing_pay + pdf_pay, key="kind")
        merged_enc = _dedup_clauses(existing_enc + pdf_enc, key="kind")
        if len(merged_pay) == len(existing_pay) and len(merged_enc) == len(existing_enc):
            yield item_html
            return
        new_item = item_html.copy()
        new_item["payment_options"] = merged_pay
        new_item["encumbrances"] = merged_enc
        yield new_item
