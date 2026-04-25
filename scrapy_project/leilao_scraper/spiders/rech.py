"""Spider para `rechleiloes.com.br` — Rech Leilões (RS, Alexandre Rech).

Mesma plataforma "bidder/lance" do Müller — toda parse logic em
`_bidder_lance_platform.BidderLancePlatformSpider`.
"""
from ._bidder_lance_platform import BidderLancePlatformSpider


class RechSpider(BidderLancePlatformSpider):
    name = "rech"
    auctioneer_slug = "rechleiloes"
    allowed_domains = ["rechleiloes.com.br"]
    start_urls = ["https://www.rechleiloes.com.br/lotes/imovel"]
