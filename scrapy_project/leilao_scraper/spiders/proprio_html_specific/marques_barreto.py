"""Marques Barreto Leilões (www.marquesbarretoleiloes.com.br) — 1 lote
na baseline. Mesma plataforma CakePHP do Casa Do Leilão, mas com
markup de preço usando `Avaliação: R$ A` / `Lance Mínimo: R$ B`
(em vez de Primeiro/Segundo Leilão).

A regex universal já cobre `Avaliação` e `Lance Mínimo`, mas o
genérico mesmo assim falhou em 0/1 → 1/1 com sucesso. O baseline já é
ótimo, então este spider é "noop com nome próprio" – preserva o slug
para classificação/relatórios e mantém porta aberta para overrides
futuros.
"""
from __future__ import annotations

from leilao_scraper.spiders.proprio_html import ProprioHtmlSpider
from leilao_scraper.spiders.proprio_html_specific._common import (
    extract_casa_platform_prices,
)


class MarquesBarretoSpider(ProprioHtmlSpider):
    name = "marques_barreto"
    provider_slug = "marques_barreto"
    auctioneer_slug = "marques_barreto"

    def _fixup_item(self, item, response, *, body_text: str, host: str) -> None:
        # Garante que se a plataforma decidir mudar para "Primeiro/Segundo
        # Leilão" no futuro, a extração não quebre.
        market, minimum = extract_casa_platform_prices(body_text)
        if minimum is not None and not item.get("minimum_bid"):
            item["minimum_bid"] = str(minimum)
        if market is not None and not item.get("market_value"):
            item["market_value"] = str(market)
