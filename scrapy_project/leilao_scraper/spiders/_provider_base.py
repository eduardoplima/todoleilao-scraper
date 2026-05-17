"""Base abstrata para spiders provider-driven.

Lê `specs/_providers/<provider>/selectors.yaml` (escrito por
arch-recon-pilot) e expõe `self.selectors` para o subclass usar nos
parsers. Itera sobre os sites do provider em
`data/intermediate/site_providers.csv` filtrando por `provider_slug`.

Decisão de escopo: v1 não consegue gerar um spider 100% genérico a
partir do YAML — providers variam o número de níveis de listagem
(2 níveis: listing→detail; 3 níveis: home→leilao_lotes→detail) e o
modo de extração de bids (HTML table vs JSON inline vs XHR). O subclass
ainda escreve os parsers, mas reusa selectors do YAML como fonte de
verdade declarativa.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import yaml

from leilao_scraper.spiders.base import BaseAuctionSpider

REPO_ROOT = Path(__file__).resolve().parents[3]
PROVIDERS_DIR = REPO_ROOT / "specs" / "_providers"
SITE_PROVIDERS_CSV = REPO_ROOT / "data" / "intermediate" / "site_providers.csv"


# ---------------------------------------------------------------------------
# IncrementalCrawlMixin — opt-in via `-a incremental_only=true`
# ---------------------------------------------------------------------------


class IncrementalCrawlMixin:
    """Pula detail fetch pra lots já no DB; mantém listing pra status update.

    Uso em qualquer spider:
        scrapy crawl <name> -a incremental_only=true

    Cliente do mixin DEVE:
    1. Herdar de IncrementalCrawlMixin (multiple inheritance OK com
       ProviderSpider/scrapy.Spider).
    2. Chamar `self._open_incremental_db()` em `start_requests` ou via
       signal `spider_opened`.
    3. Antes de yield request de detail (parse_property), checar
       `self.lot_exists(host, source_lot_code)`:
         - False → request normal (lot novo)
         - True  → emit item parcial com `listing_only_status_update=True`
           e seguir pro próximo card.
    4. Chamar `self.close_incremental_db()` em signal `closed`.

    Comportamento default (incremental_only=false): mixin é no-op,
    `lot_exists` sempre retorna False — caminho legacy preservado.

    Cache em memória: 1 query SELECT por host no start; tuple set de
    ~3MB pra 30k entries (Caixa).
    """

    def __init__(
        self,
        *args: Any,
        incremental_only: str = "false",
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        flag = (incremental_only or "").strip().lower()
        self._incremental_only: bool = flag in {"1", "true", "yes", "y"}
        self._known_lots: set[tuple[str, str]] = set()
        self._db_conn = None  # psycopg connection lazy

    def _open_incremental_db(self) -> None:
        """Conecta + pré-carrega cache (host, source_lot_code) por host.

        No-op se incremental_only=false ou já carregado. Hosts vêm de
        `_get_known_hosts()` (default: hostname de cada start_url).
        """
        if not self._incremental_only or self._db_conn is not None:
            return
        dsn = os.environ.get("SUPABASE_DB_URL")
        if not dsn:
            self.logger.warning(
                "IncrementalCrawl: SUPABASE_DB_URL não setada — desativando"
            )
            self._incremental_only = False
            return
        try:
            import psycopg
        except ImportError:
            self.logger.error("psycopg não disponível — incremental desabilitado")
            self._incremental_only = False
            return

        hosts = self._get_known_hosts()
        if not hosts:
            self.logger.warning(
                "IncrementalCrawl: nenhum host detectado de start_urls — desabilita"
            )
            self._incremental_only = False
            return

        self._db_conn = psycopg.connect(dsn)
        try:
            with self._db_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.short_name, al.source_lot_code
                      FROM core.source s
                      JOIN core.auction_lot al ON al.source_id = s.id
                     WHERE s.short_name = ANY(%s)
                    """,
                    (list(hosts),),
                )
                for host, code in cur.fetchall():
                    if host and code:
                        self._known_lots.add((host, code))
        except Exception as e:
            self.logger.warning(
                "IncrementalCrawl: query DB falhou (%s) — modo full crawl", e
            )
            self._incremental_only = False
            self._known_lots.clear()
            self._db_conn.close()
            self._db_conn = None
            return

        self.logger.info(
            "IncrementalCrawl ATIVO: %d lots conhecidos em %d hosts",
            len(self._known_lots),
            len(hosts),
        )

    def lot_exists(self, host: str, source_lot_code: str) -> bool:
        """True se (host, source_lot_code) já está no DB. Sempre False
        quando incremental_only=false."""
        if not self._incremental_only:
            return False
        host_norm = (host or "").lower().removeprefix("www.")
        return (host_norm, str(source_lot_code)) in self._known_lots

    def _get_known_hosts(self) -> list[str]:
        """Default: hostnames de `start_urls`. Subclass override quando
        spider sabe melhor (ex.: provider que raspa 116 tenants, cada um
        é um host distinto)."""
        from urllib.parse import urlparse

        hosts: set[str] = set()
        for url in getattr(self, "start_urls", []):
            h = (urlparse(url).hostname or "").lower().removeprefix("www.")
            if h:
                hosts.add(h)
        return sorted(hosts)

    def close_incremental_db(self) -> None:
        if self._db_conn is not None:
            try:
                self._db_conn.close()
            except Exception:
                pass
            self._db_conn = None

    def make_listing_only_item(
        self,
        url: str,
        source_lot_code: str,
        status: str | None = None,
        auctioneer: str | None = None,
    ) -> dict[str, Any]:
        """Helper pra emitir item parcial quando lot existe.

        Pipeline detecta `listing_only_status_update=True` e faz só
        UPDATE de `current_status` + `last_seen_at` (sem mexer em
        address/spatial_unit/round/bids/imgs).
        """
        out: dict[str, Any] = {
            "url": url,
            "source_lot_code": source_lot_code,
            "listing_only_status_update": True,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }
        if status:
            out["status"] = status
        if auctioneer:
            out["auctioneer"] = auctioneer
        return out


