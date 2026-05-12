"""Base class para scrapers das Juntas Comerciais (27 UFs).

Cada Junta tem suas próprias quirks (paginação, captcha, JS dinâmico, PDF-only)
mas todas devem expor o mesmo `fetch_leiloeiros() -> list[dict]` com schema
`nome,matricula,junta_sigla,uf,situacao,juc_url,scraped_at`.

Convenções:
- Retry exponencial em erro de rede e 5xx/429 (3 tentativas).
- Rate limit configurável por instância — default 2s entre requests da mesma Junta.
- Browser-like User-Agent (Juntas estaduais frequentemente bloqueiam UAs custom).
- Quando a Junta exige CAPTCHA/LAI/PDF não automatizável, subclass deve manter
  `fetch_leiloeiros` que ergue `NotImplementedError`. O runner registra como
  `requires_manual_request` em vez de quebrar.
"""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger

# Schema canônico do CSV de saída.
CSV_COLUMNS = ["nome", "matricula", "junta_sigla", "uf", "situacao", "juc_url", "scraped_at"]

# UA realista — muitas Juntas usam WAF (CloudFront/Cloudflare) que bloqueia bots óbvios.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15"
)

DEFAULT_TIMEOUT = 30.0
DEFAULT_RATE_LIMIT_S = 2.0
MAX_RETRIES = 3
BACKOFF_BASE_S = 1.5


def now_iso() -> str:
    """Timestamp UTC ISO 8601, igual ao usado em outras partes do pipeline."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RateLimiter:
    """Throttle simples baseado em monotonic clock — 1 instância por hostname."""

    min_interval_s: float = DEFAULT_RATE_LIMIT_S
    _last_request_at: float = field(default=0.0)

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        sleep_for = self.min_interval_s - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)
        self._last_request_at = time.monotonic()


class JuntaScraper(ABC):
    """Contrato comum para todos os scrapers de Juntas Comerciais."""

    #: Sigla canônica da Junta (ex.: "JUCEPAR", "JUCESP"). Subclass DEVE override.
    sigla: str = ""
    #: UF de duas letras (ex.: "PR", "SP"). Subclass DEVE override.
    uf: str = ""
    #: URL base da Junta — usada como referência e logging.
    base_url: str = ""

    def __init__(self, *, rate_limit_s: float = DEFAULT_RATE_LIMIT_S) -> None:
        self.rate_limit_s = rate_limit_s
        self.limiter = RateLimiter(min_interval_s=rate_limit_s)
        self._client: httpx.Client | None = None

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers={
                    "User-Agent": BROWSER_USER_AGENT,
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,"
                        "image/webp,*/*;q=0.8"
                    ),
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                },
                timeout=DEFAULT_TIMEOUT,
                follow_redirects=True,
                verify=False,  # algumas Juntas têm cadeia SSL quebrada (ex.: jucisrs)
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "JuntaScraper":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """GET com retry exponencial + rate limit + UA browser."""
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self.limiter.wait()
            try:
                response = self.client.get(url, **kwargs)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                wait = BACKOFF_BASE_S**attempt + random.uniform(0, 0.5)
                logger.warning(
                    "[{}] Falha de rede em {} (tentativa {}/{}): {}. Retry em {:.1f}s",
                    self.sigla,
                    url,
                    attempt,
                    MAX_RETRIES,
                    exc,
                    wait,
                )
                time.sleep(wait)
                continue

            if response.status_code in (429, 500, 502, 503, 504):
                last_exc = httpx.HTTPStatusError(
                    f"{response.status_code} em {url}",
                    request=response.request,
                    response=response,
                )
                wait = BACKOFF_BASE_S**attempt + random.uniform(0, 0.5)
                logger.warning(
                    "[{}] HTTP {} em {} (tentativa {}/{}). Retry em {:.1f}s",
                    self.sigla,
                    response.status_code,
                    url,
                    attempt,
                    MAX_RETRIES,
                    wait,
                )
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response

        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------------
    # Contrato
    # ------------------------------------------------------------------

    @abstractmethod
    def fetch_leiloeiros(self) -> list[dict[str, Any]]:
        """Retorna a lista de leiloeiros desta Junta no schema CSV canônico.

        Schema (exato):
            {nome, matricula, junta_sigla, uf, situacao, juc_url, scraped_at}

        Levantar ``NotImplementedError("requires_manual_request: …")`` em Juntas
        que só publicam por LAI/CAPTCHA/PDF-only. O runner trata esse caso
        gracefully — não é erro fatal.
        """

    # ------------------------------------------------------------------
    # Util para subclasses
    # ------------------------------------------------------------------

    def record(self, *, nome: str, matricula: str, situacao: str = "regular") -> dict[str, Any]:
        """Helper para montar um dict no schema canônico já preenchido."""
        return {
            "nome": (nome or "").strip(),
            "matricula": (matricula or "").strip(),
            "junta_sigla": self.sigla,
            "uf": self.uf,
            "situacao": (situacao or "").strip().lower() or "regular",
            "juc_url": self.base_url,
            "scraped_at": now_iso(),
        }


class StubJuntaScraper(JuntaScraper):
    """Stub para Juntas que exigem captcha / LAI / PDF não automatizável.

    Erro: ``NotImplementedError`` com prefixo ``requires_manual_request``.
    O runner registra a Junta como pendente e continua.
    """

    reason: str = "requires_manual_request: implementação pendente"

    def fetch_leiloeiros(self) -> list[dict[str, Any]]:  # pragma: no cover - trivial
        raise NotImplementedError(self.reason)
