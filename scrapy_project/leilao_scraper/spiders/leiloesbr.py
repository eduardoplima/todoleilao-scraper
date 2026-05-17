"""Spider para tenants do provider LeilõesBR.

Plataforma SaaS ASP clássica (peca.asp + catalogo.asp) usada por ~17
leiloeiros do INNLEI: AW Leilões, Levy Leiloeiro, Evânio Alves, PRH,
FCE Leilões, Casa Amarela, TB Aracaju, Bastos, João de Franco etc.
Endereço corporativo: https://www.leiloesbr.com.br.

NÃO confundir com `leilao.br` (provider distinto, plataforma diferente).

Recon: specs/_providers/leiloesbr/.

Templates conhecidos:

  Template 1 — Mustache+loadData (FCE, peças/numismática):
    <script>var loadData = {data: [{TITULO, PECA, MINI_DESCRICAO,
    VALOR_CONTRATADO, VALOR_VENDA, NOVO_VALOR, LOTENUM, URLMETA, ...}],
    listalotes: [...], navinfo: {...}};</script>
    O HTML server-side é só um shell; Mustache hidrata `data[0]` no carregamento.

  Template 2 — Server-side render (Levy, Evânio, PRH, AW):
    HTML completo com bloco "Peça" → div.lote-desc.text-list p.
    Preço em <span class="is-rs">R$</span><span class="is-valor">N</span>.
    Hidden inputs: ValorMinimo, IdLeilao, IdPeca.

Limitações:
  - Lots cross-tenant: Id no peca.asp é global; o mesmo Id aparece em
    múltiplos catálogos. Spider usa o host do response para `auctioneer`
    e o Id como `source_lot_code` — duplicação é resolvida no UPSERT
    do pipeline.
  - Histórico de lances: server-side render mostra apenas total ("0
    lance(s)"); detalhes individuais requerem login.
  - Filtro de imóvel: o catálogo de boa parte dos tenants é misto (arte,
    livros, antiguidades, joias, imóveis). Filtramos via título/desc
    com `_detail_is_imovel` da SOLEON.

Uso:
    scrapy crawl leiloesbr -a sites=1
    scrapy crawl leiloesbr -a urls=https://www.awleiloes.com.br/
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

import scrapy

from leilao_scraper.spiders._common_ua import BROWSER_USER_AGENT
from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _BRL_RE,
    _brl_to_decimal,
    _detail_is_imovel,
    _normalize_text,
    _parse_auction_clauses,
)


# Regex para extrair Id da peça do path
_PECA_ID_RE = re.compile(r"/peca\.asp\?Id=(\d+)", re.I)
_CATALOGO_NUM_RE = re.compile(r"/catalogo\.asp\?Num=(\d+)", re.I)


class LeiloesbrSpider(ProviderSpider):
    name = "leiloesbr"
    provider_slug = "leiloesbr"
    auctioneer_slug = "leiloesbr"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
        "USER_AGENT": BROWSER_USER_AGENT,
    }

    def start_requests(self) -> Iterable[Any]:
        self._open_incremental_db()
        self._listing_seen: set[str] = set()  # host:peca_id já visitados
        yield from super().start_requests()

    def closed(self, reason: str) -> None:
        self.close_incremental_db()

    # ------------------------------------------------------------------
    # Nível 1: home do tenant → segue catalogo.asp + peca.asp diretos
    # ------------------------------------------------------------------
    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = self.host_of(response.url)

        # 1a) Catálogos abertos linkados na home
        cat_hrefs: set[str] = set()
        for href in response.css("a[href*='/catalogo.asp']::attr(href)").getall():
            absolute = response.urljoin(href).split("#")[0]
            if absolute in cat_hrefs:
                continue
            cat_hrefs.add(absolute)
            yield self.make_request(
                absolute,
                callback=self.parse_catalogo,
                meta={"host": host, "source_listing_url": response.url},
            )

        # 1b) Peças destacadas na home (alguns tenants listam direto)
        for req in self._extract_peca_requests(response, host):
            yield req

        self.log_event(
            "lbr_home_done",
            host=host,
            n_catalogos=len(cat_hrefs),
        )

    # ------------------------------------------------------------------
    # Nível 2: catalogo.asp → emite peca.asp requests
    # ------------------------------------------------------------------
    def parse_catalogo(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        host = response.meta["host"]
        yield from self._extract_peca_requests(response, host)

    def _extract_peca_requests(
        self, response: scrapy.http.Response, host: str
    ) -> Iterable[scrapy.Request]:
        n_kept = 0
        n_seen = 0
        for href in response.css("a[href*='/peca.asp?Id=']::attr(href)").getall():
            absolute = response.urljoin(href).split("#")[0]
            m = _PECA_ID_RE.search(absolute)
            if not m:
                continue
            peca_id = m.group(1)
            key = f"{host}:{peca_id}"
            if key in self._listing_seen:
                continue
            self._listing_seen.add(key)
            n_seen += 1

            if self.lot_exists(host, peca_id):
                yield self.make_listing_only_item(
                    url=absolute,
                    source_lot_code=peca_id,
                    auctioneer=f"leiloesbr::{host}",
                )
                n_kept += 1
                continue

            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta={
                    "host": host,
                    "source_listing_url": response.url,
                    "peca_id": peca_id,
                },
            )
            n_kept += 1

        self.log_event(
            "lbr_catalogo_done",
            url=response.url,
            host=host,
            new_links=n_seen,
            emitted=n_kept,
        )

    # ------------------------------------------------------------------
    # Nível 3: peca.asp → PropertyItem
    # ------------------------------------------------------------------
    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("host", self.host_of(response.url))
        peca_id = response.meta.get("peca_id") or (
            _PECA_ID_RE.search(response.url).group(1)
            if _PECA_ID_RE.search(response.url)
            else None
        )

        # Detecta template via loadData inline
        load_data = _parse_load_data(response.text)
        # Mescla campos: prefere loadData quando disponível, fallback no DOM
        title, desc, min_bid, mkt_value, leilao_dt, location, lotenum, images, urlmeta = (
            None, None, None, None, None, None, None, [], None,
        )

        if load_data:
            d0 = load_data
            title = d0.get("TITULO") or d0.get("MINI_DESCRICAO")
            desc = d0.get("DESCRICAO") or d0.get("MINI_DESCRICAO2")
            # Strip HTML tags
            if desc:
                desc = _normalize_text(re.sub(r"<[^>]+>", " ", desc))
            min_bid = _to_brl(d0.get("VALOR_VENDA") or d0.get("VALOR_VALUE")
                              or d0.get("NOVO_VALOR"))
            mkt_value = _to_brl(d0.get("VALOR_CONTRATADO"))
            location = d0.get("LOCALTXT")
            lotenum = d0.get("LOTENUM")
            urlmeta = d0.get("URLMETA")
            # Imagens via VPASTA / CLOUD_LINK
            cloud_link = d0.get("CLOUD_LINK") or d0.get("LOCAL_LINK")
            vpasta = d0.get("VPASTA")
            id_leilao = d0.get("ID_LEILAO")
            if cloud_link and id_leilao and peca_id:
                # Padrão: {cloud}/imagens/img_m/{id_leilao}/{peca_id}.jpg
                base = cloud_link.rstrip("/")
                images.append(f"{base}/imagens/img_m/{id_leilao}/{peca_id}.jpg")

        # Template 2 — server-side render
        if not title:
            title_node = (
                response.css("div.lote-desc.text-list p::text").get()
                or response.css("meta[property='og:title']::attr(content)").get()
            )
            title = (title_node or "").strip()

        if not desc:
            # Pega description bloco inteiro
            raw_desc = " ".join(
                response.css("div.lote-desc.text-list *::text, "
                             "div.lote-desc *::text").getall()
            )
            desc = _normalize_text(raw_desc)

        # Filtro de imóvel
        og_desc = (
            response.css("meta[property='og:description']::attr(content)").get() or ""
        )
        # Use title + description; loadData TIPO field também pode ajudar
        check_text = (title or "") + " " + (desc or "") + " " + og_desc
        if not _detail_is_imovel(title or "", check_text):
            self.log_event(
                "lbr_lot_dropped_non_imovel",
                url=response.url,
                host=host,
                title=(title or "")[:80],
            )
            return

        if not min_bid:
            # input hidden ValorMinimo
            vm = response.css("input[name='ValorMinimo']::attr(value)").get()
            if vm:
                min_bid = _to_brl(vm)
        if not min_bid:
            # span.is-valor proximo a "Valor Inicial:" ou "Lance Mínimo:"
            for valor_text in response.css(
                "li.valor-atual *::text, p.search-login *::text"
            ).getall():
                m = _BRL_RE.search(valor_text)
                if m:
                    parsed = _to_brl(m.group(1))
                    if parsed:
                        min_bid = parsed
                        break

        # Data do leilão — template 2: <a data-reveal-id="leilao-modal">DD/MM/YYYY</a>
        if not leilao_dt:
            dia = response.css("a[data-reveal-id='leilao-modal']::text").get()
            if dia and re.search(r"\d{1,2}/\d{1,2}/\d{4}", dia):
                leilao_dt = dia.strip()

        if not location:
            local_link = response.css("a[data-reveal-id='local-modal']::text").get()
            if local_link:
                location = local_link.strip()

        # Imagens — template 2
        if not images:
            cdn_imgs = response.css(
                "img[src*='cloudfront.net/imagens/']::attr(src)"
            ).getall()
            images.extend(response.urljoin(u) for u in cdn_imgs if u)

        # Dedup imagens
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in images:
            if u and u not in seen_imgs:
                seen_imgs.add(u)
                unique_imgs.append(u)

        # documentos — PDFs no body (raros)
        docs: list[dict] = []
        seen_doc: set[str] = set()
        for a in response.css("a[href$='.pdf']"):
            url = a.css("::attr(href)").get()
            label = _normalize_text(" ".join(a.css("*::text").getall())) or "documento"
            if not url:
                continue
            abs_url = response.urljoin(url)
            if abs_url in seen_doc:
                continue
            seen_doc.add(abs_url)
            docs.append({"name": label, "url": abs_url})

        # status — leiloesbr template não tem badge claro; default aberto
        body_text = _normalize_text(" ".join(response.css("body *::text").getall())).lower()
        if "arrematado" in body_text:
            status = "arrematado"
        elif "leilão encerrado" in body_text or "encerrado em" in body_text:
            status = "desconhecido"
        elif "suspens" in body_text:
            status = "suspenso"
        elif "cancel" in body_text:
            status = "cancelado"
        else:
            status = "aberto"

        # Auctioneer ele mesmo — buscar nome no header/footer ou no loadData
        # Template 2: <h4>Patricia Levy - Leiloeira Oficial</h4>
        auct_name = None
        for h in response.css("h4::text").getall():
            t = (h or "").strip()
            if "leiloei" in t.lower() and t.startswith(tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")):
                auct_name = t
                break

        # Cláusulas — texto livre da página
        page_text = _normalize_text(
            " ".join(response.css("body *::text").getall())
        )
        payment_options, encumbrances = _parse_auction_clauses(page_text)

        loader = self.new_loader(response)
        loader.replace_value(
            "auctioneer",
            auct_name or f"leiloesbr::{host}",
        )
        if peca_id:
            loader.add_value("source_lot_code", peca_id)
        if title:
            loader.add_value("title", title)
        if desc:
            loader.add_value("description", desc[:10000])
        if min_bid is not None:
            loader.add_value("minimum_bid", str(min_bid))
        if mkt_value is not None:
            loader.add_value("market_value", str(mkt_value))
        loader.add_value("status", status)
        if lotenum:
            loader.add_value("lot_number", str(lotenum))
        if leilao_dt:
            # ISO normalization handled by loader
            loader.add_value("second_auction_date", leilao_dt)
            loader.add_value("auction_phase", "2a_praca")
        if location:
            addr = _parse_location(location)
            if addr:
                loader.add_value("address", addr)
        if unique_imgs:
            loader.add_value("images", unique_imgs)
        if docs:
            loader.add_value("documents", docs)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "lbr_lot_extracted",
            url=response.url,
            host=host,
            peca_id=peca_id,
            template=("load_data" if load_data else "ssr"),
            min_bid=item.get("minimum_bid"),
            mkt=item.get("market_value"),
            imgs=len(item.get("images") or []),
        )
        yield item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_load_data(html_text: str) -> dict | None:
    """Extrai `loadData.data[0]` do <script>var loadData={...};</script>.

    Retorna None quando o template é server-side (sem loadData inline).
    """
    if not html_text or "var loadData" not in html_text:
        return None
    m = re.search(r"var\s+loadData\s*=\s*(\{.*?\});", html_text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    data = obj.get("data") if isinstance(obj, dict) else None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


def _to_brl(value) -> Decimal | None:
    """'1234.56' / '1.234,56' / 1234.56 / 'R$ 1.234,56' → Decimal.

    LeilõesBR usa formatos diferentes: VALOR_VENDA é tipicamente "1234.56"
    (decimal US), MINI_DESCRICAO2 traz "R$ 1.234,56" (BR formal). Heurística:
    se contém vírgula, é BR (`,` decimal); senão US (`.` decimal).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    # Remove R$ prefix
    s = re.sub(r"^R\$\s*", "", s, flags=re.I)
    # Heurística
    if "," in s:
        # BR: "." é milhar, "," é decimal
        s = s.replace(".", "").replace(",", ".")
    # else: US, deixa como está
    try:
        v = Decimal(s)
        return v if v > 0 else None
    except (InvalidOperation, ValueError):
        return None


def _parse_location(loc: str) -> dict | None:
    """'Rio de Janeiro - RJ' → {municipality_name, uf, raw_text}."""
    if not loc:
        return None
    s = _normalize_text(loc)
    m = re.match(r"^(.+?)\s*[-/]\s*([A-Z]{2})\s*$", s)
    if m:
        return {
            "raw_text": s[:300],
            "municipality_name": m.group(1).strip(),
            "uf": m.group(2),
        }
    return {"raw_text": s[:300]}
