"""Spider para `mullerleiloes.com.br` — Müller Leilões (RS).

Cobre dois leiloeiros do INNLEI declarados no mesmo site (Darci Muller +
Daniel Costa Müller), atribuídos com `auctioneer_slug=mullerleiloes` (slug
da firma).

Plataforma "bidder/lance" — toda a parse logic vive em
`_bidder_lance_platform.BidderLancePlatformSpider`. Documentação detalhada
da topologia e seletores está lá.
"""

from ._bidder_lance_platform import BidderLancePlatformSpider


class MullerSpider(BidderLancePlatformSpider):
    name = "muller"
    auctioneer_slug = "mullerleiloes"
    allowed_domains = ["mullerleiloes.com.br"]
    start_urls = ["https://www.mullerleiloes.com.br/lotes/imovel"]
