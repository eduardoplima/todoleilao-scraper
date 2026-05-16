"""Araújo Leilões (araujoleiloes.com.br) — top produtivo (78 lotes na
baseline do genérico).

Gaps no genérico para este template:
  - **Título** vive em `<h2>` (não `<h1>`).
  - **Preços** estão em `<p>Lance 1º Leilão <b>R$ X</b></p>` — a regex
    `1ª Praça`/`2ª Praça` do genérico não casa "Lance 1º Leilão".
  - **Imagens** estão em `<div class="why-choose-us-image"
    style="background:url(...)">` (CSS shorthand, sem `background-image:`).
  - **Endereço** vem na descrição como `... cidade de Santo Antônio do
    Leverger (MT)` — parênteses em vez de slash.
  - **Descrição** está em bloco `<div>` após `LOCALIZAÇÃO DOS IMOVEIS:`.
"""
from __future__ import annotations

import re

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider
from leilao_scraper.spiders.proprio_html_specific._common import (
    _RE_LANCE_PRACA_1,
    _uf_from_url_slug,
    collect_bg_images_shorthand,
    extract_cidade_uf,
    extract_lance_min_with_dash,
)
from leilao_scraper.spiders.soleon import _brl_to_decimal


class AraujoLeiloesSpider(ProprioHtmlSpider):
    name = "araujo_leiloes"
    provider_slug = "araujo_leiloes"
    auctioneer_slug = "araujo_leiloes"

    def _fixup_item(self, item, response, *, body_text: str, host: str) -> None:
        # título via <h2> — sempre prefere o segundo h2 (o primeiro
        # é "Informação adicional" no template do Araujo)
        h2_list = [h.strip() for h in response.css("h2::text").getall() if h.strip()]
        # Drop placeholders genéricos
        h2_real = [h for h in h2_list if h.lower() not in (
            "informação adicional", "informacao adicional", "documentos",
            "descrição", "descricao", "produto"
        )]
        if h2_real:
            item["title"] = h2_real[0]
        elif h2_list and not item.get("title"):
            item["title"] = h2_list[0]

        # lance mínimo via "Lance 2º Leilão" (preferred over "Lance 1º")
        if not item.get("minimum_bid"):
            v = extract_lance_min_with_dash(body_text)
            if v:
                item["minimum_bid"] = str(v)

        # market_value via "Lance 1º Leilão" (avaliação efetiva)
        if not item.get("market_value"):
            m = _RE_LANCE_PRACA_1.search(body_text)
            if m:
                try:
                    v = _brl_to_decimal(m.group(1))
                    if v and v > 0:
                        item["market_value"] = str(v)
                except Exception:
                    pass

        # endereço via "Cidade (UF)"
        addr = dict(item.get("address") or {})
        if not addr.get("municipality_name"):
            title = item.get("title") or ""
            cuf = extract_cidade_uf(title + " " + body_text[:1500])
            if cuf:
                addr["municipality_name"] = cuf[0]
                addr["uf"] = cuf[1]
                item["address"] = addr

        # Fallback: extrai UF do slug da URL quando o texto não contém Cidade/UF
        if not addr.get("uf"):
            uf = _uf_from_url_slug(response.url)
            if uf:
                addr["uf"] = uf
                item["address"] = addr

        # imagens via background:url() shorthand
        if not item.get("images"):
            imgs = collect_bg_images_shorthand(response.text)
            if imgs:
                item["images"] = imgs[:20]

        # descrição via "LOCALIZAÇÃO DOS IMOVEIS:"
        if not item.get("description"):
            m_desc = re.search(
                r"LOCALIZA[ÇC][ÃA]O\s+DOS?\s+IM[OÓ]VEIS[:\s]+(.{50,1500}?)(?=\s+(?:Documentos|Edital|R\$))",
                body_text, re.I,
            )
            if m_desc:
                item["description"] = m_desc.group(1).strip()[:5000]
