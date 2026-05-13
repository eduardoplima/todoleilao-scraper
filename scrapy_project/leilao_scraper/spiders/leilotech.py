"""Spider para o SaaS Leilotech.

Cobre dois agrupamentos do `data/intermediate/site_providers.csv` que
são, na prática, o mesmo provedor:
  - `leilotech` (18 sites em domínios próprios — vasconcelosleiloes.com.br,
    arrematabem.com.br, lancejusto.com.br, etc.)
  - `leilao_br` (18 sites em subdomínios *.leilao.br compartilhando a
    mesma plataforma — shopleiloes.leilao.br, ferronato.leilao.br, etc.)

Marcador: CDN compartilhada `cdn.leilotech.workers.dev` e estrutura
de URL idêntica: `/leilao/{auction_id}/{slug}` (listagem do evento) →
`/lote/{lot_id}/{slug}` (detalhe).

Estratégia:
  1. Home renderiza cards de leilões ativos com links absolutos pra
     páginas `/leilao/{id}/...` (server-side, sem JS).
  2. Página de leilão lista os lotes com links pra `/lote/{id}/...`.
  3. Página de detalhe traz um JSON inline com pares
     `{"label":"Valor da avaliação:", "value":"R$ ..."}`, fácil de
     parsear via regex. PDFs do edital sob `cdn.leilotech.workers.dev`.

Uso:
    scrapy crawl leilotech -a sites=1
    scrapy crawl leilotech -a sites=all
"""
from __future__ import annotations

import html as html_lib
import re
from decimal import Decimal
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


_AUCTION_HREF_RE = re.compile(r"/leilao/(\d+)/")
_LOT_HREF_RE = re.compile(r"/lote/(\d+)/")
# Aceita aspas escapadas dentro do value (Topo Leilões emite "value":"<span
# class=\"block\">..."); o regex anterior cortava no primeiro \"  produzindo
# value truncado e regex de R$ falhando.
_LABEL_VALUE_RE = re.compile(
    r'"label":"((?:[^"\\]|\\.)+?)","value":"((?:[^"\\]|\\.){1,2000})"'
)
_BRL_PRICE_RE = re.compile(r"R\$\s*([\d.,]+)")
_PROC_RE = re.compile(r"(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})")

# Datas de praças em texto da forma "1º. LEILÃO: Qui, DD/MM/YYYY - HH:MMh
# - R$ ..." (Topo Leilões / leilotech). Captura praça + data + hora.
_LEILOTECH_PRACA_RE = re.compile(
    r"([12])[ºº°o.]?\s*\.?\s*LEIL[ÃA]O\s*:?\s*"
    r"(?:[A-Za-zãç]+,?\s*)?"  # opcional weekday "Qui, "
    r"(\d{2}/\d{2}/\d{4})\s*[-–]?\s*(\d{1,2})(?:h|:)(\d{2})?",
    re.I,
)


