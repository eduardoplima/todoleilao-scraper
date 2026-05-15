"""Spider para tenants da plataforma Prism IT (www.prism.com.br).

Hosts conhecidos servidos pela mesma stack (server-rendered PHP + Bootstrap):
- hastapublica.com.br (EUCLIDES MARASCHI JUNIOR, 2 leiloeiros high)
- valland.com.br (MARCELO VALLAND, 1 high)

Marcador canônico: `<meta name="author" content="Prism IT - www.prism.com.br">`.

URLs:
- Home `/?page=N` — paginação de lotes ativos.
- Lote `/lote/{id}/{slug}`  — detalhe completo server-rendered.
- Leilão `/leilao/{id}/{slug}` — landing do evento (não usado: home cobre).

Estrutura do detail:
- Título: `<h4>1.0 - {slug}</h4>` no topo do `.pageLote`.
- `<dt>` rótulos: Valor da Ação, Leiloeiro Oficial, Número do Processo,
  Réu, Autor da Ação, Comitente, Abertura em, etc.
- Praças: vários `<dl>`s; "Lance Inicial" em outra área separada.
- Imagens: `<a class="example-image-link">` com URLs no S3 (cdnhp).
- Documentos: `ul.arquivos li a[href$='.pdf']` (Edital, Matrícula, Avaliação).
"""
from __future__ import annotations

import html as html_mod
import re
from decimal import InvalidOperation
from typing import Iterable

import scrapy

from leilao_scraper.spiders.base import BaseAuctionSpider
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _normalize_text,
    _parse_auction_clauses,
)


_LOT_HREF_RE = re.compile(r"/lote/(\d+)/[^\s\"'<)]+", re.I)
_BRL_RE = re.compile(r"R\$\s*([\d.,]+)")

DEFAULT_HOSTS: list[str] = [
    "https://www.hastapublica.com.br/",
    "https://www.valland.com.br/",
]


_IMOVEL_RE = re.compile(
    r"\b(im[óo]vel|im[óo]veis|apartamento|apto|casa|sobrado|kitnet|"
    r"cobertura|terreno|fazenda|ch[áa]cara|s[íi]tio|gleba|"
    r"sala\s+comercial|loja|galp[ãa]o|pr[ée]dio|edif[íi]cio|"
    r"resid[êe]ncial|comercial|industrial)\b",
    re.I,
)
_VEICULO_RE = re.compile(
    r"\b(autom[óo]vel|ve[íi]culo|porsche|bmw|land\s+rover|toyota|"
    r"caminh[ãa]o|motocicleta|trator|reboque|[ôo]nibus|placa\s+)\b",
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
    "fazenda": "rural",
    "chácara": "rural",
    "chacara": "rural",
    "sitio": "rural",
    "rural": "rural",
    "loja": "comercial",
    "sala": "comercial",
    "galpão": "comercial",
    "galpao": "comercial",
    "predio": "comercial",
    "edifício": "comercial",
    "industrial": "comercial",
    "comercial": "comercial",
}


def _classify(title: str) -> str | None:
    t = (title or "").lower()
    for key, val in _TYPE_MAP.items():
        if key in t:
            return val
    return None


def _dl_pairs(body: str) -> dict[str, str]:
    """Mapa label→value de todos os `<dl><dt>Label</dt><dd>Value</dd></dl>`.

    Mantém apenas valores texto limpos (sem tags internas). Em caso de
    múltiplas ocorrências, mantém a primeira.
    """
    out: dict[str, str] = {}
    for m in re.finditer(
        r"<dl[^>]*>\s*<dt[^>]*>(.+?)</dt>\s*<dd[^>]*>(.+?)</dd>",
        body, re.S | re.I,
    ):
        label = _normalize_text(re.sub(r"<[^>]+>", " ", m.group(1)))
        value = _normalize_text(re.sub(r"<[^>]+>", " ", m.group(2)))
        if label and label not in out:
            out[label] = value
    return out


