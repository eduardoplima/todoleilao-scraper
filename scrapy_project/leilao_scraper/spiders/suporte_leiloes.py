"""Spider para tenants do provider Suporte Leilões (SL).

Plataforma multi-tenant SaaS PHP (Symfony Encore + jQuery + Bootstrap)
operada via static.suporteleiloes.com.br. 51 tenants em
data/intermediate/site_providers.csv.

Recon arquitetural: specs/_providers/suporte_leiloes/.

Diferenças vs SOLEON:
  - Card de listagem é `article[class^='evento-index-{leilao_id}']`
    (não `div.lote`). Múltiplas praças aparecem como `<li>` em
    `ul.cont-datas`, cada uma com seu `small.valInit` (Lance Inicial
    da praça em questão). Detail page NÃO mostra Valor inicial —
    spider precisa propagar via meta.
  - Sem listing de encerrados (provider regenera datas; lots passados
    perdem badge de status). Acompanhamento exige re-crawl diário —
    cron Fly já cobre.
  - Histórico de lances público é boilerplate (3 propostas R$1,00
    do TiagoFelipe em todos os lots). Ignoramos.

Uso:
    scrapy crawl suporte_leiloes                       # 1 site (representante)
    scrapy crawl suporte_leiloes -a sites=5
    scrapy crawl suporte_leiloes -a sites=all
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urlparse

import scrapy

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.proprio_html_specific._common import _uf_from_url_slug
from leilao_scraper.spiders.soleon import (
    _BRL_RE,
    _brl_to_decimal,
    _card_category,
    _detail_is_imovel,
    _dedup_clauses,
    _extract_auctioneer,
    _extract_brl_from_og_title,
    _find_edital_url,
    _normalize_text,
    _parse_auction_clauses,
    _pdf_to_text,
)


class SuporteLeiloesSpider(ProviderSpider):
    name = "suporte_leiloes"
    provider_slug = "suporte_leiloes"
    auctioneer_slug = "suporte_leiloes"
    requires_playwright = False

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.5,
    }

    EVENTO_CLASS_RE = re.compile(r"evento-index-(\d+)")
    LOT_HREF_RE = re.compile(r"/lote/(\d+)/")

    # ------------------------------------------------------------------
    # Nível 1: home → cards de leilão
    # ------------------------------------------------------------------
    def parse(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        seen: set[str] = set()
        kept = 0
        dropped = 0
        for card in response.css("article[class^='evento-index-']"):
            klass = " ".join(card.css("::attr(class)").getall())
            m = self.EVENTO_CLASS_RE.search(klass)
            leilao_id = m.group(1) if m else None

            href = card.css("a[href*='/eventos/leilao/']::attr(href)").get()
            if not href:
                continue
            absolute = response.urljoin(href)
            if absolute in seen:
                continue
            seen.add(absolute)

            verdict = _card_category(card)
            if verdict is False:
                dropped += 1
                continue

            # Praças: cada <li> em ul.cont-datas. Captura Lance Inicial,
            # Abertura, Fechamento — propaga via meta porque o detail
            # não tem.
            rounds: list[dict] = []
            for li in card.css("ul.cont-datas li"):
                label = _normalize_text(" ".join(li.css("div.line-1 strong::text").getall()))
                # valInit: 'Valor inicial: R$ X,XX'
                vi_text = " ".join(li.css("small.valInit *::text, small.valInit::text").getall())
                vi_brl = _BRL_RE.search(vi_text)
                min_bid = None
                if vi_brl:
                    try:
                        min_bid = str(_brl_to_decimal(vi_brl.group(1)))
                    except Exception:
                        pass
                # Datas: cols com Abertura/Fechamento
                col_texts = [_normalize_text(" ".join(c.css("*::text").getall()))
                             for c in li.css("div.line-2 div.col-line")]
                rounds.append({
                    "label": label,
                    "minimum_bid": min_bid,
                    "dates_raw": col_texts,
                })

            # Status do badge
            status_class = " ".join(card.css("strong.strong-status::attr(class)").getall())
            status = _map_card_status(status_class)

            kept += 1
            yield self.make_request(
                absolute,
                callback=self.parse_evento,
                meta={
                    "source_listing_url": response.url,
                    "leilao_id": leilao_id,
                    "evento_rounds": rounds,
                    "evento_status": status,
                },
            )
        self.log_event(
            "sl_home_done",
            host=self.host_of(response.url),
            cards=kept + dropped,
            kept=kept,
            dropped=dropped,
        )

    # ------------------------------------------------------------------
    # Nível 2: evento — pode ser detail direto (single-lot) ou listagem
    # ------------------------------------------------------------------
    def parse_evento(self, response: scrapy.http.Response) -> Iterable[scrapy.Request]:
        if self.LOT_HREF_RE.search(response.url):
            yield from self.parse_property(response)
            return
        # Multi-lot: lista de lotes do leilão
        seen: set[str] = set()
        for href in response.css("a[href*='/lote/']::attr(href)").getall():
            if not self.LOT_HREF_RE.search(href):
                continue
            absolute = response.urljoin(href)
            if absolute in seen:
                continue
            seen.add(absolute)
            yield self.make_request(
                absolute,
                callback=self.parse_property,
                meta=response.meta,
            )

    # ------------------------------------------------------------------
    # Nível 3: detail → PropertyItem
    # ------------------------------------------------------------------
    def parse_property(self, response: scrapy.http.Response):
        # Suporte Leilões NÃO emite meta og:* nem meta description.
        # Fallbacks: <h1> como title, primeiro <p>/<div> de descrição
        # como desc. _detail_is_imovel é tolerante a inputs vazios.
        h1_title = (response.css("h1::text").get() or "").strip()
        desc_blob = " ".join(
            response.xpath(
                "//*[self::h2 or self::h3 or self::strong]"
                "[contains(., 'Descrição')]/following::*[1]//text()"
            ).getall()
        )[:600]
        if not _detail_is_imovel(h1_title, desc_blob):
            self.log_event(
                "sl_lote_dropped_non_imovel",
                url=response.url,
                h1=h1_title[:80],
            )
            return
        og_title = h1_title
        og_desc = desc_blob

        loader = self.new_loader(response)
        host = self.host_of(response.url)
        auctioneer = _extract_auctioneer(response)
        if auctioneer and auctioneer.get("full_name"):
            loader.replace_value("auctioneer", auctioneer["full_name"])
            loader.add_value("auctioneer_data", auctioneer)
        else:
            loader.replace_value("auctioneer", f"suporte_leiloes::{host}")

        # title — h1 (usa primeiro)
        title = (response.css("h1::text").get() or "").strip()
        if title:
            loader.add_value("title", title)

        # lot_number — vem da URL `/lote/{lot_id}/`
        m_lot = self.LOT_HREF_RE.search(response.url)
        if m_lot:
            loader.add_value("source_lot_code", m_lot.group(1))

        # status — do meta do card
        status = response.meta.get("evento_status", "desconhecido")
        loader.add_value("status", status)

        # market_value — Avaliação no painel
        avalia_text = " ".join(
            response.xpath(
                "//li[strong[contains(., 'Avaliação')]]//p//text() | "
                "//li[strong[contains(., 'Avaliação')]]//text()"
            ).getall()
        )
        m_av = _BRL_RE.search(avalia_text)
        if m_av:
            try:
                loader.add_value("market_value", str(_brl_to_decimal(m_av.group(1))))
            except Exception:
                pass

        # minimum_bid + datas — Suporte Leilões embute um JSON inline com
        # `valorInicial`, `valorInicial2`, `valorInicial3`, `data1`, `data2`,
        # `data3` no script da página de detalhe. É a fonte mais confiável
        # quando o card de listagem (rounds_meta) não trouxe os valores.
        json_bids, json_dates = _extract_json_pracas(response.text)

        rounds_meta: list[dict] = list(response.meta.get("evento_rounds") or [])
        first_min_bid = next(
            (r["minimum_bid"] for r in rounds_meta if r.get("minimum_bid")),
            None,
        )
        # Preferência: JSON inline (1ª praça) > card meta > og:title
        chosen_min_bid = (json_bids[0] if json_bids else None) or first_min_bid
        if not chosen_min_bid:
            chosen_min_bid = _extract_brl_from_og_title(og_title, "Lance Inicial")
        if chosen_min_bid:
            loader.add_value("minimum_bid", chosen_min_bid)

        # Datas: prefere JSON inline (data1=1ª praça, data2=2ª praça)
        # quando disponível; fallback para dates do card.
        first_dt = json_dates[0] if json_dates and len(json_dates) > 0 else None
        second_dt = json_dates[1] if json_dates and len(json_dates) > 1 else None

        if first_dt:
            loader.add_value("first_auction_date", first_dt)
        if second_dt:
            loader.add_value("second_auction_date", second_dt)
            loader.add_value("auction_phase", "2a_praca")
        elif first_dt:
            loader.add_value("auction_phase", "1a_praca")

        if not (first_dt or second_dt):
            if len(rounds_meta) >= 2:
                self._set_round_date(loader, rounds_meta[-1])
            elif rounds_meta:
                self._set_round_date(loader, rounds_meta[0])

        # description — Suporte Leilões embute JSON inline com `descricao`
        # do bem (mesmo texto que aparece no h1 + descrição expandida em
        # alguns casos). Parser simples por regex nos scripts da página.
        desc = None
        # 1. Tenta o bloco textual primeiro (algumas páginas têm)
        desc_nodes = response.xpath(
            "//*[self::h2 or self::h3 or self::strong][contains(., 'Descrição')]/following::*[self::p or self::div][1]"
        )
        if desc_nodes:
            raw = " ".join(desc_nodes[0].css("*::text").getall())
            desc = _normalize_text(raw)
        # 2. Fallback: JSON inline (`"descricao":"..."`). Preferimos a chave
        # `descricaoCompleta` ou `descricaoLeiloeiro` se existir; senão a
        # `descricao` simples (geralmente igual ao h1).
        if not desc or len(desc) < 30:
            for key in ("descricaoCompleta", "descricaoLeiloeiro", "descricao"):
                m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)+)"', response.text)
                if m and m.group(1).strip() and m.group(1) not in ("null", ""):
                    try:
                        import json
                        candidate = json.loads(f'"{m.group(1)}"')  # decodifica \uXXXX
                        if len(candidate) > 30 and (not desc or len(candidate) > len(desc)):
                            desc = candidate
                            break
                    except Exception:
                        continue
        if desc:
            loader.add_value("description", desc[:10000])

        # address — bloco "Localização" em texto livre
        addr_nodes = response.xpath(
            "//*[self::h2 or self::h3 or self::strong][contains(., 'Localização')]/following::*[1]"
        )
        addr_parsed: dict = {}
        if addr_nodes:
            addr_text = _normalize_text(" ".join(addr_nodes[0].css("*::text").getall()))
            if addr_text:
                addr_parsed = _parse_address_loose(addr_text)
                loader.add_value("address", addr_parsed)

        # Fallback: extrai UF do slug da URL quando o bloco de localização
        # não continha UF (ex.: endereço truncado ou ausente).
        # URLs Suporte Leilões: /eventos/leilao/<auction-slug>/lote/<id>/<lote-slug>
        # Tanto auction-slug como lote-slug podem terminar com "-rj", "-sp" etc.
        if not addr_parsed.get("uf"):
            uf = _uf_from_url_slug(response.url)
            if uf:
                addr_parsed["uf"] = uf
                loader.replace_value("address", addr_parsed)

        # images — CDN externa
        img_urls = response.css(
            "img[src*='static.suporteleiloes.com.br'][src*='/leiloes/']::attr(src), "
            "img[src*='static.suporteleiloes.com.br'][src*='/bens/']::attr(src)"
        ).getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            absolute = response.urljoin(u)
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs)

        # documents — PDF/DOC na CDN
        docs: list[dict] = []
        seen_doc_urls: set[str] = set()
        for a in response.css(
            "a[href*='static.suporteleiloes.com.br'][href*='.pdf'], "
            "a[href*='static.suporteleiloes.com.br'][href*='.doc'], "
            "a[href*='static.suporteleiloes.com.br'][href*='.docx']"
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

        # Cláusulas: HTML do detail + cláusulas gerais (similar ao SOLEON)
        page_text = _normalize_text(" ".join(response.css("body *::text").getall()))
        payment_options, encumbrances = _parse_auction_clauses(page_text)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self.log_event(
            "sl_lote_extracted",
            url=response.url,
            host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            mkt=item.get("market_value"),
        )
        yield item

        # Edital PDF parser fallback (mesma lógica do SOLEON)
        edital_url = _find_edital_url(item)
        if edital_url:
            yield self.make_request(
                edital_url,
                callback=self._merge_edital_clauses,
                cb_kwargs={"item_html": item},
                errback=self._on_edital_error,
                meta={
                    "handle_httpstatus_list": [403, 404],
                    "dont_obey_robotstxt": True,
                },
            )
        else:
            return  # já yielded item

    def _set_round_date(self, loader, round_meta: dict) -> None:
        """Tenta extrair Fechamento de col_line texts e popula second_auction_date."""
        for txt in round_meta.get("dates_raw") or []:
            # Padrões típicos: "Fechamento: DD/MM/YYYY HH:MM" ou só "DD/MM/YYYY HH:MM"
            m = re.search(r"(\d{2}/\d{2}/\d{4}[^,]{0,8}\d{2}:\d{2})", txt)
            if m:
                loader.add_value("second_auction_date", m.group(1))
                loader.add_value("auction_phase", "2a_praca")
                return

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


# ---------------------------------------------------------------------------
# Helpers locais
# ---------------------------------------------------------------------------

_CARD_STATUS_MAP = {
    "status-1":  "aberto",   # "Em breve" — futuro, mas frontend trata como aberto
    "status-3":  "aberto",   # "Aberto para lances"
    "status-96": "cancelado",
}


def _map_card_status(class_attr: str) -> str:
    classes = (class_attr or "").lower()
    for key, value in _CARD_STATUS_MAP.items():
        if key in classes:
            return value
    return "desconhecido"


_ADDRESS_PATTERN_RE = re.compile(
    r"^(?P<street>[^,]+?)(?:,\s*(?P<number>[\d\w/-]+))?"
    r"(?:,\s*(?P<district>[^-]+?))?"
    r"\s*-\s*"
    r"(?P<city>[^/-]+?)\s*[/-]\s*(?P<uf>[A-Z]{2})"
    r"(?:\.\s*CEP\s*[:\s]*(?P<cep>\d{5}-?\d{3}))?",
    re.I,
)


def _parse_address_loose(raw: str) -> dict:
    """Parser permissivo para endereços de Suporte Leilões.

    Formato típico: 'Rua X, 1026, Vila Y, São Paulo - SP. CEP 05688-021'.
    """
    cleaned = _normalize_text(raw)
    out: dict[str, Any] = {"raw_text": cleaned}
    m = _ADDRESS_PATTERN_RE.search(cleaned)
    if m:
        for k in ("street", "number", "district", "city", "uf", "cep"):
            v = m.group(k)
            if v:
                out[k.replace("city", "municipality_name").replace("uf", "uf")] = v.strip()
    # Tenta UF/cidade no final mesmo se padrão completo não bater
    if "uf" not in out:
        m2 = re.search(r"([A-ZÀ-Úa-zà-ú\s.'-]+?)\s*[/-]\s*([A-Z]{2})\b", cleaned)
        if m2:
            out["municipality_name"] = m2.group(1).strip()
            out["uf"] = m2.group(2)
    return out


# Regex para os campos do JSON inline da Suporte Leilões.
# valorInicial (1ª praça), valorInicial2 (2ª praça), valorInicial3 (3ª praça)
_VALOR_INICIAL_RE = re.compile(
    r'"valorInicial(\d?)"\s*:\s*([\d.]+)'
)
# data1/data2/data3 são objetos com "date":"YYYY-MM-DD HH:MM:SS.UUUUUU"
_DATA_PRACA_RE = re.compile(
    r'"data(\d)"\s*:\s*\{[^}]*?"date"\s*:\s*"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})'
)


def _extract_json_pracas(html: str) -> tuple[list[str], list[str]]:
    """Extrai (lista de min_bids brl, lista de datas BR) do JSON inline.

    min_bids = ['valorInicial', 'valorInicial2', 'valorInicial3'] ordenadas.
    datas    = ['data1', 'data2', 'data3'] ordenadas (formato 'DD/MM/YYYY HH:MM').

    Cada praça pode estar ausente; o índice mantém a ordem.
    """
    bids_by_n: dict[int, str] = {}
    for m in _VALOR_INICIAL_RE.finditer(html or ""):
        n_str = m.group(1) or "1"  # valorInicial == 1ª praça
        n = int(n_str)
        val = m.group(2)
        # Trata "0", "0.0" como ausente (lots sem 2ª praça)
        try:
            if float(val) <= 0:
                continue
        except ValueError:
            continue
        if n in bids_by_n:
            continue  # mantém o primeiro match (do bloco do próprio lote)
        # Trunca pra 2 decimais (JSON da Suporte Leilões emite floats sujos
        # com 30+ casas: "597078.93000000005122274160385131..." causaria
        # InvalidOperation no Decimal). Converte via Decimal pra preservar
        # precisão monetária.
        try:
            from decimal import Decimal, ROUND_HALF_UP
            quantized = Decimal(val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            bids_by_n[n] = str(quantized)
        except Exception:
            bids_by_n[n] = val
    bids = [bids_by_n[k] for k in sorted(bids_by_n.keys())]

    dates_by_n: dict[int, str] = {}
    for m in _DATA_PRACA_RE.finditer(html or ""):
        n = int(m.group(1))
        # "2026-05-27 10:00:00" → "27/05/2026 10:00"
        iso = m.group(2)
        try:
            y, mo, d = iso[:4], iso[5:7], iso[8:10]
            h, mi = iso[11:13], iso[14:16]
            dates_by_n[n] = f"{d}/{mo}/{y} {h}:{mi}"
        except (IndexError, ValueError):
            continue
    dates = [dates_by_n[k] for k in sorted(dates_by_n.keys())]
    return bids, dates
