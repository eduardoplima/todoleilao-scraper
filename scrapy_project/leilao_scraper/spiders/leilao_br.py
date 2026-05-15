"""Spider para o cluster `*.leilao.br` — plataforma e-leiloes (Laravel/Blade).

Em 2026-05-01 (data do recon) parte dos sites usava Nuxt SSR. Em 2026-05-14
todos os sites do cluster `*.leilao.br` migraram para a plataforma única
Laravel da e-leiloes.com.br. Recon arquitetural em `specs/_providers/leilao_br/`
está parcialmente desatualizado — este spider re-implementa a partir do
stack atual.

Estratégia
==========

1. **Listagem por leiloeiro**: `/leilao/imoveis` em cada subdomínio
   `*.leilao.br` mostra os lotes do leiloeiro daquele site (filtro por
   broker). Cards `div.item-list.lote-item` com `<a class="lote-status">`
   apontam para URLs **canônicas** em `e-leiloes.com.br` no padrão
   `/eventos/leilao/{slug-leilao}/lote/{lot_id}/{slug-lote}`.
2. **Paginação**: `?page=N` na própria URL de listagem.
3. **Detalhe**: 100% HTML estático. Há um `<script type="application/ld+json">`
   por lote com `@type=Product`, `name`, `description`, `image[]`,
   `offers.price` (lance mínimo atual), `broker` (leiloeiro + JUC).
   Datas das praças e endereço estruturado vêm do DOM (`div.c-bloco c-data`,
   `div.c-bloco c-endereco`).
4. **source_lot_code**: o ID `{lot_id}` do path, único em todo o cluster.
5. **auctioneer**: extraído do JSON-LD (`broker.name` + `broker.identifier`
   com JUCESP/JUC). Quando ausente, cai em `leilao_br::{host}`.

Uso
===

```
scrapy crawl leilao_br -a sites=3
scrapy crawl leilao_br -a sites=all
scrapy crawl leilao_br -a urls=https://www.e-leiloeiro.leilao.br/leilao/imoveis
```
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Iterable
from urllib.parse import urlparse

import scrapy

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _normalize_text,
    _parse_br_datetime_iso,
)


# Detail URL canônica vive em e-leiloes.com.br/eventos/leilao/.../lote/{id}/{slug}
_LOT_HREF_RE = re.compile(r"/eventos/leilao/[^\"'/]+/lote/(\d+)/[a-z0-9-]+", re.I)

# Datas em português ("17 de junho de 2026 às 11:00")
_PT_DT_RE = re.compile(
    r"(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})\s+[àa]s\s+(\d{1,2}):(\d{2})",
    re.I,
)
_MONTH_PT = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _parse_pt_date(text: str) -> str | None:
    m = _PT_DT_RE.search(text or "")
    if not m:
        return _parse_br_datetime_iso(text or "")
    d, mname, y, h, mi = m.groups()
    mnum = _MONTH_PT.get(mname.lower().strip())
    if not mnum:
        return None
    return f"{y}-{mnum:02d}-{int(d):02d}T{int(h):02d}:{mi}:00-03:00"


# Mapeamento tipo (no schema.org / breadcrumb) → property_type canônico
_TYPE_MAP = {
    "casa": "casa",
    "apartamento": "apartamento",
    "terreno": "terreno",
    "rural": "rural",
    "comercial": "comercial",
    "sala": "comercial",
    "loja": "comercial",
    "industrial": "comercial",
}


def _classify_property(text: str) -> str | None:
    t = (text or "").lower()
    for k, v in _TYPE_MAP.items():
        if k in t:
            return v
    return None


def _extract_jsonld_product(response) -> dict | None:
    """Retorna o JSON-LD com @type=Product (ou None)."""
    for script in response.css("script[type='application/ld+json']::text").getall():
        try:
            data = json.loads(script.strip())
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("@type") == "Product":
            return data
    return None


def _extract_broker(jsonld: dict | None) -> dict | None:
    if not jsonld:
        return None
    broker = jsonld.get("broker") or {}
    if not isinstance(broker, dict):
        return None
    name = (broker.get("name") or "").strip()
    if not name:
        return None
    out = {"full_name": name}
    ident = (broker.get("identifier") or "").strip()
    # "JUCESP nº 1083" → uf=SP, num=1083
    m = re.search(r"JUC([A-Z]{2})\s*n[º°.]?\s*(\d+)", ident, re.I)
    if m:
        out["juc_uf"] = m.group(1).upper()
        out["jucesp_number"] = m.group(2)
    return out


def _is_imovel(jsonld: dict | None, body_text: str) -> bool:
    if jsonld:
        name = (jsonld.get("name") or "").lower()
        if any(w in name for w in ("imóvel", "imovel", "casa", "apartamento",
                                    "terreno", "lote", "sala", "loja",
                                    "comercial", "rural", "fazenda", "chácara")):
            return True
    bt = (body_text or "").lower()
    # Filtros negativos (mais comuns em not-imóvel cluster)
    if any(w in bt[:5000] for w in ("veículo", "veiculo", "motocicleta", "caminhão",
                                     "automóvel", "automovel")):
        return False
    return True  # default permissivo, pipeline filtra depois via property_type


def _extract_property_type(jsonld: dict | None, response) -> str | None:
    if jsonld:
        pt = _classify_property(jsonld.get("name") or "")
        if pt:
            return pt
    # Tenta breadcrumb (segundo JSON-LD)
    for script in response.css("script[type='application/ld+json']::text").getall():
        try:
            data = json.loads(script.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "BreadcrumbList":
            for item in data.get("itemListElement") or []:
                name = (item.get("name") or "").lower() if isinstance(item, dict) else ""
                pt = _classify_property(name)
                if pt:
                    return pt
    return None


def _extract_address_from_dom(response) -> dict | None:
    """Endereço em `<div class='c-bloco c-endereco'> <a>...</a></div>`.

    Texto agregado com vírgulas/quebras: 'Rua X, 250, Bairro, Cidade - UF'.
    """
    nodes = response.css("div.c-bloco.c-endereco a *::text, div.c-bloco.c-endereco a::text").getall()
    raw = _normalize_text(" ".join(nodes))
    if not raw or len(raw) < 6:
        return None
    out: dict = {"raw_text": raw}
    # UF no final: " - UF" ou "/UF"
    m = re.search(r"[-/]\s*([A-Z]{2})\s*$", raw)
    if m:
        out["uf"] = m.group(1).upper()
    # Cidade: token antes do "- UF"
    m = re.search(r",\s*([A-Za-zÀ-ú\s'.-]+?)\s*[-/]\s*[A-Z]{2}\s*$", raw)
    if m:
        out["municipality_name"] = m.group(1).strip()
    # Rua + número: primeiro segmento "Rua X, NN"
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if parts:
        out["street_name"] = parts[0]
    if len(parts) >= 2 and re.match(r"^\d", parts[1]):
        out["number"] = parts[1]
    return out


class LeilaoBrSpider(ProviderSpider):
    """Spider para o cluster `*.leilao.br` (plataforma e-leiloes Laravel)."""

    name = "leilao_br"
    provider_slug = "leilao_br"
    auctioneer_slug = "leilao_br"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.0,
        # robots de e-leiloes.com.br pode bloquear bots; respeitar.
    }

    MAX_PAGES_PER_HOST = 50

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_lots: set[str] = set()

    # ----- Nível 1: home → /leilao/imoveis ----------------------------------

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        # start_urls é a homepage do leiloeiro OU já uma URL de listagem.
        # Quando a URL recebida não é uma listagem reconhecida, redirecionamos
        # para `/leilao/imoveis`. Se já é a listagem, parseia direto.
        host = self.host_of(response.url)
        path = urlparse(response.url).path or ""
        if "/leilao/imoveis" in path or "/lote/" in path:
            yield from self.parse_listing(response)
            return
        listing_url = response.urljoin("/leilao/imoveis")
        yield self.make_request(
            listing_url,
            callback=self.parse_listing,
            meta={"page": 1, "broker_host": host},
        )

    # ----- Nível 2: listing → detail URLs em e-leiloes.com.br ----------------

    def parse_listing(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        broker_host = response.meta.get("broker_host") or self.host_of(response.url)
        page = response.meta.get("page", 1)
        # Quando parse_listing é entrado direto a partir de parse() sem
        # passar via make_request, copia broker_host pro meta atual.
        if not response.meta.get("broker_host"):
            response.meta["broker_host"] = broker_host
        kept = 0
        for href in response.css(
            "div.item-list.lote-item a.lote-status::attr(href), "
            "div.item-list.lote-item h5 a::attr(href)"
        ).getall():
            if not _LOT_HREF_RE.search(href):
                continue
            absolute = response.urljoin(href)
            m = _LOT_HREF_RE.search(absolute)
            if not m:
                continue
            lot_id = m.group(1)
            if lot_id in self._seen_lots:
                continue
            self._seen_lots.add(lot_id)
            kept += 1
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={
                    "source_listing_url": response.url,
                    "broker_host": broker_host,
                    "source_lot_code": lot_id,
                },
            )

        self.log_event("lb_listing_done", url=response.url, page=page, kept=kept)

        # Paginação ?page=N — só continua se trouxe novos
        if kept > 0 and page < self.MAX_PAGES_PER_HOST:
            base_url = re.sub(r"[?&]page=\d+", "", response.url).rstrip("?&")
            sep = "&" if "?" in base_url else "?"
            next_url = f"{base_url}{sep}page={page + 1}"
            yield self.make_request(
                next_url,
                callback=self.parse_listing,
                meta={"page": page + 1, "broker_host": broker_host},
            )

    # ----- Nível 3: parse_property ------------------------------------------

    def parse_property(self, response: scrapy.http.Response):
        body_text = " ".join(response.css("body *::text").getall())[:8000]
        jsonld = _extract_jsonld_product(response)

        if not _is_imovel(jsonld, body_text):
            self.log_event("lb_dropped_non_imovel", url=response.url)
            return

        loader = self.new_loader(response)
        broker_host = response.meta.get("broker_host") or ""

        # auctioneer
        broker = _extract_broker(jsonld)
        if broker and broker.get("full_name"):
            loader.replace_value("auctioneer", broker["full_name"])
            loader.add_value("auctioneer_data", broker)
        else:
            loader.replace_value("auctioneer", f"leilao_br::{broker_host}")

        # source_lot_code
        slc = response.meta.get("source_lot_code")
        if not slc:
            m = _LOT_HREF_RE.search(response.url)
            if m:
                slc = m.group(1)
        if slc:
            loader.add_value("source_lot_code", slc)

        # Title / description / property_type
        if jsonld:
            if jsonld.get("name"):
                loader.add_value("title", _normalize_text(jsonld["name"]))
            if jsonld.get("description"):
                loader.add_value("description", _normalize_text(jsonld["description"])[:10000])
        # Fallback h1
        if not jsonld or not jsonld.get("name"):
            h1 = response.css("main h1::text, h1::text").get()
            if h1:
                loader.add_value("title", _normalize_text(h1))
        # Fallback descrição: div.c-descricao .html
        if not jsonld or not jsonld.get("description"):
            desc_nodes = response.css(
                "div.c-descricao .html *::text, "
                "div.c-descricao .html::text"
            ).getall()
            desc = _normalize_text(" ".join(desc_nodes))
            if desc:
                loader.add_value("description", desc[:10000])

        pt = _extract_property_type(jsonld, response)
        if pt:
            loader.add_value("property_type", pt)

        # Endereço
        addr = _extract_address_from_dom(response)
        if addr:
            loader.add_value("address", addr)

        # Status: a página tem 2 praças datadas. Status "aberto" se houver
        # data futura, senão "desconhecido". Sinais de "encerrado/arrematado"
        # via texto.
        bt_low = body_text.lower()
        if "arrematad" in bt_low:
            status = "arrematado"
        elif "cancelad" in bt_low:
            status = "cancelado"
        elif "encerrad" in bt_low or "sem licitante" in bt_low:
            status = "desconhecido"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # ---- Datas das praças (1º Leilão / 2º Leilão) -----------------------
        # `<div class="c-bloco c-data ...">` ou `<div class="c-data ...">`.
        # Cada bloco tem `<h5>Nº Leilão</h5>` + `<strong>R$ ...</strong>` +
        # `<p class="widescreen">DD de MES de YYYY às HH:MM</p>`.
        first_date = None
        second_date = None
        first_min_brl = None
        second_min_brl = None
        for block in response.css("div.c-data, div[class*='c-data']"):
            label = " ".join(block.css("h5::text").getall()).strip().lower()
            date_text = " ".join(block.css("p.widescreen::text").getall()).strip()
            if not date_text:
                date_text = " ".join(block.css("p.mobile::text").getall()).strip()
            value_text = " ".join(block.css("strong::text").getall()).strip()
            dt_iso = _parse_pt_date(date_text)
            m_brl = re.search(r"R\$\s*([\d.,]+)", value_text)
            brl = None
            if m_brl:
                try:
                    brl = str(_brl_to_decimal(m_brl.group(1)))
                except Exception:
                    pass

            if "1" in label and ("leilão" in label or "leilao" in label or "praça" in label or "praca" in label):
                if dt_iso and not first_date:
                    first_date = dt_iso
                if brl and not first_min_brl:
                    first_min_brl = brl
            elif "2" in label and ("leilão" in label or "leilao" in label or "praça" in label or "praca" in label):
                if dt_iso and not second_date:
                    second_date = dt_iso
                if brl and not second_min_brl:
                    second_min_brl = brl

        if first_date:
            loader.add_value("first_auction_date", first_date)
        if second_date:
            loader.add_value("second_auction_date", second_date)

        # Valor de avaliação ("Valor de venda" / "Valor avaliado")
        valor_text = " ".join(response.css(
            "div.c-bloco.c-valor *::text, div[class*='c-valor'] *::text"
        ).getall())
        m_av = re.search(r"venda[^R]{0,30}R\$\s*([\d.,]+)", valor_text, re.I)
        if not m_av:
            m_av = re.search(r"avalia[çc][ãa]o?[^R]{0,30}R\$\s*([\d.,]+)", valor_text, re.I)
        if not m_av:
            m_av = re.search(r"avaliado[^R]{0,30}R\$\s*([\d.,]+)", body_text, re.I)
        if m_av:
            try:
                loader.add_value("market_value", str(_brl_to_decimal(m_av.group(1))))
            except Exception:
                pass

        # minimum_bid: regra do schema = "menor lance ainda válido". Se a
        # 2ª praça tem valor menor que a 1ª e ainda não passou, esse é o
        # vigente. Heurística simples: o **menor valor positivo** entre 1ª
        # e 2ª praças. Se nenhum, tenta JSON-LD offers.price.
        candidates = []
        if first_min_brl:
            try:
                candidates.append(Decimal(first_min_brl))
            except Exception:
                pass
        if second_min_brl:
            try:
                candidates.append(Decimal(second_min_brl))
            except Exception:
                pass
        if candidates:
            loader.add_value("minimum_bid", str(min(candidates)))
        elif jsonld and isinstance(jsonld.get("offers"), dict):
            price = jsonld["offers"].get("price")
            if price is not None:
                try:
                    loader.add_value("minimum_bid", str(Decimal(str(price))))
                except Exception:
                    pass

        # auction_phase: se 2ª data presente e mais "atual" (presente da
        # praça vigente é marcado no HTML como `c-data.atual`)
        atual_blocks = response.css("div.c-data.atual h5::text, div[class*='c-data'].atual h5::text").getall()
        atual_text = " ".join(atual_blocks).lower()
        if "2" in atual_text:
            loader.add_value("auction_phase", "2a_praca")
        elif "1" in atual_text:
            loader.add_value("auction_phase", "1a_praca")

        # Imagens — JSON-LD traz lista completa
        imgs: list[str] = []
        if jsonld and jsonld.get("image"):
            raw_imgs = jsonld["image"]
            if isinstance(raw_imgs, str):
                imgs.append(raw_imgs)
            elif isinstance(raw_imgs, list):
                imgs.extend([i for i in raw_imgs if isinstance(i, str)])
        # Fallback DOM `ul.lote-thumbs a[href]`
        if not imgs:
            for a in response.css("ul.lote-thumbs a::attr(href)").getall():
                if a:
                    imgs.append(response.urljoin(a))
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in imgs:
            if u not in seen_imgs:
                seen_imgs.add(u)
                unique_imgs.append(u)
        if unique_imgs:
            loader.add_value("images", unique_imgs)

        # Documentos — `div.c-documentos ul li a[href$=.pdf]`
        docs: list[dict] = []
        seen_doc_urls: set[str] = set()
        for a in response.css("div.c-documentos ul li a"):
            href = a.css("::attr(href)").get() or ""
            label = _normalize_text(" ".join(a.css("*::text").getall()))
            if not href:
                continue
            absolute = response.urljoin(href)
            if absolute in seen_doc_urls:
                continue
            seen_doc_urls.add(absolute)
            docs.append({"name": label or "documento", "url": absolute})
        if docs:
            loader.add_value("documents", docs)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "lb_lote_extracted",
            url=response.url,
            host=broker_host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            market=item.get("market_value"),
        )
        yield item
