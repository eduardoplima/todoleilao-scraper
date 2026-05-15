"""Spider para o provider SISHP (PHP server-render, asset prefix `/sishp/...`).

Tenants conhecidos: `sfrazao.com.br`, `lancenoleilao.com.br`,
`lancetotal.com.br`. Mesmo template PHP, mesmas rotas, sem JS dinâmico.

Estratégia
==========

1. Home (`/`) é a listagem de **LEILÕES** (cards `div.card.card-1` com
   onClick `goTo('leilao.php?idLeilao=N')`). Cobre ativos + encerrados.
2. Página do leilão (`/leilao.php?idLeilao=N`) lista os **LOTES** via
   anchors `<a href="lote.php?idLote=M">`.
3. Detalhe do lote (`/lote.php?idLote=M`) traz title (`<h1>`), descrição,
   imagens (`/sishp/leilao/N/fotos/M_NN.jpg`), datas e valores em
   `Encerramento, valores e lances`.

Recon: `specs/_providers/sishp/recon.md`.

Uso
===

```
scrapy crawl sishp -a sites=2
scrapy crawl sishp -a urls=https://www.sfrazao.com.br
```
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Iterable
from urllib.parse import urljoin, urlparse

import scrapy

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _normalize_text,
    _parse_br_datetime_iso,
)


_LEILAO_RE = re.compile(r"leilao\.php\?idLeilao=(\d+)")
_LOTE_RE = re.compile(r"lote\.php\?idLote=(\d+)")

# "07/Mar/2024, 10h00" → ISO
_DT_HEADER_RE = re.compile(
    r"(\d{1,2})/([A-Za-zçÇ]+)/(\d{4})[,\s]+(\d{1,2})h(\d{2})",
    re.I,
)
_MONTH_PT_SHORT = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}


def _parse_dt_header(text: str) -> str | None:
    if not text:
        return None
    m = _DT_HEADER_RE.search(text)
    if not m:
        return _parse_br_datetime_iso(text)
    d, mname, y, h, mi = m.groups()
    mnum = _MONTH_PT_SHORT.get(mname[:3].lower())
    if not mnum:
        return None
    return f"{y}-{mnum:02d}-{int(d):02d}T{int(h):02d}:{mi}:00-03:00"


# Filtros de imóvel a partir do título do leilão/lote
_RE_IMOVEL_TITLE = re.compile(
    r"\b(im[óo]ve(?:l|is)|imove(?:l|is)|casa|apartamento|apto|sobrado|kitnet|"
    r"loja|sala|comercial|terreno|ch[áa]cara|fazenda|s[íi]tio|[áa]rea|rural|"
    r"galp[ãa]o|gleba|edif[íi]cio|pr[ée]dio|cobertura|flat|loft)\b",
    re.I,
)
_RE_NOT_IMOVEL = re.compile(
    r"\b(ve[íi]culo|motocicleta|moto|caminh[ãa]o|m[áa]quina|equipamento|"
    r"semovente|gado|bovino|cavalo|tratorr?|colheitadeira)\b",
    re.I,
)


def _is_imovel(text: str) -> bool:
    t = text or ""
    if _RE_NOT_IMOVEL.search(t) and not _RE_IMOVEL_TITLE.search(t):
        return False
    return bool(_RE_IMOVEL_TITLE.search(t))


_RE_PROP_TYPE = {
    "apartamento": "apartamento",
    "apto": "apartamento",
    "casa": "casa",
    "sobrado": "casa",
    "terreno": "terreno",
    "gleba": "terreno",
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
    "comercial": "comercial",
}


def _classify(title: str) -> str | None:
    t = (title or "").lower()
    for key, val in _RE_PROP_TYPE.items():
        if key in t:
            return val
    return "outro" if _is_imovel(title) else None


class SishpSpider(ProviderSpider):
    name = "sishp"
    provider_slug = "sishp"
    auctioneer_slug = "sishp"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_leiloes: set[str] = set()
        self._seen_lotes: set[str] = set()

    # ----- Nível 1: home → leilões -----------------------------------------

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)
        # Cards de leilão com onClick goTo('leilao.php?idLeilao=N').
        # Também há `href="leilao.php?idLeilao=N"` em outros pontos.
        onclick_ids = set(_LEILAO_RE.findall(
            " ".join(response.css("[onclick]::attr(onclick)").getall())
        ))
        href_ids = set(_LEILAO_RE.findall(
            " ".join(response.css("a::attr(href)").getall())
        ))
        all_ids = onclick_ids | href_ids
        self.log_event("sishp_home_leiloes", host=host, count=len(all_ids))
        for leilao_id in all_ids:
            if leilao_id in self._seen_leiloes:
                continue
            self._seen_leiloes.add(leilao_id)
            url = urljoin(response.url, f"leilao.php?idLeilao={leilao_id}")
            yield self.make_request(
                url,
                callback=self.parse_leilao,
                meta={"source_listing_url": response.url, "broker_host": host},
            )

    # ----- Nível 2: leilao.php → lotes -------------------------------------

    def parse_leilao(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = response.meta.get("broker_host") or self.host_of(response.url)
        # Capta hrefs e onclicks lote.php
        body = response.text
        ids = set(_LOTE_RE.findall(body))
        kept = 0
        for lote_id in ids:
            if lote_id in self._seen_lotes:
                continue
            self._seen_lotes.add(lote_id)
            kept += 1
            url = urljoin(response.url, f"lote.php?idLote={lote_id}")
            yield self.make_request(
                url,
                callback=self.parse_property,
                meta={
                    "source_listing_url": response.url,
                    "broker_host": host,
                    "source_lot_code": lote_id,
                },
            )
        self.log_event("sishp_leilao_done", url=response.url, kept=kept)

    # ----- Nível 3: lote.php → PropertyItem --------------------------------

    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("broker_host") or self.host_of(response.url)
        h1 = (response.css("h1::text").get() or "").strip()
        body_text = " ".join(response.css("body *::text").getall())[:8000]

        if not _is_imovel(h1) and not _is_imovel(body_text[:2000]):
            self.log_event("sishp_dropped_non_imovel", url=response.url,
                           title=h1[:80])
            return

        loader = self.new_loader(response)
        loader.replace_value("auctioneer", f"sishp::{host}")

        slc = response.meta.get("source_lot_code")
        if not slc:
            m = _LOTE_RE.search(response.url)
            if m:
                slc = m.group(1)
        if slc:
            loader.add_value("source_lot_code", slc)

        if h1:
            loader.add_value("title", h1)

        ptype = _classify(h1)
        if ptype:
            loader.add_value("property_type", ptype)

        # Descrição: bloco "Descrição do lote" — text node antes do próximo
        # form-title. Vamos extrair tudo entre os spans `Descrição do lote`
        # e `Encerramento, valores e lances`.
        descr_match = re.search(
            r'form-title[^>]*>\s*Descri[çc][ãa]o do lote.*?</span>(.*?)<span[^>]*form-title',
            response.text, re.S | re.I,
        )
        if descr_match:
            raw = descr_match.group(1)
            # Substitui <br> por espaço e remove tags
            cleaned = re.sub(r"<br\s*/?>", " ", raw, flags=re.I)
            cleaned = re.sub(r"<[^>]+>", " ", cleaned)
            desc = _normalize_text(cleaned)
            if len(desc) > 30:
                loader.add_value("description", desc[:10000])

        # Datas: header tem "Abertura: DD/Mes/YYYY, HHhMM" + "Encerramento: ..."
        m_open = re.search(r"Abertura:\s*([^<]+?)(?:<br>|Encerramento)", response.text)
        m_close = re.search(r"Encerramento:\s*([^<]+?)(?:</span>|<br>|$)", response.text)
        first_date = None
        if m_open:
            first_date = _parse_dt_header(m_open.group(1))
        if first_date:
            loader.add_value("first_auction_date", first_date)
            loader.add_value("auction_phase", "unica")

        # Avaliação / Lance Mínimo (estrutura tabular row/col).
        # Label e valor vivem em divs irmãos; usar regex tolerante.
        av_m = re.search(
            r"Avalia[çc][ãa]o\s*:.{0,400}?R\$\s*([\d.,]+)",
            response.text, re.I | re.S,
        )
        if av_m:
            try:
                loader.add_value("market_value", str(_brl_to_decimal(av_m.group(1))))
            except Exception:
                pass

        min_m = re.search(
            r"Lance\s+M[íi]nimo\s*:.{0,400}?R\$\s*([\d.,]+)",
            response.text, re.I | re.S,
        )
        if min_m:
            try:
                loader.add_value("minimum_bid", str(_brl_to_decimal(min_m.group(1))))
            except Exception:
                pass

        # Encerramento (data DD/MM/YYYY a partir das HH:MM:SS)
        m_enc = re.search(
            r"Encerramento\s*:.{0,400}?(\d{2}/\d{2}/\d{4})\s*(?:a partir das\s+)?(\d{2}:\d{2})",
            response.text, re.I | re.S,
        )
        if m_enc and not first_date:
            dt = _parse_br_datetime_iso(f"{m_enc.group(1)} {m_enc.group(2)}")
            if dt:
                loader.add_value("first_auction_date", dt)
                loader.add_value("auction_phase", "unica")

        # Status — texto do badge: Vendido | Encerrado | Sem licitantes | Em andamento
        bt_low = body_text.lower()
        if "vendido" in bt_low or "arrematad" in bt_low:
            status = "arrematado"
        elif "sem licitante" in bt_low or "encerrad" in bt_low:
            status = "desconhecido"
        elif "cancelad" in bt_low:
            status = "cancelado"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # Endereço — bloco "Localização do bem" tem <a href=maps...>{texto}</a>
        addr_text = response.css(
            "a[href*='maps.google.com']::text, a[href*='/maps?']::text"
        ).get()
        if addr_text:
            addr_text = _normalize_text(addr_text)
            addr: dict = {"raw_text": addr_text}
            # "Rua X - Bairro - Cidade/UF"
            m_uf = re.search(r"/\s*([A-Z]{2})\s*$", addr_text)
            if m_uf:
                addr["uf"] = m_uf.group(1)
            parts = [p.strip() for p in re.split(r"\s+-\s+", addr_text)]
            if parts:
                addr["street_name"] = parts[0]
            if len(parts) >= 3:
                addr["district"] = parts[-2]
                # último é "Cidade/UF"
                last = parts[-1]
                m_city = re.match(r"^(.+?)\s*/\s*[A-Z]{2}\s*$", last)
                if m_city:
                    addr["municipality_name"] = m_city.group(1).strip()
            loader.add_value("address", addr)

        # Área: parsear título "TERRENO C/X,YM² AT" ou "CASA C/AAA M² AC E BB M² AT"
        m_at = re.search(
            r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?)\s*[mM][²2]\s*(?:de\s+)?(?:AT|área\s+total|area\s+total)",
            h1 + " " + body_text[:2000], re.I,
        )
        if m_at:
            try:
                # Brasileiro: 8.831,53 → 8831.53
                raw = m_at.group(1).replace(".", "").replace(",", ".")
                loader.add_value("total_area_sqm", str(Decimal(raw)))
            except Exception:
                pass
        m_ac = re.search(
            r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?)\s*[mM][²2]\s*(?:de\s+)?(?:AC|área\s+constru|area\s+constru)",
            h1 + " " + body_text[:2000], re.I,
        )
        if m_ac:
            try:
                raw = m_ac.group(1).replace(".", "").replace(",", ".")
                loader.add_value("area_sqm", str(Decimal(raw)))
            except Exception:
                pass

        # Imagens — `img[src*='sishp/leilao/']`
        imgs: list[str] = []
        for src in response.css("img[src*='sishp/leilao/']::attr(src)").getall():
            if not src:
                continue
            absolute = response.urljoin(src)
            if absolute not in imgs:
                imgs.append(absolute)
        if imgs:
            loader.add_value("images", imgs)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "sishp_lote_extracted",
            url=response.url,
            host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            market=item.get("market_value"),
        )
        yield item
