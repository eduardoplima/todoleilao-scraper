"""Spider para o portal oficial do Bradesco — `vitrinebradesco.com.br`.

SPA React (Hallo / Resale stack — `<div id="root">` + chunks webpack).
A listagem só aparece após hidratação do JS; usamos Playwright pra
renderizar a home/listagem, descobrir links que casem o padrão de
detalhe e seguir.

Detail URLs típicos no Bradesco vitrine: `/imoveis/{slug}-{id}` ou
`/produto/{slug}`. Em runtime descobrimos o padrão real via DOM
renderizado (lista de `a` cujo href cai em rotas internas do app).

Provider slug: `bradesco`. Sub-componente Hallo identificado pelo
`hallo-static.s3-sa-east-1.amazonaws.com` no favicon.

Uso:
    scrapy crawl bradesco -a urls=https://vitrinebradesco.com.br/imoveis
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import scrapy
from scrapy_playwright.page import PageMethod

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _detail_is_imovel,
    _normalize_text,
    _parse_auction_clauses,
)


# Bradesco/Hallo usa /auctions/{slug}-{id} pra lotes individuais.
# /auctions?type=realstate pra listagem filtrada por imóveis.
_LOT_PATH_RE = re.compile(
    r"^/auctions/[A-Za-z0-9._-]+(?:/\d+)?/?$"
)
# Lotes terminam com -N ou _N (ID numérico)
_LOT_PATH_WITH_ID_RE = re.compile(r"[-_][0-9]+/?$")

_CITY_UF_RE = re.compile(
    r"\b([A-ZÀ-Ú][A-ZÀ-Úa-zà-ú\s'.-]{2,60}?)\s*[/-]\s*([A-Z]{2})\b",
)
_MATRICULA_RE = re.compile(
    r"Matr[íi]cula\s*(?:n[º°.]?\s*)?(\d{1,7})", re.I
)


class BradescoSpider(ProviderSpider):
    name = "bradesco"
    provider_slug = "bradesco"
    auctioneer_slug = "bradesco"
    requires_playwright = True

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 1.0,
        "PLAYWRIGHT_MAX_PAGES_PER_CONTEXT": 4,
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 60_000,
        "USER_AGENT": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36 TodoLeilaoBot/1.0"
        ),
    }

    MAX_LOTS_PER_RUN = 100

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._yielded = 0
        self._seen: set[str] = set()

    # ------------------------------------------------------------------
    # Nível 1: home/listagem via Playwright; aguarda hidratação
    # ------------------------------------------------------------------
    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        kept = 0
        # Após hidratação, qualquer <a> que casa o padrão de detalhe vira
        # candidato. Filtramos por _LOT_PATH_RE + sufixo numérico.
        for href in response.css("a::attr(href)").getall():
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            absolute = response.urljoin(href)
            if self.host_of(absolute) != host:
                continue
            path = absolute.replace(f"https://{host}", "").split("?")[0]
            if not _LOT_PATH_RE.match(path):
                continue
            # Filtra rotas que terminam em ID numérico (lotes)
            if not (_LOT_PATH_WITH_ID_RE.search(path) or re.search(r"/\d{3,}/?$", path)):
                continue
            if absolute in self._seen:
                continue
            self._seen.add(absolute)
            if self._yielded >= self.MAX_LOTS_PER_RUN:
                break
            self._yielded += 1
            kept += 1
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={"source_listing_url": response.url, "host": host},
                # Bradesco SPA hidrata `<div class="price">` somente após o
                # XHR de detalhe — esperamos pelo texto "Valor mínimo" estar
                # presente, indicador de hidratação completa.
                wait_for_selector="text=Valor mínimo",
                wait_timeout_ms=25_000,
            )
        self.log_event(
            "bradesco_listing_done",
            host=host,
            url=response.url,
            kept=kept,
            seen_total=len(self._seen),
        )

    def start_requests(self) -> Iterable[Any]:
        # Override pra: (1) substituir URLs `/imoveis` ou similares pelo
        # filtro real do app `/auctions?type=realstate`; (2) aguardar o
        # JS render hidratar os <a href="/auctions/...">.
        for url in self.start_urls:
            host = self.host_of(url)
            # Normaliza para o filtro real-state da SPA
            target = f"https://{host}/auctions?type=realstate"
            yield self.make_request(
                target,
                callback=self.parse,
                wait_for_selector="a[href*='/auctions/']",
                wait_timeout_ms=30_000,
                scroll_to_bottom=True,
                dont_filter=True,
            )

    # ------------------------------------------------------------------
    # Nível 2: detalhe — extração best-effort
    # ------------------------------------------------------------------
    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("host", self.host_of(response.url))

        body_text = _normalize_text(" ".join(response.css("body *::text").getall()))
        # Bradesco usa <h4> dentro de div.title para o título do lote.
        title_h4 = _normalize_text(
            " ".join(response.css("div.title h4::text").getall())
        )
        h1 = title_h4 or (response.css("h1::text").get() or "").strip()
        og_title = response.css("meta[property='og:title']::attr(content)").get() or h1
        og_desc = response.css("meta[property='og:description']::attr(content)").get() or ""

        sample = (og_title + " " + og_desc + " " + body_text[:3000])
        if not _detail_is_imovel(og_title or h1 or "imóvel Bradesco", sample):
            self.log_event("bradesco_lote_dropped_non_imovel", url=response.url)
            return

        loader = self.new_loader(response)
        loader.replace_value("auctioneer", "bradesco")

        # Bradesco h4 do bloco div.title é a fonte canônica do título.
        # og_title é o título global da SPA (não dá informação).
        title = h1 or og_title or "Imóvel Bradesco"
        loader.add_value("title", title[:300])

        m_id = re.search(r"-(\d{3,})/?$", response.url) or re.search(r"/(\d+)/?$", response.url)
        if m_id:
            loader.add_value("source_lot_code", f"brad-{m_id.group(1)}")

        # Description — Bradesco usa <p class="description"> em
        # div.container-description.
        desc_block = " ".join(response.css(
            "p.description::text, "
            "div.container-description *::text, "
            "div[class*='descricao'] *::text"
        ).getall())
        desc = _normalize_text(desc_block)
        if not desc:
            desc = og_desc
        if desc:
            loader.add_value("description", desc[:10000])

        # Status — usar texto-chave do app React
        status_lower = (
            (response.css("[class*='status']::text").get() or "")
            + " " + body_text[:200]
        ).lower()
        if "encerrad" in status_lower or "finalizad" in status_lower:
            status = "desconhecido"
        elif "arrematad" in status_lower or "vendid" in status_lower:
            status = "arrematado"
        elif "suspens" in status_lower:
            status = "suspenso"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Preço: Bradesco quebra "R$" + valor em <span>s.
        # Extração via texto bruto do div.price (que concatena R$, 0, ,00).
        price_block = _normalize_text(
            " ".join(response.css("div.price *::text").getall())
        )
        # Após normalize, padrão típico: "R$ 0 ,00 Valor mínimo"
        m_min = (
            re.search(r"R\$\s*([\d.\s]*[\d])\s*,\s*(\d{2})\s*Valor\s+m[íi]nimo", price_block, re.I)
            or re.search(r"R\$\s*([\d.,\s]+?)\s*Valor\s+m[íi]nimo", price_block, re.I)
            or re.search(r"R\$\s*([\d.,\s]+?)\s*Valor\s+m[íi]nimo", body_text, re.I)
        )
        if m_min:
            try:
                # Quando capturamos integer + decimal em grupos separados,
                # reunimos como "INT,DEC". Caso geral: strip whitespace.
                if m_min.lastindex and m_min.lastindex >= 2:
                    raw = (
                        re.sub(r"\s+", "", m_min.group(1))
                        + ","
                        + m_min.group(2)
                    )
                else:
                    raw = re.sub(r"\s+", "", m_min.group(1))
                v = _brl_to_decimal(raw)
                # Aceita 0 como valor válido (lote "Convencional" pré-leilão).
                if v is not None and v >= 0:
                    loader.add_value("minimum_bid", str(v))
            except Exception:
                pass

        m_av = re.search(r"Avalia[çc][ãa]o[:\s]*R\$\s*([\d.,]+)", body_text, re.I)
        if m_av:
            try:
                v = _brl_to_decimal(m_av.group(1))
                if v and v > 0:
                    loader.add_value("market_value", str(v))
            except Exception:
                pass

        # Endereço — formato Bradesco: "Casa - Tupã /SP - Rua X, 123"
        # Cidade vem após o primeiro " - ", UF é o /XX que segue.
        addr: dict[str, Any] = {"raw_text": title[:300]}
        m_brad = re.search(
            r"^[A-Za-zÀ-ú\s/]+?\s*-\s*([A-ZÀ-Úa-zà-ú\s.'-]+?)\s*/\s*([A-Z]{2})\b",
            title or "",
        )
        if m_brad:
            cidade = m_brad.group(1).strip().rstrip(",.")
            if 3 <= len(cidade) <= 60:
                addr["municipality_name"] = cidade.title()
                addr["uf"] = m_brad.group(2)
        elif (title or ""):
            # Fallback: regex genérica
            m_cuf = _CITY_UF_RE.search(title or "")
            if m_cuf:
                cidade = m_cuf.group(1).strip().rstrip(",.")
                if 3 <= len(cidade) <= 60:
                    addr["municipality_name"] = cidade.title()
                    addr["uf"] = m_cuf.group(2)
        m_matr = _MATRICULA_RE.search(body_text)
        if m_matr:
            addr["registry_matricula"] = m_matr.group(1)
        if any(v for v in addr.values()):
            loader.add_value("address", addr)

        # Imagens — galeria React; aceita src + data-src + background
        img_urls = response.css("img::attr(src), img::attr(data-src)").getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            if not u or "data:image" in u:
                continue
            absolute = response.urljoin(u)
            low = absolute.lower()
            if any(skip in low for skip in (
                "logo", "favicon", "icon", "bandeira", "placeholder",
                "facebook", "instagram", "whatsapp", "/static/media/")):
                continue
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        # background-image inline
        for m in re.finditer(
            r"background-image:\s*url\(['\"]?(https?://[^'\")]+\.(?:jpe?g|png|webp))",
            response.text, re.I,
        ):
            u = m.group(1)
            low = u.lower()
            if any(k in low for k in ("logo", "favicon", "/static/media/")):
                continue
            if u not in seen_imgs:
                seen_imgs.add(u)
                unique_imgs.append(u)
        if unique_imgs:
            loader.add_value("images", unique_imgs[:20])

        # Documentos
        docs: list[dict] = []
        seen_docs: set[str] = set()
        for a in response.css("a[href$='.pdf']"):
            url = a.css("::attr(href)").get()
            if not url:
                continue
            absolute = response.urljoin(url)
            if absolute in seen_docs:
                continue
            seen_docs.add(absolute)
            label = _normalize_text(" ".join(a.css("*::text").getall())) or "documento"
            docs.append({"name": label, "url": absolute})
        if docs:
            loader.add_value("documents", docs)

        payment_options, encumbrances = _parse_auction_clauses(body_text)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())
        item = loader.load_item()
        self.log_event(
            "bradesco_lote_extracted",
            url=response.url,
            host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            mkt=item.get("market_value"),
        )
        yield item
