"""Base para todos os spiders de leiloeiros.

Centraliza:
  - flag `requires_playwright` (default False) consumida pelos middlewares
    para decidir se a request precisa de `meta={"playwright": True}`.
  - atributo `auctioneer` que cada subclass deve sobrescrever — usado pelo
    `ValidationPipeline` e como chave para attribuir os itens.
  - helpers de extração comuns (preço, data, URL absoluta).

Cada subclass implementa `parse()`/`parse_*()` específicas do site, mas
deve manter o contrato: yield `PropertyItem` ou `scrapy.Request`.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import scrapy


class BaseAuctionSpider(scrapy.Spider):
    """Classe base para os spiders de leilão.

    Subclasses obrigatórias:
      - `name`           : slug único Scrapy
      - `auctioneer`     : slug canônico do leiloeiro (vai para o item)
      - `allowed_domains`: domínios permitidos
      - `start_urls`     : URLs iniciais
      - `parse(response)`: ponto de entrada
    """

    auctioneer: str = ""
    requires_playwright: bool = False

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def absolute(response: scrapy.http.Response, href: str) -> str:
        return urljoin(response.url, href)

    @staticmethod
    def first_match(pattern: str, text: str, group: int = 1, flags: int = re.IGNORECASE) -> str:
        """Retorna o primeiro grupo capturado pelo regex, ou string vazia."""
        if not text:
            return ""
        m = re.search(pattern, text, flags)
        return m.group(group).strip() if m else ""
