"""Spider para `cassianoleiloes.com.br` — Cassiano Leilões (PI, Cassiano Ricardo Dall Ago e Silva).

Mesma plataforma "bidder/lance" do Müller/Rech — toda parse logic em
`_bidder_lance_platform.BidderLancePlatformSpider`.
"""
from ._bidder_lance_platform import BidderLancePlatformSpider


class CassianoSpider(BidderLancePlatformSpider):
    name = "cassiano"
    auctioneer_slug = "cassianoleiloes"
    allowed_domains = ["cassianoleiloes.com.br"]
    start_urls = ["https://www.cassianoleiloes.com.br/lotes/imovel"]
