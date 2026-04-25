"""Configuração do projeto Scrapy `leilao_scraper`.

Resolução de paths: este arquivo vive em
`<repo>/scrapy_project/leilao_scraper/settings.py`. `PROJECT_ROOT` sobe três
níveis para apontar para a raiz do repo, garantindo que `data/raw/...` aponte
ao mesmo lugar mesmo quando o `scrapy crawl` é invocado de outro cwd.

scrapy-playwright: o `DOWNLOAD_HANDLERS` é registrado para http/https, mas
requisições só passam pelo Chromium quando o spider opta com
`meta={"playwright": True}`. Sem esse flag o handler delega para o handler
HTTP padrão do Scrapy — o overhead da troca é desprezível.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
HTTPCACHE_PATH = DATA_DIR / "intermediate" / "cache" / "scrapy_httpcache"

BOT_NAME = "leilao_scraper"

SPIDER_MODULES = ["leilao_scraper.spiders"]
NEWSPIDER_MODULE = "leilao_scraper.spiders"

# ---------------------------------------------------------------------------
# Politeness
# ---------------------------------------------------------------------------

ROBOTSTXT_OBEY = True

USER_AGENT = "TodoLeilaoBot/1.0 (+contato@exemplo.com)"

DOWNLOAD_DELAY = 1.5
CONCURRENT_REQUESTS_PER_DOMAIN = 2
CONCURRENT_REQUESTS = 16

# AutoThrottle ajusta o delay com base na latência observada — começa
# conservador e cresce só quando o servidor responde rápido.
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.5
AUTOTHROTTLE_MAX_DELAY = 30
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.5
AUTOTHROTTLE_DEBUG = False

# ---------------------------------------------------------------------------
# HTTP cache (desenvolvimento)
# ---------------------------------------------------------------------------

HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 0  # 0 = nunca expira automaticamente
HTTPCACHE_DIR = str(HTTPCACHE_PATH)
HTTPCACHE_IGNORE_HTTP_CODES = [500, 502, 503, 504, 408, 429]
HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

# ---------------------------------------------------------------------------
# Feeds — um JSONL por spider, com timestamp no nome
# Resolvido via PROJECT_ROOT acima (cross-cwd safe).
# ---------------------------------------------------------------------------

FEEDS = {
    str(DATA_DIR / "raw" / "%(name)s" / "%(time)s.jsonl"): {
        "format": "jsonlines",
        "encoding": "utf-8",
        "store_empty": False,
        "overwrite": False,
        "indent": None,
    },
}

# ---------------------------------------------------------------------------
# scrapy-playwright — registrado, mas opt-in por spider/request
# ---------------------------------------------------------------------------

DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}

# scrapy-playwright requer o reactor asyncio.
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

PLAYWRIGHT_BROWSER_TYPE = "chromium"

# Launch options aplicadas a `chromium.launch(...)`.
#   `headless=True`        — headless em produção (já é o default da lib).
#   `timeout=30_000`       — timeout do próprio launch (browser stuck na boot).
#   `args` enxutos         — desabilita features que comem RAM/inflate flakiness
#                             em ambiente CI/Docker. Em dev local não faz mal.
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": True,
    "timeout": 30_000,
    "args": [
        "--disable-dev-shm-usage",     # Linux/Docker: usa /tmp em vez de /dev/shm
        "--disable-blink-features=AutomationControlled",
    ],
}

# Timeout default de `page.goto(...)` quando o spider não passa um valor próprio.
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30_000  # ms

# Quantas páginas mantemos abertas por contexto antes de reciclar (controla
# vazamento de memória do Chromium em runs longos).
PLAYWRIGHT_MAX_PAGES_PER_CONTEXT = 4

# Hook para abortar requests do Playwright (assets desnecessários).
# spiders podem sobrescrever para bloquear imagens/css/etc.; default = nada.
PLAYWRIGHT_ABORT_REQUEST = None

# Concorrência efetiva de pages dentro do navegador headless.
PLAYWRIGHT_CDP_KWARGS = {}

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
FEED_EXPORT_ENCODING = "utf-8"

# Pipelines: ordem por prioridade (menor primeiro).
ITEM_PIPELINES: dict[str, int] = {
    "leilao_scraper.pipelines.ValidationPipeline": 100,
    "leilao_scraper.pipelines.DeduplicationPipeline": 200,
    "leilao_scraper.pipelines.EnrichmentPipeline": 300,
    "leilao_scraper.pipelines.JsonLinesExportPipeline": 900,
}
SPIDER_MIDDLEWARES: dict[str, int] = {}
DOWNLOADER_MIDDLEWARES: dict[str, int] = {}
