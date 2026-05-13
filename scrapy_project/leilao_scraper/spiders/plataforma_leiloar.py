"""Spider para o SaaS Plataforma Leiloar.

21 tenants em data/intermediate/site_providers.csv compartilham o
sistema "externo" do leiloar — domínio próprio (`*.com.br`) com path
`/externo/` que serve as páginas server-side em HTML estático.

Padrão:
  - Home `/externo/`: lista cards de leilões via `<a href="/externo/leilao/{id}">`.
  - Página do leilão: lista lotes via `<a href="/externo/lote/{id}/{slug}">`.
  - Detail do lote: texto direto com "1º Leilão: R$ N", "2º Leilão: R$ N",
    "AVALIAÇÃO: R$ N", "Incremento: R$ N". PDF do edital em
    `/externo/bens/../../arquivos/arquivos_leilao/*.pdf`.

Uso:
    scrapy crawl plataforma_leiloar -a sites=1
    scrapy crawl plataforma_leiloar -a sites=all
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


_AUCTION_HREF_RE = re.compile(r"/externo/leilao/(\d+)")
_LOT_HREF_RE = re.compile(r"/externo/lote/(\d+)")
_PRICE_1A = re.compile(r"1[ºº°]?\s*Leil[ãa]o[:\s]*R\$\s*([\d.,]+)", re.I)
_PRICE_2A = re.compile(r"2[ºº°]?\s*Leil[ãa]o[:\s]*R\$\s*([\d.,]+)", re.I)
_PRICE_AV = re.compile(r"AVALIA[ÇC][ÃA]O[^R]{0,200}R\$\s*([\d.,]+)", re.I | re.S)
# Fallback: alguns tenants usam "Lance inicial" / "Lance mínimo" quando há
# praça única ou venda direta (sem 1ª/2ª praça nomeada). Santos Moraes usa
# "LANCE MÍNIMO" em caixa alta — case-insensitive captura ambos.
_PRICE_LANCE_INICIAL = re.compile(
    r"Lance\s+(?:inicial|m[íi]nimo)[:\s]*R\$\s*([\d.,]+)", re.I
)
# "Este lote se encerrará no dia: DD/MM/YYYY às HH:MM:SS" — padrão de
# venda direta (Santos Moraes, e tenants similares).
_DATE_ENCERRA = re.compile(
    r"(?:Este\s+lote\s+se\s+encerrar[áa]?\s+no\s+dia[:\s]*|Data\s+do\s+Leil[ãa]o[:\s]*)"
    r"(\d{2}/\d{2}/\d{4})\s*(?:[àa]s|-)?\s*(\d{2}:\d{2})(?::\d{2})?",
    re.I,
)


class PlataformaLeiloarSpider(ProviderSpider):
    name = "plataforma_leiloar"
    provider_slug = "plataforma_leiloar"
    auctioneer_slug = "plataforma_leiloar"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
    }

    MAX_PAGES_PER_HOST = 30

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._host_seen: dict[str, set[str]] = {}

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        seen = self._host_seen.setdefault(host, set())
        # Se a URL inicial já é a home, redireciona pra /externo/
        if "/externo" not in response.url:
            yield self.make_request(
                response.urljoin("/externo/"),
                callback=self.parse,
                meta={"host": host},
                dont_filter=True,
            )
            return

        kept = 0
        for href in response.css("a[href*='/externo/leilao/']::attr(href)").getall():
            if not _AUCTION_HREF_RE.search(href):
                continue
            absolute = response.urljoin(href)
            if self.host_of(absolute) != host:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            kept += 1
            yield self.make_request(
                absolute,
                callback=self.parse_auction,
                meta={"host": host},
            )
        self.log_event("pl_home_done", host=host, auctions_kept=kept)

    def parse_auction(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = response.meta["host"]
        seen = self._host_seen.setdefault(host, set())
        kept = 0
        for href in response.css("a[href*='/externo/lote/']::attr(href)").getall():
            if not _LOT_HREF_RE.search(href):
                continue
            absolute = response.urljoin(href)
            if self.host_of(absolute) != host:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            kept += 1
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url, "host": host},
            )
        self.log_event("pl_auction_done", url=response.url, lots_kept=kept)

    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("host", self.host_of(response.url))
        og_title = response.css("meta[property='og:title']::attr(content)").get() or ""
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""
        # og:title vem como "Tenant Leilões | TITULO" — extrai TITULO
        if "|" in og_title:
            og_title = og_title.split("|", 1)[1].strip()

        # Body text limpo
        body_text = _normalize_text(" ".join(response.css("body *::text").getall()))
        if not _detail_is_imovel(og_title, og_desc + " " + body_text[:2000]):
            self.log_event("pl_lote_dropped_non_imovel", url=response.url,
                           title=og_title[:80])
            return

        loader = self.new_loader(response)
        auctioneer = _extract_auctioneer(response)
        if auctioneer and auctioneer.get("full_name"):
            loader.replace_value("auctioneer", auctioneer["full_name"])
            loader.add_value("auctioneer_data", auctioneer)
        else:
            loader.replace_value("auctioneer", f"plataforma_leiloar::{host}")

        m_lot = _LOT_HREF_RE.search(response.url)
        if m_lot:
            loader.add_value("source_lot_code", m_lot.group(1))

        if og_title:
            loader.add_value("title", og_title.strip())

        # Description — primeiros 2000 chars úteis (pula menu)
        # O sistema sempre coloca a sinopse após "Descrição"
        desc = ""
        m_desc = re.search(r"Descrição\s*(.+?)(?:Lance|Pra ça|AVALIAÇÃO|Incremento|$)",
                           body_text, re.I | re.S)
        if m_desc:
            desc = m_desc.group(1).strip()[:10000]
        if not desc:
            desc = og_desc or body_text[:2000]
        if desc:
            loader.add_value("description", desc[:10000])

        # status — sidebar do leiloar tem checkboxes com TODOS os status
        # possíveis ("CANCELADO", "ABERTO", etc.), então não dá pra usar
        # heurística por substring. Default = aberto; refinamos com
        # markers específicos que aparecem só quando o lote efetivamente
        # tem aquele estado.
        if re.search(r"Lance\s+vencedor|ARREMATAD[OA]\b", body_text, re.I):
            status = "arrematado"
        elif re.search(r"\bLEIL[ÃA]O\s+SUSPENSO\b", body_text, re.I):
            status = "suspenso"
        elif re.search(r"\bLEIL[ÃA]O\s+CANCELAD[OA]\b|\bLOTE\s+CANCELAD[OA]\b",
                       body_text, re.I):
            status = "cancelado"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Preços: pega 2º leilão como min_bid (mais baixo) e avaliação
        m_min = _PRICE_2A.search(body_text) or _PRICE_1A.search(body_text) \
            or _PRICE_LANCE_INICIAL.search(body_text)
        if m_min:
            try:
                loader.add_value("minimum_bid", str(_brl_to_decimal(m_min.group(1))))
            except Exception:
                pass

        m_av = _PRICE_AV.search(body_text)
        if m_av:
            try:
                loader.add_value("market_value", str(_brl_to_decimal(m_av.group(1))))
            except Exception:
                pass

        # Data: prioriza labels específicos ("Este lote se encerrará", "Data do
        # Leilão"); fallback genérico para DD/MM/YYYY HH:MM no body.
        m_dt_label = _DATE_ENCERRA.search(body_text)
        if m_dt_label:
            loader.add_value(
                "second_auction_date",
                f"{m_dt_label.group(1)} {m_dt_label.group(2)}",
            )
            loader.add_value("auction_phase", "2a_praca")
        else:
            m_dt = re.search(r"(\d{2}/\d{2}/\d{4})[^,<]{0,10}(\d{2}:\d{2})", body_text)
            if m_dt:
                loader.add_value("second_auction_date", f"{m_dt.group(1)} {m_dt.group(2)}")
                loader.add_value("auction_phase", "2a_praca")

        # Endereço — tenta extrair "em CIDADE/UF" do título ou body
        m_cuf = re.search(r"\bem\s+([A-ZÀ-Úa-zà-ú\s.'-]{3,40})/([A-Z]{2})\b", og_title)
        if not m_cuf:
            m_cuf = re.search(r"\b([A-ZÀ-Ú][A-Za-zÀ-ú\s.'-]{2,40}?)/([A-Z]{2})\b", body_text)
        addr: dict[str, Any] = {"raw_text": og_title[:300]}
        if m_cuf:
            addr["municipality_name"] = m_cuf.group(1).strip().title()
            addr["uf"] = m_cuf.group(2).upper()
        if any(v for v in addr.values()):
            loader.add_value("address", addr)

        # Imagens — /arquivos/icones/
        img_urls = response.css(
            "img[src*='/arquivos/icones/']::attr(src), "
            "img[src*='/arquivos/lotes/']::attr(src), "
            "img[src*='/arquivos/']::attr(src)"
        ).getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            if not u:
                continue
            absolute = response.urljoin(u)
            low = absolute.lower()
            if any(skip in low for skip in ("logo", "favicon", "bandeira", "/styles/")):
                continue
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs)

        # Documentos
        docs: list[dict] = []
        seen_doc_urls: set[str] = set()
        for a in response.css("a[href$='.pdf']"):
            url = a.css("::attr(href)").get()
            label = _normalize_text(" ".join(a.css("*::text").getall())) or None
            if not url:
                continue
            abs_url = response.urljoin(url)
            if abs_url in seen_doc_urls:
                continue
            seen_doc_urls.add(abs_url)
            docs.append({"name": label or "documento", "url": abs_url})
        if docs:
            loader.add_value("documents", docs)

        # Cláusulas
        payment_options, encumbrances = _parse_auction_clauses(body_text)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event("pl_lote_extracted", url=response.url, host=host,
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