class ProviderSpider(IncrementalCrawlMixin, BaseAuctionSpider):
    """Spider provider-driven.

    Subclass deve setar:
      - `name`              — slug Scrapy
      - `provider_slug`     — chave para selectors.yaml e site_providers.csv
      - `auctioneer_slug`   — slug pra `PropertyItem.auctioneer`. Em provider
                              multi-tenant (SOLEON), use o slug do provider e
                              opcionalmente sobrescreva por host em runtime.

    Spider arg:
      - `-a sites=N` (default 1) — top N sites do provider (por
        useful_links em site_analysis.csv) a serem raspados. `all` para todos.
      - `-a urls=...` — vírgula-CSV de URLs específicas (sobrescreve `sites`).
    """

    provider_slug: str = ""

    def __init__(
        self,
        sites: str = "1",
        urls: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if not self.provider_slug:
            raise ValueError(f"{type(self).__name__}: provider_slug não definido")

        self.selectors = self._load_selectors(self.provider_slug)

        # Resolve start_urls a partir de sites/urls
        if urls:
            self.start_urls = [u.strip() for u in urls.split(",") if u.strip()]
        else:
            self.start_urls = self._sites_for_provider(self.provider_slug, sites)

        if not self.start_urls:
            raise ValueError(
                f"{type(self).__name__}: sem URLs para iniciar "
                f"(provider={self.provider_slug}, sites={sites!r})"
            )

        self.logger.info(
            "ProviderSpider: provider=%s start_urls=%d (%s)",
            self.provider_slug,
            len(self.start_urls),
            self.start_urls[:3],
        )

    # ------------------------------------------------------------------
    # YAML & site selection
    # ------------------------------------------------------------------

    @staticmethod
    def _load_selectors(provider: str) -> dict:
        path = PROVIDERS_DIR / provider / "selectors.yaml"
        if not path.exists():
            raise FileNotFoundError(f"selectors.yaml não encontrado: {path}")
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: YAML precisa ser dict no top-level")
        # Validação leve: campos obrigatórios
        for k in ("auctioneer_slug", "listing_active", "detail"):
            if k not in data:
                raise ValueError(f"{path}: campo obrigatório ausente: {k!r}")
        return data

    @staticmethod
    def _sites_for_provider(provider: str, sites_arg: str) -> list[str]:
        if not SITE_PROVIDERS_CSV.exists():
            raise FileNotFoundError(SITE_PROVIDERS_CSV)
        rows: list[dict] = []
        with SITE_PROVIDERS_CSV.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("provider") != provider:
                    continue
                if r.get("cache_used") == "cache_missing":
                    continue
                rows.append(r)
        # Sem dado de useful_links no providers.csv — preserva ordem do CSV
        # (que já reflete a ordem original do site_analysis.csv). Para v1 isso
        # é suficiente; tiebreak fino é responsabilidade do select_arch_batch.
        if sites_arg.lower() == "all":
            limit = len(rows)
        else:
            try:
                limit = max(1, int(sites_arg))
            except ValueError:
                limit = 1
        seen_hosts: set[str] = set()
        out: list[str] = []
        for r in rows:
            url = (r.get("final_url") or "").strip()
            if not url:
                continue
            host = (urlparse(url).hostname or "").lower()
            if host in seen_hosts:
                continue
            seen_hosts.add(host)
            out.append(url)
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------
    # Helpers para parsers da subclass
    # ------------------------------------------------------------------

    def field_selector(self, field: str) -> tuple[str, str] | None:
        """Retorna `(selector, kind)` do `detail.field_selectors[field]` ou None."""
        fs = (self.selectors.get("detail") or {}).get("field_selectors") or {}
        spec = fs.get(field)
        if not spec:
            return None
        return spec["selector"], spec.get("kind", "css")

    def host_of(self, url: str) -> str:
        return (urlparse(url).hostname or "").lower()

    # ------------------------------------------------------------------
    # start_requests usa `make_request` da base (Playwright opt-in)
    # ------------------------------------------------------------------

    def start_requests(self) -> Iterable[Any]:
        for url in self.start_urls:
            yield self.make_request(url, callback=self.parse)