class PrismLeiloesSpider(BaseAuctionSpider):
    name = "prism_leiloes"
    auctioneer_slug = "prism_leiloes"
    allowed_domains = ["hastapublica.com.br", "valland.com.br"]
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
    }

    MAX_PAGES = 15

    def __init__(self, sites: str = "all", urls: str | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if urls:
            self.start_urls = [u.strip() for u in urls.split(",") if u.strip()]
        else:
            if sites.lower() == "all":
                self.start_urls = list(DEFAULT_HOSTS)
            else:
                try:
                    limit = max(1, int(sites))
                except ValueError:
                    limit = len(DEFAULT_HOSTS)
                self.start_urls = DEFAULT_HOSTS[:limit]
        self._seen: dict[str, set[str]] = {}

    def start_requests(self) -> Iterable[scrapy.Request]:
        for url in self.start_urls:
            yield scrapy.Request(url, callback=self.parse, meta={"page": 1})

    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = (response.url.split("//", 1)[-1].split("/", 1)[0]).lower()
        host_seen = self._seen.setdefault(host, set())
        page = response.meta.get("page", 1)

        kept = 0
        new = 0
        for m in _LOT_HREF_RE.finditer(response.text):
            lot_id = m.group(1)
            absolute = response.urljoin(m.group(0))
            # Considera só do mesmo host
            if host not in absolute:
                continue
            kept += 1
            if lot_id in host_seen:
                continue
            host_seen.add(lot_id)
            new += 1
            yield scrapy.Request(
                absolute,
                callback=self.parse_property,
                meta={
                    "source_listing_url": response.url,
                    "source_lot_code": lot_id,
                    "host": host,
                },
            )

        self.log_event("prism_listing_done", host=host, page=page, kept=kept, new=new)

        # Paginação: continua enquanto vê novos lotes
        if new > 0 and page < self.MAX_PAGES:
            base = response.url.split("?")[0]
            yield scrapy.Request(
                f"{base}?page={page + 1}",
                callback=self.parse,
                meta={"page": page + 1},
            )

    def parse_property(self, response: scrapy.http.Response):
        body = response.text
        host = response.meta.get("host", "")
        body_text_full = " ".join(response.css("body *::text").getall())

        # Título — <h4> dentro do .pageLote
        h4 = response.xpath(
            "//article[contains(@class,'pageLote')]//h4[1]/text()"
        ).get()
        if not h4:
            h4 = response.css("article.pageLote h4::text").get()
        title = _normalize_text(h4 or "")
        if not title:
            self.log_event("prism_lot_drop_no_title", url=response.url)
            return

        # Strip prefix "1.0 - " ou "X.Y - " do título
        title_clean = re.sub(r"^\d+(?:\.\d+)?\s*-\s*", "", title)

        # Categoria
        has_im = bool(_IMOVEL_RE.search(title_clean))
        has_ve = bool(_VEICULO_RE.search(title_clean))
        if has_ve and not has_im:
            self.log_event("prism_lot_drop_veiculo", url=response.url, title=title_clean[:80])
            return

        # Também checa breadcrumb "<li>Imóveis ></li>"
        is_imovel_breadcrumb = "Imóveis" in body or "imóveis" in body[:5000]
        if not has_im and not has_ve and not is_imovel_breadcrumb:
            self.log_event("prism_lot_drop_ambiguous", url=response.url, title=title_clean[:80])
            return

        loader = self.new_loader(response)
        # Auctioneer slug pelo host
        host_slug = host.replace("www.", "").replace(".com.br", "").replace(".", "_")
        loader.replace_value("auctioneer", f"prism::{host_slug}")
        loader.add_value("source_lot_code", response.meta.get("source_lot_code"))
        loader.add_value("title", title_clean)

        pt = _classify(title_clean)
        if pt:
            loader.add_value("property_type", pt)

        # lot_number (1.0 → 1)
        m_lot = re.match(r"\s*(\d+)(?:\.\d+)?\s*-", title)
        if m_lot:
            loader.add_value("lot_number", m_lot.group(1))

        # Extrai pares dt/dd
        pairs = _dl_pairs(body)

        # market_value: "Valor da Ação" ou "Valor de Avaliação"
        market_value = None
        for k in ("Valor da Ação", "Valor de Avaliação", "Valor da Avaliação"):
            if k in pairs:
                m = _BRL_RE.search(pairs[k])
                if m:
                    try:
                        market_value = str(_brl_to_decimal(m.group(1)))
                        break
                    except (InvalidOperation, ValueError):
                        continue
        if market_value:
            loader.add_value("market_value", market_value)

        # minimum_bid: encontra "Lance Inicial" no body texto
        m_lance = re.search(
            r"Lance\s+Inicial[^R]{0,30}R\$\s*([\d.,]+)",
            body_text_full, re.I,
        )
        if m_lance:
            try:
                loader.add_value("minimum_bid", str(_brl_to_decimal(m_lance.group(1))))
            except (InvalidOperation, ValueError):
                pass

        # Data de abertura (primeira praça)
        abertura = pairs.get("Abertura em") or pairs.get("Abertura")
        if abertura:
            iso = self._date_to_iso(abertura)
            if iso:
                loader.add_value("first_auction_date", iso)
                loader.add_value("auction_phase", "1a_praca")

        # Comitente / processo → na description
        desc_parts = []
        for k in ("Comitente", "Número do Processo", "Réu", "Autor da Ação"):
            if k in pairs:
                desc_parts.append(f"{k}: {pairs[k]}")
        # Acrescenta o "Descrição" full HTML body se houver bloco
        m_desc = re.search(
            r'<h3[^>]*>\s*Descri[çc][ãa]o\s*</h3>\s*(.+?)(?=<h3|<section|</div>)',
            body, re.I | re.S,
        )
        if m_desc:
            raw = re.sub(r"<[^>]+>", " ", m_desc.group(1))
            desc_full = _normalize_text(html_mod.unescape(raw))
            if len(desc_full) > 20:
                desc_parts.append(desc_full)
        if desc_parts:
            loader.add_value("description", " — ".join(desc_parts)[:10000])

        # Status — Prism normalmente exibe "Encerrado" / "Aberto" em badge
        bt_low = body_text_full.lower()
        if "arrematad" in bt_low:
            status = "arrematado"
        elif "deserto" in bt_low or "sem lance" in bt_low:
            status = "cancelado"
        elif "cancelad" in bt_low or "sustad" in bt_low:
            status = "cancelado"
        elif "abertura em" in bt_low or "dê seu lance" in bt_low or "habilite" in bt_low:
            status = "aberto"
        else:
            status = "desconhecido"
        loader.add_value("status", status)

        # Imagens em S3 (cdnhp)
        imgs = []
        for src in response.css("a.example-image-link::attr(href), img.example-image::attr(src)").getall():
            if src and src.startswith("http") and src not in imgs:
                imgs.append(src)
        if imgs:
            loader.add_value("images", imgs)

        # Documentos
        docs = []
        for a in response.css("ul.arquivos a[href]"):
            href = a.css("::attr(href)").get() or ""
            label = _normalize_text(" ".join(a.css("*::text").getall()))
            if href.startswith("http") and href.lower().endswith(".pdf"):
                docs.append({"name": label or "documento", "url": href})
        if docs:
            loader.add_value("documents", docs)

        # Cláusulas
        payments, encumbrances = _parse_auction_clauses(body_text_full)
        if payments:
            loader.add_value("payment_options", payments)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "prism_lote_extracted",
            url=response.url,
            min_bid=item.get("minimum_bid"),
            market=item.get("market_value"),
            status=item.get("status"),
            first=item.get("first_auction_date"),
        )
        yield item

    @staticmethod
    def _date_to_iso(raw: str) -> str | None:
        """'13/05/2026' ou '13/05/2026 às 14:00' → ISO."""
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})(?:\s*(?:às\s*)?(\d{1,2}):(\d{2}))?", raw)
        if not m:
            return None
        d, mo, y, h, mi = m.groups()
        h = h or "00"
        mi = mi or "00"
        return f"{y}-{mo}-{d}T{int(h):02d}:{mi}:00-03:00"
