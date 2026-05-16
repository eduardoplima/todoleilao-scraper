"""Atlântico Leilões (atlanticoleiloes.com.br) — Francisco Luã Costa, RN.

Site PHP (server-side render) com dados do lote inline como JSON:
    var lote = {"id":19, "titulo":..., "valorInicial":"79000.00", "status":8,...};
    var leilao = {"id":7, "dataPraca1":{...}, "judicial":false, ...};

A home (`/`) lista ~100 lotes ativos via URLs `/lote/{id}/{slug}`. A
listagem `/leiloes/{auction_id}` mostra lotes de cada leilão (alguns
mais antigos ainda têm links server-side, outros carregam via JS — só
o home expõe links de fato).

Status codes (campo `lote.status`) observados:
    8  = aberto (recebendo lances)
    99 = realizado / encerrado
Os demais (sustado/cancelado) aparecem como labels HTML separados.
"""
from __future__ import annotations

import html as html_mod
import json
import re
from decimal import InvalidOperation
from typing import Iterable

import scrapy

from leilao_scraper.spiders.base import BaseAuctionSpider
from leilao_scraper.spiders.proprio_html_specific._common import _uf_from_url_slug
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _normalize_text,
    _parse_auction_clauses,
)


_LOT_URL_RE = re.compile(r"/lote/(\d+)/[^\s\"'<)]+", re.I)

_IMOVEL_RE = re.compile(
    r"\b(im[óo]vel|im[óo]veis|apartamento|apto|casa|sobrado|kitnet|"
    r"cobertura|terreno|lote\s|fazenda|ch[áa]cara|s[íi]tio|gleba|"
    r"sala\s+comercial|loja|galp[ãa]o|pr[ée]dio|edif[íi]cio|"
    r"resid[êe]ncial|comercial|garagem|m[²2]\b|metros)\b",
    re.I,
)
_VEICULO_RE = re.compile(
    r"\b(autom[óo]vel|ve[íi]culo|carro|caminh[ãa]o|motocicleta|"
    r"trator|reboque|[ôo]nibus|placa)\b",
    re.I,
)

_TYPE_MAP = {
    "apartamento": "apartamento",
    "apto": "apartamento",
    "kitnet": "apartamento",
    "cobertura": "apartamento",
    "casa": "casa",
    "sobrado": "casa",
    "terreno": "terreno",
    "lote": "terreno",
    "sítio": "rural",
    "sitio": "rural",
    "fazenda": "rural",
    "chácara": "rural",
    "chacara": "rural",
    "rural": "rural",
    "loja": "comercial",
    "sala": "comercial",
    "galpão": "comercial",
    "galpao": "comercial",
    "predio": "comercial",
    "edifício": "comercial",
    "edificio": "comercial",
    "comercial": "comercial",
}


def _classify(title: str) -> str | None:
    t = (title or "").lower()
    for key, val in _TYPE_MAP.items():
        if key in t:
            return val
    return None


_STATUS_MAP = {
    1: "aberto",
    2: "aberto",
    8: "aberto",
    9: "aberto",
    10: "aberto",
    11: "aberto",
    12: "aberto",
    13: "arrematado",
    14: "arrematado",
    99: "desconhecido",  # realizado/encerrado sem distinção fina
}


