"""Spider para os tenants "dg" (Degrau Publicidade) que não estão no
provider CSV ou estão mislabeled.

Contexto
========
ISSUES_TODO.md § "Plataformas dg e Next/React" lista 9 leiloeiros com
template idêntico (`<div class="dg-lote-titulo">`, `<span class=
"ValorMinimoLancePrimeiraPraca">`, footer "Sua Plataforma de Leilão |
Degrau Publicidade e Internet"). Quando a página é carregada via
browser, jQuery templates renderizam os preços a partir de
`/ApiEngine/GetBusca` + SignalR. HTML estático tem só o título.

Recon de 2026-05-15 (esta sessão): TODOS os 9 sites publicam um
`/sitemap.xml` no formato Facebook-listings com `<price>`, `<rate>`,
`<available_dates_price_config>` (start/end por praça), URL canônica
do lote e endereço. **Não precisa de Playwright nem de chamar a API
JSON** — o sitemap é exportado pelo próprio framework Degrau com tudo
que precisamos.

Por que um spider separado?
- O spider `degrau_publicidade` já cobre 26 tenants do CSV de providers
  via `_provider_base.ProviderSpider`. Mas dos 9 sites do escopo
  "plataforma dg" do ISSUES_TODO, 4 estão **fora** do CSV
  (`destakleiloes`, `vivaleiloes`, `multipliqueleiloes`, `upleilao`)
  e 1 está como `proprio_html` (`inovaleilao`). Tentar adicioná-los
  ao CSV exigiria mexer no `recon-provider` (fora do escopo).
- `dg_platform` é o spider público para crawlear esses 9 hosts por
  URL explícita (`-a urls=...` ou padrão = todos os 9).

Comportamento: idêntico ao `degrau_publicidade` — herda parse_sitemap
e parse_property, só sobrescreve a fonte de start_urls.

Uso:
    scrapy crawl dg_platform                                # todos os 9
    scrapy crawl dg_platform -a urls=https://www.destakleiloes.com.br/
    scrapy crawl dg_platform -a sites=3                     # primeiros 3
"""
from __future__ import annotations

from typing import Any, Iterable

import scrapy

from leilao_scraper.spiders.degrau_publicidade import DegrauPublicidadeSpider


# Hosts canônicos derivados de ISSUES_TODO.md (todos confirmados em
# 2026-05-15 servindo sitemap Facebook-listings com price/rate/datas).
# A ordem reflete o "high count" de leiloeiros high-confidence cobertos
# (gfleiloes lidera com 8; depois destak, teza, silva, etc.).
DG_DEFAULT_HOSTS: list[str] = [
    "https://www.gfleiloes.com.br/",          # 8 high
    "https://www.destakleiloes.com.br/",      # 4 high
    "https://www.teza.com.br/",               # 4 high
    "https://www.silvaleiloes.com.br/",       # 3 high
    "https://www.vivaleiloes.com.br/",        # 2 high
    "https://www.multipliqueleiloes.com.br/", # 2 high
    "https://www.upleilao.com.br/",           # 2 high
    "https://www.casareisleiloes.com.br/",    # 2 high
    "https://www.inovaleilao.com.br/",        # 2 high
    # Adicionados 2026-05-15 (agentC): mais 4 tenants dg identificados
    # via batch-recon de footer/meta — todos servem sitemap Facebook-
    # listings idêntico. Sitemaps de erika+nacional retornam 0 listings
    # ativos hoje, mas o template é o mesmo — spider extrai 0 items
    # idempotentemente, sem regressão.
    "https://grupoarremateleiloes.com.br/",   # 1 high (Fernando Cabeças)
    "https://leiloeiraerikamaciel.com.br/",   # 1 high (Erika Maciel)
    "https://leilaooficialonline.com.br/",    # 1 high (Clecio Oliveira)
    "https://nacionalleiloes.com.br/",        # 1 high (Maritza Grande)
    # Batch 2 (agentC, mesmo dia): outros 5 tenants dg em hosts long-tail.
    # sitemap.xml retorna 6/3/103/49/24 listings respectivamente.
    "https://ktzleiloes.com.br/",             # 1 high (Vivian Katzenelson)
    "https://brancalliao.com.br/",            # 1 high (Nilton Brancalliao)
    "https://sublimeleiloes.com.br/",         # 1 high (Lidianicy Xavier) — 103 listings!
    "https://arremaxleiloes.com.br/",         # 1 high (João Simão) — 49 listings
    "https://pecinileiloes.com.br/",          # 1 high (Angela Pecini) — 24 listings
    "https://camargoleiloes.com.br/",         # 1 high (Camargo) — 24 listings
]


class DgPlatformSpider(DegrauPublicidadeSpider):
    """Subclass de DegrauPublicidadeSpider com start_urls fixos nos 9
    tenants da família "dg" listados em ISSUES_TODO.md.

    Toda lógica de fetch/parse é herdada — sitemap.xml + detail HTML.
    """

    name = "dg_platform"
    # Mantém provider_slug='degrau_publicidade' para reaproveitar o
    # selectors.yaml + auctioneer_slug do parent (host-discriminated).
    provider_slug = "degrau_publicidade"
    auctioneer_slug = "degrau_publicidade"
    requires_playwright = False

    # Override do __init__ pra ignorar o requisito do provider CSV:
    # site_providers.csv não cobre todos os 9 hosts (destak/viva/multi/up
    # estão ausentes; inova está como `proprio_html`). Usamos DG_DEFAULT_HOSTS
    # como fonte de verdade.
    def __init__(
        self,
        sites: str = "all",
        urls: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        # Não chama super().__init__ do ProviderSpider porque ele exigiria
        # CSV resolve; chama o BaseAuctionSpider.__init__ direto via grandparent.
        scrapy.Spider.__init__(self, *args, **kwargs)

        # IncrementalCrawlMixin.__init__ não é chamado pelo Spider.__init__
        # acima (bypass do MRO normal). Inicializa manualmente o estado do mixin.
        from leilao_scraper.spiders._provider_base import IncrementalCrawlMixin
        IncrementalCrawlMixin.__init__(self, *args, **kwargs)

        # Carrega selectors.yaml do provider degrau (não usamos no parser,
        # mas mantém compatibilidade com helpers do ProviderSpider).
        from leilao_scraper.spiders._provider_base import ProviderSpider
        self.selectors = ProviderSpider._load_selectors(self.provider_slug)

        if urls:
            self.start_urls = [u.strip() for u in urls.split(",") if u.strip()]
        else:
            if sites.lower() == "all":
                self.start_urls = list(DG_DEFAULT_HOSTS)
            else:
                try:
                    limit = max(1, int(sites))
                except ValueError:
                    limit = len(DG_DEFAULT_HOSTS)
                self.start_urls = DG_DEFAULT_HOSTS[:limit]

        # Estado consumido por degrau_publicidade (e indiretamente
        # pelo merge edital): inicializa o dict-cache aqui pra evitar
        # AttributeError caso parent não passe pela __init__ do super.
        self._host_seen: dict = {}

        self.logger.info(
            "DgPlatformSpider: start_urls=%d hosts=%s",
            len(self.start_urls),
            [u.split("//", 1)[-1].split("/", 1)[0] for u in self.start_urls[:9]],
        )

    def start_requests(self) -> Iterable[Any]:
        self._open_incremental_db()
        for url in self.start_urls:
            yield self.make_request(url, callback=self.parse)

    def closed(self, reason: str) -> None:
        self.close_incremental_db()
