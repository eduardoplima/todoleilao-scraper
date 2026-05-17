"""Schulmann Leilões (schulmannleiloes.com.br) — leiloeiro RJ.

Problema do genérico:
  - Template tem DOIS `<h1>` tags: o primeiro é `<h1 class="assistive-text">
    Menu principal</h1>` (accessibility heading), o segundo é o
    `<h1 id="featured-heading" class="entry-title labasoft_h1">` que
    contém o nome real do lote (ex.: "SALA NO EDIF. CENTRAL15 - Eletrônico - Judicial").
  - Não há `<meta property="og:title">`, então `og_title = h1 = "Menu principal"`.
  - `_detail_is_imovel("Menu principal", body_text[:3000])` retorna False
    porque o texto do edital começa só após o cabeçalho — `imóvel` aparece
    a partir do char ~8700, longe do cutoff de 3000.
  - Resultado: TODOS os ~51 lotes de imóveis do edital são dropados
    como "non_imovel" pelo genérico, render bom mas filtro errado.

Fix: override `parse_property` para usar o `h1.entry-title` em vez do
primeiro `<h1>`, e estender o scope do body_text na checagem de imóvel.
O resto da pipeline (preços via `_PRICE_*`, imagens, etc.) reaproveita.

Smoke (manual, 17 mai 2026):
  $ scrapy crawl schulmann_leiloes -a urls=https://schulmannleiloes.com.br/ \
      -s CLOSESPIDER_ITEMCOUNT=5
  → ≥5 itens emitidos, todos com `status=aberto` e título tipo
    "SALA NO EDIF. CENTRAL15 - Eletrônico - Judicial".
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

import scrapy

from leilao_scraper.spiders.proprio_html import (
    _PRICE_AVALIACAO,
    _PRICE_LANCE_MIN,
    _PRICE_PRACA_1,
    _PRICE_PRACA_2,
    ProprioHtmlSpider,
)
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _detail_is_imovel,
    _extract_auctioneer,
    _find_edital_url,
    _normalize_text,
    _parse_auction_clauses,
)


class SchulmannLeiloesSpider(ProprioHtmlSpider):
    name = "schulmann_leiloes"
    provider_slug = "schulmann_leiloes"
    auctioneer_slug = "schulmann_leiloes"

    def parse_property(self, response: scrapy.http.Response):
        host = response.meta.get("host", self.host_of(response.url))

        # Pega o h1 de conteúdo (skip "Menu principal" da acessibilidade)
        title_h1 = (
            response.css("h1#featured-heading::text").get()
            or response.css("h1.entry-title::text").get()
            or response.css("h1:not(.assistive-text)::text").get()
            or response.css("h1::text").get()
            or ""
        ).strip()
        # Normaliza: remove sufixos de modalidade ("- Eletrônico - Judicial")
        # mantendo só o nome do lote
        title = title_h1

        og_title = (
            response.css("meta[property='og:title']::attr(content)").get()
            or title
        )
        og_desc = (
            response.css("meta[property='og:description']::attr(content)").get()
            or ""
        )

        body_text = _normalize_text(
            " ".join(response.css("body *::text").getall())
        )

        # Schulmann mistura veículos, móveis e imóveis no mesmo template.
        # Usar `body_text` global pra is_imovel é arriscado: carrosséis
        # laterais ("Outros imóveis") contaminam lotes de Semirreboque.
        # Estratégia: combina sinais do título com a presença do bloco
        # "IMÓVEL:" no edital. Edital de imóvel SEMPRE prefixa com
        # `<strong>IMÓVEL:</strong>`; edital de veículo usa outros termos
        # (ex.: "Semirreboque", "Veículo"). Fallback: títulos abreviados
        # ("AP.", "APTO.", "AP-CAMPO-GRANDE", etc.) que casam imovel via
        # url_slug.
        m_slug = re.search(r"[?&]imovel=([^&]+)", response.url)
        url_slug = unquote(m_slug.group(1)) if m_slug else ""
        title_signal = (title or "") + " " + url_slug.replace("-", " ").replace(".", " ")
        # body_text é largo; busca diretamente o anchor "IMÓVEL:" do edital
        has_imovel_anchor = bool(
            re.search(r"IM[ÓO]VEL\s*:", body_text, re.I)
            or "IM&Oacute;VEL" in response.text
        )
        # Title-based check (`is_imovel`) cobre títulos óbvios
        # ("IMÓVEL EM ANGRA", "TERRENO NA FREGUESIA"). Para títulos
        # ambíguos ("SALA NO EDIF.", "AP-CAMPO-GRANDE"), exige anchor.
        title_says_imovel = _detail_is_imovel(title_signal, "")
        title_says_vehicle = bool(re.search(
            r"\b(?:Semirreboque|Reboque|Ve[íi]culo|Caminh[ãa]o|Trator|"
            r"Motocicleta|Carreta|Camionete|Camioneta|[ÔO]nibus)\b",
            title_signal, re.I,
        ))
        # Vehicle title é veto absoluto
        if title_says_vehicle:
            self.log_event(
                "ph_lote_dropped_non_imovel",
                url=response.url,
                title=(og_title or title)[:80],
                reason="vehicle_title",
            )
            return
        # Aceita se (a) título obviamente imóvel OU (b) tem anchor IMÓVEL:
        if not (title_says_imovel or has_imovel_anchor):
            self.log_event(
                "ph_lote_dropped_non_imovel",
                url=response.url,
                title=(og_title or title)[:80],
            )
            return

        loader = self.new_loader(response)
        auctioneer = _extract_auctioneer(response)
        if auctioneer and auctioneer.get("full_name"):
            loader.replace_value("auctioneer", auctioneer["full_name"])
            loader.add_value("auctioneer_data", auctioneer)
        else:
            loader.replace_value("auctioneer", self.auctioneer_slug)

        # source_lot_code — extrai N do path
        m_id = re.search(r"[?&]id=(\d+)", response.url)
        if m_id:
            loader.add_value("source_lot_code", m_id.group(1))

        # Título: usa o h1#featured-heading
        if title:
            # Limpa sufixo " - Eletrônico - Judicial" repetitivo
            cleaned = re.sub(
                r"\s*-\s*Eletr[ôo]nico\s*-?\s*Judicial\s*$", "", title, flags=re.I
            )
            loader.add_value("title", cleaned or title)

        # description — pega o primeiro parágrafo grande que contém "IMÓVEL"
        m_desc = re.search(
            r"IM[ÓO]VEL[:\s]+(.{50,4000}?)(?=\s+(?:Os\s+leil[ãa]es|Condi[çc][õo]es|\Z))",
            body_text, re.I | re.S,
        )
        if m_desc:
            loader.add_value("description", m_desc.group(1).strip()[:5000])

        # status
        loader.add_value("status", "aberto")

        # Preços — "A partir de R$ X" é o lance mínimo (1ª data tipicamente)
        m_apartir = re.search(
            r"A\s+partir\s+de[:\s]*R\$\s*([\d.,]+)", body_text, re.I,
        )
        if m_apartir:
            try:
                v = _brl_to_decimal(m_apartir.group(1))
                if v and v > 0:
                    loader.add_value("minimum_bid", str(v))
            except Exception:
                pass

        # Avaliação Total: "Avaliação Total ... R$ X"
        m_av = re.search(
            r"Avalia[çc][ãa]o\s+Total[^R]{0,80}R\$\s*([\d.,]+)",
            body_text, re.I,
        )
        if not m_av:
            m_av = _PRICE_AVALIACAO.search(body_text)
        if m_av:
            try:
                v = _brl_to_decimal(m_av.group(1))
                if v and v > 0:
                    loader.add_value("market_value", str(v))
            except Exception:
                pass

        # Fallback minimum_bid
        if not loader.get_output_value("minimum_bid"):
            m_min = (_PRICE_PRACA_2.search(body_text)
                     or _PRICE_PRACA_1.search(body_text)
                     or _PRICE_LANCE_MIN.search(body_text))
            if m_min:
                try:
                    v = _brl_to_decimal(m_min.group(1))
                    if v and v > 0:
                        loader.add_value("minimum_bid", str(v))
                except Exception:
                    pass

        # Datas — "1ª hasta: DD/MM/YYYY"
        m_dt = re.search(
            r"1[ºoº°ªa]?\s*hasta[:\s]+(\d{2}/\d{2}/\d{4})",
            body_text, re.I,
        )
        if m_dt:
            loader.add_value("first_auction_date", m_dt.group(1))
        m_dt2 = re.search(
            r"2[ºoº°ªa]?\s*hasta[:\s]+(\d{2}/\d{2}/\d{4})",
            body_text, re.I,
        )
        if m_dt2:
            loader.add_value("second_auction_date", m_dt2.group(1))
            loader.add_value("auction_phase", "2a_praca")

        # Endereço — extrai CIDADE/UF
        addr: dict[str, Any] = {"raw_text": title[:300] if title else ""}
        m_cuf = re.search(
            r"\b([A-ZÀ-Ú][A-Za-zÀ-ú\s.'-]{2,40}?)\s*[/-]\s*([A-Z]{2})\b",
            (title or "") + " " + body_text[:500],
        )
        if m_cuf:
            cidade = m_cuf.group(1).strip().rstrip(",.").strip()
            if 3 <= len(cidade) <= 50:
                addr["municipality_name"] = cidade
                addr["uf"] = m_cuf.group(2)
        # Schulmann é RJ — fallback default
        if not addr.get("uf"):
            addr["uf"] = "RJ"
        if addr.get("municipality_name") or addr.get("raw_text"):
            loader.add_value("address", addr)

        # Imagens
        img_urls = response.css(
            "img::attr(src), img::attr(data-src)"
        ).getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
        for u in img_urls:
            if not u or "data:image" in u:
                continue
            absolute = response.urljoin(u)
            low = absolute.lower()
            if any(skip in low for skip in (
                "logo", "favicon", "icon", "bandeira", "payment",
                "facebook", "instagram", "whatsapp", "twitter", "linkedin",
                "placeholder", "escudo",
            )):
                continue
            if absolute in seen_imgs:
                continue
            seen_imgs.add(absolute)
            unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs[:20])

        # Documents
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

        payment_options, encumbrances = _parse_auction_clauses(body_text)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())

        item = loader.load_item()
        self._fixup_item(item, response, body_text=body_text, host=host)

        self.log_event(
            "ph_lote_extracted", url=response.url, host=host,
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            mkt=item.get("market_value"),
        )
        yield item

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
                    "playwright": False,
                    "download_timeout": 15,
                },
            )
