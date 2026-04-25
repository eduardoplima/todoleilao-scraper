"""Base para todos os spiders de leilão.

Centraliza o que é repetido em todo spider concreto:

  - identidade do leiloeiro (`auctioneer_slug`) propagada para os itens;
  - injeção automática de `meta={"playwright": True}` quando o spider declara
    `requires_playwright = True`, via `make_request`;
  - construção de `PropertyLoader` já com `url`, `auctioneer` e
    `source_listing_url` pré-preenchidos, via `new_loader`;
  - hook `parse_property(response)` que subclasses obrigatoriamente
    implementam para emitir o `PropertyItem` final;
  - logging estruturado simples (`log_event(event, **fields)`);
  - helpers de Playwright em `make_request`: `wait_for_selector`,
    `scroll_to_bottom`, `load_more_selector` — encadeados como
    `playwright_page_methods` antes da response ser entregue ao callback.

Subclasse mínima:

```python
class FrazaoSpider(BaseAuctionSpider):
    name = "frazao"
    auctioneer_slug = "frazao_leiloes"
    start_urls = ["https://www.frazaoleiloes.com.br/imoveis"]
    requires_playwright = False

    def parse(self, response):
        for href in response.css("a.lote::attr(href)").getall():
            yield self.make_request(
                response.urljoin(href), callback=self.parse_property,
                meta={"source_listing_url": response.url},
            )

    def parse_property(self, response):
        loader = self.new_loader(response)
        loader.add_value("title", response.css("h1::text").get())
        ...
        yield loader.load_item()
```
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import scrapy
from scrapy_playwright.page import PageMethod

from leilao_scraper.items import PropertyItem
from leilao_scraper.loaders import PropertyLoader


# JS de scroll progressivo: rola até o final, espera 800ms, checa se cresceu;
# quando estabiliza, sai. Cobre lazy-load por intersection observer e por
# fetch-on-near-bottom (padrões mais comuns).
_SCROLL_BOTTOM_JS = """
async () => {
    let prev = -1;
    let stable = 0;
    while (stable < 2) {
        const h = document.body.scrollHeight;
        if (h === prev) {
            stable += 1;
        } else {
            stable = 0;
            prev = h;
            window.scrollTo(0, h);
        }
        await new Promise(r => setTimeout(r, 800));
    }
}
"""

# Loop de "carregar mais": clica no seletor até N vezes ou até o botão sumir
# /ficar disabled. O wait_for_timeout dá tempo do servidor responder.
_LOAD_MORE_LOOP_JS = """
async ({sel, maxClicks}) => {
    for (let i = 0; i < maxClicks; i++) {
        const btn = document.querySelector(sel);
        if (!btn || btn.disabled || btn.offsetParent === null) break;
        btn.click();
        await new Promise(r => setTimeout(r, 1500));
    }
}
"""

DEFAULT_WAIT_TIMEOUT_MS = 15_000


class BaseAuctionSpider(scrapy.Spider):
    """Superclasse para spiders de leiloeiros.

    Atributos obrigatórios em subclasses:
      - `name`             — slug Scrapy (`scrapy crawl <name>`)
      - `auctioneer_slug`  — slug canônico que vai para o item
      - `start_urls`       — lista de URLs iniciais

    Opcional:
      - `requires_playwright` — quando `True`, todas as requests criadas via
        `make_request` recebem `meta["playwright"] = True`.
    """

    auctioneer_slug: str = ""
    requires_playwright: bool = False

    # ---------- factory de Request ----------------------------------------

    def make_request(
        self,
        url: str,
        callback: Any | None = None,
        *,
        meta: dict[str, Any] | None = None,
        wait_for_selector: str | None = None,
        wait_timeout_ms: int = DEFAULT_WAIT_TIMEOUT_MS,
        scroll_to_bottom: bool = False,
        load_more_selector: str | None = None,
        load_more_max_clicks: int = 10,
        page_methods: list[PageMethod] | None = None,
        **kwargs: Any,
    ) -> scrapy.Request:
        """Cria um `scrapy.Request` injetando `playwright=True` e, quando aplicável,
        a sequência de `playwright_page_methods` para esperar/rolar/clicar.

        Preserva qualquer `meta` que o chamador passou e só adiciona a chave
        `playwright` quando ainda não está presente — permite ao spider opt-out
        explicitamente para uma URL específica em um spider Playwright (raro,
        mas útil para CDNs/sitemaps que não precisam de JS).

        Helpers Playwright (ignorados quando a request não vai pro Chromium):

        - `wait_for_selector`: espera por um CSS selector (até `wait_timeout_ms`)
          antes de considerar a página pronta. Use quando o conteúdo de
          interesse aparece após XHR.
        - `scroll_to_bottom`: scroll progressivo até o `scrollHeight` estabilizar.
          Cobre lazy-load por `IntersectionObserver` ou `fetch-on-near-bottom`.
        - `load_more_selector` + `load_more_max_clicks`: clica repetidamente
          no botão "carregar mais" até ele sumir/desabilitar ou bater o cap.
        - `page_methods`: lista raw para casos avançados (anexada antes dos
          helpers acima).

        Estes ENCADEAM na ordem: page_methods extras → wait_for_selector →
        scroll_to_bottom → load_more_selector. Se você precisa de outra
        ordem, passe tudo via `page_methods=[...]`.
        """
        merged_meta = dict(meta or {})
        if self.requires_playwright:
            merged_meta.setdefault("playwright", True)

        if merged_meta.get("playwright"):
            methods: list[PageMethod] = list(merged_meta.get("playwright_page_methods", []))
            if page_methods:
                methods.extend(page_methods)
            if wait_for_selector:
                methods.append(
                    PageMethod("wait_for_selector", wait_for_selector, timeout=wait_timeout_ms)
                )
            if scroll_to_bottom:
                methods.append(PageMethod("evaluate", _SCROLL_BOTTOM_JS))
                methods.append(PageMethod("wait_for_load_state", "networkidle"))
            if load_more_selector:
                methods.append(
                    PageMethod(
                        "evaluate",
                        _LOAD_MORE_LOOP_JS,
                        {"sel": load_more_selector, "maxClicks": load_more_max_clicks},
                    )
                )
            if methods:
                merged_meta["playwright_page_methods"] = methods

        return scrapy.Request(url, callback=callback, meta=merged_meta, **kwargs)

    # ---------- factory de PropertyLoader ---------------------------------

    def new_loader(
        self,
        response: scrapy.http.Response,
        *,
        source_listing_url: str | None = None,
    ) -> PropertyLoader:
        """Devolve um `PropertyLoader` ligado a `response` com identidade pré-preenchida.

        Ordem de resolução de `source_listing_url`:

        1. argumento explícito `source_listing_url=...`
        2. `response.meta["source_listing_url"]` (set pelo `make_request` anterior)
        3. fallback: a própria `response.url` (caso o item viva na home/listagem)
        """
        loader = PropertyLoader(item=PropertyItem(), selector=response)
        loader.add_value("url", response.url)
        loader.add_value("auctioneer", self.auctioneer_slug)
        src = (
            source_listing_url
            or response.meta.get("source_listing_url")
            or response.url
        )
        loader.add_value("source_listing_url", src)
        return loader

    # ---------- hook obrigatório ------------------------------------------

    def parse_property(self, response: scrapy.http.Response):
        """Hook que cada subclass implementa para extrair UM `PropertyItem`.

        Não é abstrato por convenção (Scrapy spiders são instanciados via
        `from_crawler` e abstract methods atrapalham), mas levanta
        `NotImplementedError` quando chamado sem override.
        """
        raise NotImplementedError(
            f"{type(self).__name__}.parse_property(response) must be overridden"
        )

    # ---------- logging estruturado ---------------------------------------

    def log_event(self, event: str, /, **fields: Any) -> None:
        """Emite um log INFO no formato `event=NAME k=v k=v ...`.

        Útil para grep/jq nos logs de produção:
          `2026-04-25 14:30:00 [oaleiloes] INFO: event=lote_skipped reason=non_property url=...`
        """
        parts = [f"event={event}"]
        for key, value in fields.items():
            if isinstance(value, str):
                if " " in value or "=" in value:
                    parts.append(f"{key}={value!r}")
                else:
                    parts.append(f"{key}={value}")
            else:
                parts.append(f"{key}={value}")
        self.logger.info(" ".join(parts))

    # ---------- helpers utilitários ---------------------------------------

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def absolute(response: scrapy.http.Response, href: str) -> str:
        return urljoin(response.url, href)

    @staticmethod
    def first_match(
        pattern: str, text: str, group: int = 1, flags: int = re.IGNORECASE
    ) -> str:
        if not text:
            return ""
        m = re.search(pattern, text, flags)
        return m.group(group).strip() if m else ""
