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
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import yaml

from leilao_scraper.spiders.base import BaseAuctionSpider

REPO_ROOT = Path(__file__).resolve().parents[3]
PROVIDERS_DIR = REPO_ROOT / "specs" / "_providers"
SITE_PROVIDERS_CSV = REPO_ROOT / "data" / "intermediate" / "site_providers.csv"


class ProviderSpider(BaseAuctionSpider):
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
