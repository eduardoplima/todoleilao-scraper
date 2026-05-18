"""Settings de scrapy-playwright opt-in por spider.

Antes (até 2026-05-18) `DOWNLOAD_HANDLERS` era global em `settings.py`,
o que fazia o handler do scrapy-playwright iniciar para TODOS os spiders
— mesmo aqueles que só usam httpx puro (banks, soleon, leilao_pro, etc).
Em produção (Fly machine) a inicialização em thread separada do
scrapy-playwright 0.0.46 + Playwright 1.58 / Python 3.12+ levanta
`Exception: Connection closed while reading from the driver`, matando
o spider antes mesmo da primeira request.

Solução: spiders que de fato precisam JS dynamico mergeam estas chaves
no seu `custom_settings`. Spiders que não precisam ficam imunes.
"""
from __future__ import annotations


PLAYWRIGHT_DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}


PLAYWRIGHT_CUSTOM_SETTINGS = {
    "DOWNLOAD_HANDLERS": PLAYWRIGHT_DOWNLOAD_HANDLERS,
    "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
}