class LeilotechSpider(ProviderSpider):
    name = "leilotech"
    provider_slug = "leilotech"
    auctioneer_slug = "leilotech"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
    }

    MAX_PAGES_PER_HOST = 30

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._host_seen: dict[str, set[str]] = {}

    # ------------------------------------------------------------------
    # Nível 1: home → cards de leilões (server-side)
    # ------------------------------------------------------------------
    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        seen = self._host_seen.setdefault(host, set())
        kept = 0
        for href in response.css("a[href*='/leilao/']::attr(href)").getall():
            if not _AUCTION_HREF_RE.search(href):
                continue
            absolute = response.urljoin(href)
            # Aceita só /leilao/ no mesmo host (descarta CDN/parent site)
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
        # Paginação: ?page=N na home
        if kept > 0:
            page = response.meta.get("page", 1)
            if page < self.MAX_PAGES_PER_HOST:
                base = response.url.split("?")[0]
                yield self.make_request(
                    f"{base}?page={page + 1}",
                    callback=self.parse,
                    meta={"host": host, "page": page + 1},
                )
        self.log_event("lt_home_done", host=host, auctions_kept=kept,
                       page=response.meta.get("page", 1))

    # ------------------------------------------------------------------
    # Nível 2: página do leilão → lista de lotes
    # ------------------------------------------------------------------
    def parse_auction(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = response.meta["host"]
        seen = self._host_seen.setdefault(host, set())
        kept = 0
        for href in response.css("a[href*='/lote/']::attr(href)").getall():
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
        self.log_event("lt_auction_done", url=response.url, lots_kept=kept)

    # ------------------------------------------------------------------
    # Nível 3: detalhe do lote → PropertyItem
    # ------------------------------------------------------------------
    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("host", self.host_of(response.url))
        og_title = response.css("meta[property='og:title']::attr(content)").get() or ""
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""
        # og_desc vem com entidades duplamente escapadas (&amp;ccedil;)
        og_desc = html_lib.unescape(html_lib.unescape(og_desc))

        if not _detail_is_imovel(og_title, og_desc):
            self.log_event("lt_lote_dropped_non_imovel", url=response.url,
                           title=og_title[:80])
            return

        # Body unescape pra extrair JSON inline label/value
        raw = html_lib.unescape(response.text)
        pairs: dict[str, str] = {}
        for m in _LABEL_VALUE_RE.finditer(raw):
            # Decoder cobre tanto \uXXXX (unicode_escape) quanto \/ \" \\
            # (escapes JSON em literais embutidos em HTML).
            label = _decode_jsonish(m.group(1))
            value = _decode_jsonish(m.group(2))
            # Limpa HTML residual dentro do value
            value = re.sub(r"<[^>]+>", " ", value)
            value = re.sub(r"\s+", " ", value).strip()
            pairs[label.rstrip(":").strip()] = value

        loader = self.new_loader(response)
        auctioneer = _extract_auctioneer(response)
        if auctioneer and auctioneer.get("full_name"):
            loader.replace_value("auctioneer", auctioneer["full_name"])
            loader.add_value("auctioneer_data", auctioneer)
        else:
            loader.replace_value("auctioneer", f"leilotech::{host}")

        # source_lot_code da URL
        m_lot = _LOT_HREF_RE.search(response.url)
        if m_lot:
            loader.add_value("source_lot_code", m_lot.group(1))

        title = og_title
        if title:
            loader.add_value("title", title.strip())

        # description: og:description (já unescaped) ou bloco "Descrição"
        desc = og_desc
        if not desc or len(desc) < 30:
            block = response.css(
                "div.descricao *::text, section.descricao *::text, "
                "div[class*='descricao'] *::text"
            ).getall()
            desc = _normalize_text(" ".join(block))
        if desc:
            loader.add_value("description", desc[:10000])

        # status — heurística sobre o body
        body_lower = raw.lower()
        if "arrematado" in body_lower:
            status = "arrematado"
        elif "suspens" in body_lower:
            status = "suspenso"
        elif "cancelad" in body_lower:
            status = "cancelado"
        elif "encerrad" in body_lower or "finalizad" in body_lower:
            status = "desconhecido"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Avaliação (market_value)
        mkt_str = pairs.get("Valor da avaliação") or pairs.get("Avaliação") or ""
        m_mkt = _BRL_PRICE_RE.search(mkt_str)
        if m_mkt:
            try:
                loader.add_value("market_value", str(_brl_to_decimal(m_mkt.group(1))))
            except Exception:
                pass

        # Lance inicial (minimum_bid) — quando há 2 praças, o value do label
        # "Lance inicial" tem ambos preços + datas embutidos:
        #   "1º. LEILÃO: Sex, 12/06/2026 - 10:00h - R$ 810.000,00
        #    2º. LEILÃO: Sex, 19/06/2026 - 10:00h - R$ 405.000,00"
        # Estratégia: tentar parsear todas praças primeiro (extraindo
        # min_bid + datas); fallback genérico para BRL único.
        min_str = pairs.get("Lance inicial") or pairs.get("Valor mínimo") or pairs.get("Lance mínimo") or ""
        first_dt, second_dt, first_bid, second_bid = _parse_leilotech_pracas(min_str)
        # Quando min_str não tem "1º LEILÃO" / "2º LEILÃO", min_str é só "R$ N"
        if not (first_bid or second_bid):
            m_min = _BRL_PRICE_RE.search(min_str)
            if not m_min:
                # Fallback: procurar "Pelo valor de:" no body
                m_min = re.search(r"Pelo valor de[^R]{0,30}R\$\s*([\d.,]+)", raw, re.I)
            if m_min:
                first_bid = m_min.group(1)

        # min_bid escolhido: prefere 2ª praça (mais barata e ativa em judicial)
        chosen_min = second_bid or first_bid
        if chosen_min:
            try:
                loader.add_value("minimum_bid", str(_brl_to_decimal(chosen_min)))
            except Exception:
                pass

        # Cidade/UF
        city_uf = pairs.get("Cidade/UF") or pairs.get("Localização") or ""
        addr: dict[str, Any] = {"raw_text": city_uf[:300]}
        m_cuf = re.match(r"^([^/]+?)\s*/\s*([A-Z]{2})\s*$", city_uf)
        if m_cuf:
            addr["municipality_name"] = m_cuf.group(1).strip()
            addr["uf"] = m_cuf.group(2)
        if any(v for v in addr.values()):
            loader.add_value("address", addr)

        # Datas das praças
        if first_dt:
            loader.add_value("first_auction_date", first_dt)
        if second_dt:
            loader.add_value("second_auction_date", second_dt)
            loader.add_value("auction_phase", "2a_praca")
        elif first_dt:
            loader.add_value("auction_phase", "1a_praca")

        # Fallback: data DD/MM/YYYY HH:MM no body (sem rótulo de praça)
        if not (first_dt or second_dt):
            m_dt = re.search(r"(\d{2}/\d{2}/\d{4})[^,<]{0,8}(\d{1,2}):(\d{2})", raw)
            if m_dt:
                d, h, mi = m_dt.group(1), m_dt.group(2), m_dt.group(3)
                loader.add_value("second_auction_date", f"{d} {int(h):02d}:{mi}")
                loader.add_value("auction_phase", "2a_praca")

        # Images: cdn.leilotech.workers.dev/{tenant}/lotes/{lot_id}/...
        img_urls = response.css(
            "img[src*='cdn.leilotech.workers.dev']::attr(src), "
            "img[data-src*='cdn.leilotech.workers.dev']::attr(data-src)"
        ).getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            if not u:
                continue
            absolute = response.urljoin(u)
            # filtra logos
            if "/logos/" in absolute:
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
        for a in response.css(
            "a[href*='cdn.leilotech.workers.dev'][href$='.pdf'], a[href$='.pdf']"
        ):
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
            "lt_lote_extracted",
            url=response.url,
            host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            mkt=item.get("market_value"),
        )
        yield item

        # Merge edital
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


