"""Spider para o cluster Nuxt de leiloesjudiciais.com.br.

Família de subdomínios state-specific compartilhando a mesma base via
Nuxt 3 SSR. Recon: specs/_providers/leiloes_judiciais_br/.

NOTA: o agrupamento `_input.json` lista 30 sites mas ~25 são plataformas
distintas (Giordano MVC legacy etc.). Este spider cobre apenas o
cluster Nuxt canônico (leiloesjudiciais.com.br + leiloesjudiciaisXX.com.br).

Estratégia:
  1. /imoveis (lista paginada)
  2. div.base-card → href /lote/{leilao_id}/{lot_id}
  3. Detail page é SSR puro — extrai do HTML.

Particularidade Nuxt: __NUXT_DATA__ JSON inline traz o dump completo
do lote. Spider tenta primeiro o JSON; cai no DOM se falhar.

Uso:
    scrapy crawl leiloes_judiciais_br -a sites=1
    scrapy crawl leiloes_judiciais_br -a sites=all
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

import scrapy

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _BRL_RE,
    _brl_to_decimal,
    _detail_is_imovel,
    _dedup_clauses,
    _extract_auctioneer,
    _find_edital_url,
    _normalize_text,
    _parse_auction_clauses,
    _pdf_to_text,
)


class LeiloesJudiciaisBrSpider(ProviderSpider):
    name = "leiloes_judiciais_br"
    provider_slug = "leiloes_judiciais_br"
    auctioneer_slug = "leiloes_judiciais_br"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
    }

    LOT_HREF_RE = re.compile(r"/lote/(\d+)/(\d+)")

    # ------------------------------------------------------------------
    # Nível 1: home → /imoveis
    # ------------------------------------------------------------------
    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        listing_url = response.urljoin("/imoveis")
        yield self.make_request(
            listing_url,
            callback=self.parse_listing,
            meta={"page": 1, "host": self.host_of(response.url)},
        )

    def parse_listing(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        seen: set[str] = set()
        kept = 0
        for card in response.css("div.base-card, article.base-card"):
            href = card.css("a[href^='/lote/']::attr(href)").get()
            if not href or not self.LOT_HREF_RE.search(href):
                continue
            absolute = response.urljoin(href)
            if absolute in seen:
                continue
            seen.add(absolute)
            kept += 1
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url},
            )

        page = response.meta.get("page", 1)
        self.log_event("ljb_listing_done", url=response.url, page=page, kept=kept)

        # Paginação via ?pagina=N (robots.txt desencoraja, mas é único
        # caminho sem sitemap parser)
        if kept > 0:
            next_url = re.sub(r"\?.*$", "", response.url) + f"?pagina={page + 1}"
            yield self.make_request(
                next_url,
                callback=self.parse_listing,
                meta={"page": page + 1, "host": response.meta["host"]},
            )

    # ------------------------------------------------------------------
    # Nível 2: detail → PropertyItem
    # ------------------------------------------------------------------
    def parse_property(self, response: scrapy.http.Response):
        # Filtro de imóvel — usa h1+breadcrumb
        h1 = (response.css("h1::text").get() or "").strip()
        og_title = response.css("meta[property='og:title']::attr(content)").get() or h1
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""
        # meta description traz a sinopse real do lote — confiável para
        # filtro mesmo quando body_blob começa pelo menu.
        meta_desc = response.css("meta[name='description']::attr(content)").get() or ""
        # Body blob: precisamos ir além do menu (que ocupa ~1500 chars).
        body_blob = " ".join(response.css("body *::text").getall())[:8000]
        if not _detail_is_imovel(og_title or h1, " ".join([og_desc, meta_desc, body_blob[:2000]])):
            self.log_event(
                "ljb_lote_dropped_non_imovel",
                url=response.url,
                title=og_title[:80],
            )
            return

        loader = self.new_loader(response)
        host = self.host_of(response.url)
        auctioneer = _extract_auctioneer(response)
        if auctioneer and auctioneer.get("full_name"):
            loader.replace_value("auctioneer", auctioneer["full_name"])
            loader.add_value("auctioneer_data", auctioneer)
        else:
            loader.replace_value("auctioneer", f"leiloes_judiciais_br::{host}")

        # source_lot_code do path /lote/{leilao_id}/{lot_id}
        m_lot = self.LOT_HREF_RE.search(response.url)
        if m_lot:
            loader.add_value("source_lot_code", m_lot.group(2))

        # Title
        if h1:
            loader.add_value("title", h1)

        # status: heurística sobre badge + texto
        body_text_lower = body_blob.lower()
        if "arrematado" in body_text_lower:
            status = "arrematado"
        elif "encerrad" in body_text_lower or "finalizad" in body_text_lower:
            status = "desconhecido"
        elif "suspens" in body_text_lower:
            status = "suspenso"
        elif "cancel" in body_text_lower:
            status = "cancelado"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Avaliação — div.vl-avaliacao traz "Avaliação:" + "R$ ..."
        av_text = " ".join(response.css(
            "div.vl-avaliacao *::text, div[class*='vl-avaliacao'] *::text"
        ).getall())
        m_av = re.search(r"R\$\s*([\d.,]+)", av_text)
        if m_av:
            try:
                loader.add_value("market_value", str(_brl_to_decimal(m_av.group(1))))
            except Exception:
                pass

        # Lance mínimo — button.vl-minimo
        min_text = " ".join(response.css(
            "button.vl-minimo *::text, .vl-minimo *::text, "
            ".lance-minimo *::text, .vl-lance-minimo *::text"
        ).getall())
        m_min = re.search(r"R\$\s*([\d.,]+)", min_text)
        if m_min:
            try:
                loader.add_value("minimum_bid", str(_brl_to_decimal(m_min.group(1))))
            except Exception:
                pass

        # Fallback regex em body_blob caso DOM não tenha ainda esses divs
        if not m_av:
            m_av_fb = re.search(r"avalia[çc][ãa]o[^R]{0,40}R\$\s*([\d.,]+)", body_blob, re.I)
            if m_av_fb:
                try:
                    loader.add_value("market_value", str(_brl_to_decimal(m_av_fb.group(1))))
                except Exception:
                    pass
        if not m_min:
            m_min_fb = re.search(r"(?:lance|valor)\s+(?:m[íi]nimo|inicial)[^R]{0,40}R\$\s*([\d.,]+)", body_blob, re.I)
            if m_min_fb:
                try:
                    loader.add_value("minimum_bid", str(_brl_to_decimal(m_min_fb.group(1))))
                except Exception:
                    pass

        # Data: tenta encontrar DD/MM/YYYY HH:MM no body
        m_dt = re.search(r"(\d{2}/\d{2}/\d{4})[^,<]{0,8}(\d{2}:\d{2})", body_blob)
        if m_dt:
            loader.add_value("second_auction_date",
                             f"{m_dt.group(1)} {m_dt.group(2)}")
            loader.add_value("auction_phase", "2a_praca")

        # Description: tentar bloco de descrição via classe Vue/Nuxt
        desc_nodes = response.css(
            "div.descricao *::text, "
            "section.descricao *::text, "
            "div[class*='descricao'] *::text"
        )
        desc = _normalize_text(" ".join(desc_nodes.getall()))
        if not desc or len(desc) < 30:
            # Fallback: se há um __NUXT_DATA__ JSON inline, tenta parsear
            nuxt_match = re.search(r"<script\s+id=\"__NUXT_DATA__\"[^>]*>(.+?)</script>", response.text, re.S)
            if nuxt_match:
                try:
                    nuxt = json.loads(nuxt_match.group(1))
                    desc = _extract_description_from_nuxt(nuxt)
                except Exception:
                    pass
        if desc:
            loader.add_value("description", desc[:10000])

        # Endereço — extrai cidade/UF do body
        addr_text = body_blob
        m_addr = re.search(r"([A-ZÀ-Úa-zà-ú\s.'-]+?)\s*[/-]\s*([A-Z]{2})\b", addr_text)
        if m_addr:
            cidade = m_addr.group(1).strip().rstrip(",-").strip()
            if 3 <= len(cidade) <= 50 and not re.search(r"\d", cidade):
                loader.add_value("address", {
                    "raw_text": addr_text[:300],
                    "municipality_name": cidade,
                    "uf": m_addr.group(2).upper(),
                })

        # Imagens — S3 sa-east-1
        img_urls = response.css(
            "img[src*='s3.sa-east-1.amazonaws.com']::attr(src), "
            "img[src*='/public/fotos/imoveis/']::attr(src)"
        ).getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            if not u:
                continue
            absolute = response.urljoin(u)
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs)

        # Documentos
        docs: list[dict] = []
        seen_doc_urls: set[str] = set()
        for a in response.css("a[href*='/public/anexo/'][href$='.pdf'], a[href$='.pdf']"):
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
        page_text = _normalize_text(" ".join(response.css("body *::text").getall()))
        payment_options, encumbrances = _parse_auction_clauses(page_text)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "ljb_lote_extracted",
            url=response.url,
            host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
        )
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


def _extract_description_from_nuxt(nuxt: Any) -> str:
    """__NUXT_DATA__ é um array compactado; varre recursivamente buscando
    chave 'descricao' ou similar. Retorna string ou ''."""
    seen = set()

    def walk(obj):
        if id(obj) in seen:
            return None
        seen.add(id(obj))
        if isinstance(obj, dict):
            for k in ("descricao", "descricaoCompleta", "description"):
                if isinstance(obj.get(k), str) and len(obj[k]) > 30:
                    return obj[k]
            for v in obj.values():
                r = walk(v)
                if r:
                    return r
        elif isinstance(obj, list):
            for v in obj:
                r = walk(v)
                if r:
                    return r
        return None

    result = walk(nuxt) or ""
    return _normalize_text(re.sub(r"<[^>]+>", " ", result))