def _extract_inline_var(body: str, var_name: str) -> dict | None:
    """Extrai `var <name> = { ... };` retornando o dict ou None."""
    # Estratégia: pega tudo de '{' até ';' final, depois faz balanceamento.
    m = re.search(rf"var\s+{re.escape(var_name)}\s*=\s*\{{", body)
    if not m:
        return None
    start = m.end() - 1  # posição do '{'
    depth = 0
    end = -1
    in_str = False
    esc = False
    for i in range(start, len(body)):
        c = body[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return None
    try:
        return json.loads(body[start:end])
    except (json.JSONDecodeError, ValueError):
        return None


class AtlanticoLeiloesSpider(BaseAuctionSpider):
    name = "atlantico_leiloes"
    auctioneer_slug = "atlantico_leiloes"
    allowed_domains = ["atlanticoleiloes.com.br"]
    requires_playwright = False

    start_urls = [
        "https://www.atlanticoleiloes.com.br/",
        "https://www.atlanticoleiloes.com.br/leiloes/144",
        "https://www.atlanticoleiloes.com.br/leiloes/219",
        "https://www.atlanticoleiloes.com.br/leiloes/230",
        "https://www.atlanticoleiloes.com.br/leiloes/231",
    ]

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.0,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_lots: set[str] = set()

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        kept = 0
        for m in _LOT_URL_RE.finditer(response.text):
            lot_id = m.group(1)
            if lot_id in self._seen_lots:
                continue
            self._seen_lots.add(lot_id)
            # Reconstrói URL a partir do path completo do match
            path = m.group(0)
            absolute = response.urljoin(path)
            kept += 1
            yield scrapy.Request(
                absolute,
                callback=self.parse_property,
                meta={
                    "source_listing_url": response.url,
                    "source_lot_code": lot_id,
                },
            )
        self.log_event("at_listing_done", url=response.url, kept=kept)

    def parse_property(self, response: scrapy.http.Response):
        body = response.text

        lote = _extract_inline_var(body, "lote")
        leilao = _extract_inline_var(body, "leilao")
        if not lote:
            self.log_event("at_lot_drop_no_json", url=response.url)
            return

        titulo = _normalize_text(lote.get("titulo") or "")
        descricao = _normalize_text(lote.get("descricao") or "")
        observacao_raw = lote.get("observacao") or ""
        # Limpa HTML da observação
        observacao = _normalize_text(re.sub(r"<[^>]+>", " ", html_mod.unescape(observacao_raw)))

        # Categoria: passa imóveis, rejeita veículos puros
        text_for_class = f"{titulo} {descricao}"
        has_im = bool(_IMOVEL_RE.search(text_for_class))
        has_ve = bool(_VEICULO_RE.search(text_for_class))
        if not has_im and has_ve:
            self.log_event("at_lot_drop_veiculo", url=response.url, title=titulo[:80])
            return
        # Tolerante quando sem sinais: usa título do <h1> se vazio
        if not titulo:
            self.log_event("at_lot_drop_empty_title", url=response.url)
            return
        if not has_im and not has_ve:
            # Sem sinal — confere se o leilão é tipo "Imóveis" (categoria
            # do leilão se disponível). Senão drop.
            categoria = (leilao or {}).get("categoria") or ""
            if "im" not in str(categoria).lower():
                self.log_event("at_lot_drop_ambiguous", url=response.url, title=titulo[:80])
                return

        loader = self.new_loader(response)
        loader.replace_value("auctioneer", "atlantico_leiloes")
        slc = response.meta.get("source_lot_code") or str(lote.get("id") or "")
        if slc:
            loader.add_value("source_lot_code", slc)
        loader.add_value("title", titulo)

        pt = _classify(titulo) or _classify(descricao)
        if pt:
            loader.add_value("property_type", pt)

        lot_num = lote.get("numero")
        if lot_num is not None:
            loader.add_value("lot_number", str(lot_num))

        # Valores monetários
        for k_min, lf in (("valorInicial", "minimum_bid"), ("valorInicial2", "minimum_bid")):
            v = lote.get(k_min)
            if v in (None, "", "0.00", "0"):
                continue
            try:
                # API devolve "79000.00" — formato decimal já normalizado
                _brl_to_decimal(v.replace(".", ",")) if "," not in v else _brl_to_decimal(v)
                loader.add_value(lf, str(v))
                break  # primeiro válido
            except Exception:
                continue

        # Status
        status_code = lote.get("status")
        if isinstance(status_code, int):
            loader.add_value("status", _STATUS_MAP.get(status_code, "desconhecido"))
        else:
            loader.add_value("status", "desconhecido")

        # Data da praça (do leilão)
        if leilao:
            data_p1 = (leilao.get("dataPraca1") or {}).get("date") if isinstance(leilao.get("dataPraca1"), dict) else None
            data_p2 = (leilao.get("dataPraca2") or {}).get("date") if isinstance(leilao.get("dataPraca2"), dict) else None
            if data_p1:
                # "2022-04-06 10:30:00.000000" → "2022-04-06T10:30:00-03:00"
                iso1 = self._to_iso(data_p1)
                if iso1:
                    loader.add_value("first_auction_date", iso1)
            if data_p2:
                iso2 = self._to_iso(data_p2)
                if iso2:
                    loader.add_value("second_auction_date", iso2)
                    loader.add_value("auction_phase", "2a_praca")
            elif data_p1:
                loader.add_value("auction_phase", "1a_praca")

        # Description: titulo + descricao + observacao
        desc_parts = [p for p in (descricao, observacao) if p]
        if desc_parts:
            full_desc = " — ".join(desc_parts)
            loader.add_value("description", full_desc[:10000])

        # Imagens: <img class="lote-img" data-src="..."> ou pswp__item img
        img_urls: list[str] = []
        for src in response.css(
            "img.lote-img::attr(src), img.lote-img::attr(data-src), "
            ".pswp__item img::attr(src)"
        ).getall():
            if not src:
                continue
            absolute = response.urljoin(src)
            if absolute not in img_urls:
                img_urls.append(absolute)
        if img_urls:
            loader.add_value("images", img_urls)

        # Documentos: links para PDFs (edital)
        docs = []
        for a in response.css("a[href$='.pdf']"):
            href = a.css("::attr(href)").get() or ""
            label = _normalize_text(" ".join(a.css("*::text").getall()))
            if href:
                docs.append({"name": label or "documento", "url": response.urljoin(href)})
        if docs:
            loader.add_value("documents", docs)

        # Cláusulas
        body_text_full = " ".join(response.css("body *::text").getall())
        payments, encumbrances = _parse_auction_clauses(body_text_full)
        if payments:
            loader.add_value("payment_options", payments)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        # Endereço — Atlântico não emite campo de endereço estruturado.
        # Extrai UF a partir do slug da URL (ex.: /lote/24/terreno-em-patos-pb).
        uf_slug = _uf_from_url_slug(response.url)
        if uf_slug:
            loader.add_value("address", {"uf": uf_slug, "raw_text": response.url})

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "at_lote_extracted",
            url=response.url,
            min_bid=item.get("minimum_bid"),
            status=item.get("status"),
            first=item.get("first_auction_date"),
        )
        yield item

    @staticmethod
    def _to_iso(dt_str: str) -> str | None:
        """'2022-04-06 10:30:00.000000' → '2022-04-06T10:30:00-03:00'."""
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})", dt_str)
        if not m:
            return None
        y, mo, d, h, mi, s = m.groups()
        return f"{y}-{mo}-{d}T{h}:{mi}:{s}-03:00"