def _decode_jsonish(s: str) -> str:
    """Decodifica escapes JSON comuns em strings inline (\\/, \\", \\\\, \\uXXXX).

    Mais robusto que `s.encode().decode('unicode_escape')`, que falha em
    bytes não-ASCII (UTF-8 multi-byte vira mojibake) e ignora `\\/`.
    """
    if not s:
        return s
    import json as _json
    # Tenta primeiro via json.loads (cobre todos escapes JSON corretamente).
    try:
        return _json.loads('"' + s + '"')
    except Exception:
        pass
    # Fallback: troca manual dos escapes mais comuns
    out = s.replace("\\/", "/").replace('\\"', '"').replace("\\\\", "\\")
    return out


def _parse_leilotech_pracas(text: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Extrai (first_dt, second_dt, first_bid, second_bid) do value de
    "Lance inicial" da Leilotech.

    Texto típico:
        "1º. LEILÃO: Sex, 12/06/2026 - 10:00h - R$ 810.000,00
         2º. LEILÃO: Sex, 19/06/2026 - 10:00h - R$ 405.000,00"

    Retorna strings 'DD/MM/YYYY HH:MM' e valores R$ (sem o "R$").
    """
    if not text:
        return None, None, None, None
    first_dt = second_dt = first_bid = second_bid = None
    # Padrão: "Nº. LEILÃO: weekday?, DD/MM/YYYY - HH:MMh - R$ V"
    pat = re.compile(
        r"([12])[ºº°o.]?\s*\.?\s*LEIL[ÃA]O\s*:?\s*"
        r"(?:[A-Za-zãç]+,?\s*)?"
        r"(\d{2}/\d{2}/\d{4})\s*[-–]?\s*(\d{1,2})(?:[h:](\d{2}))?h?\s*"
        r"(?:[-–]\s*R\$\s*([\d.,]+))?",
        re.I,
    )
    for m in pat.finditer(text):
        n = m.group(1)
        d = m.group(2)
        h = int(m.group(3))
        mi = m.group(4) or "00"
        bid = m.group(5)
        dt = f"{d} {h:02d}:{mi}"
        if n == "1" and not first_dt:
            first_dt = dt
            first_bid = bid
        elif n == "2" and not second_dt:
            second_dt = dt
            second_bid = bid
    return first_dt, second_dt, first_bid, second_bid
