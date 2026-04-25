"""Fase 1 — descoberta da lista de leiloeiros oficiais via API pública do INNLEI.

A página /leiloeiros é uma SPA Next.js cujo HTML não contém a lista; ela é
hidratada client-side via GET /api/public/leiloeiros (paginação JSON com cap
real de 100 itens/página). Este módulo consome esse endpoint diretamente —
ver `reports/innlei_recon.md` para o raciocínio e os campos disponíveis.
"""

from __future__ import annotations

import csv
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx
import typer
from loguru import logger

BASE_URL = "https://innlei.org.br"
LIST_ENDPOINT = "/api/public/leiloeiros"
PROFILE_ENDPOINT = "/api/public/leiloeiros/{id}"
PAGE_SIZE = 100  # cap real do servidor; valores > 100 fazem fallback para 20
USER_AGENT = "TodoLeilaoBot/0.1 (+contato: eplima.cc@gmail.com)"
REQUEST_TIMEOUT = 30.0
MIN_INTERVAL_S = 1.0  # 1 req/s
MAX_RETRIES = 3
BACKOFF_BASE_S = 1.5

CSV_COLUMNS = [
    "id",
    "slug",
    "nome",
    "uf",
    "cidade",
    "cep",
    "endereco",
    "email",
    "telefone",
    "celular",
    "dominio",
    "dominio_url",
    "dominio_status",
    "dominio_online",
    "situacao",
    "credenciamento",
    "is_associado",
    "nivel",
    "junta_comercial",
    "matricula",
    "ano_posse",
    "matriculas_extras",
    "facebook",
    "instagram",
    "linkedin",
    "youtube",
    "twitter",
    "tiktok",
    "imagem",
    "url_perfil_innlei",
]


@dataclass
class RateLimiter:
    min_interval_s: float
    _last_request_at: float = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        sleep_for = self.min_interval_s - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)
        self._last_request_at = time.monotonic()


def _request_with_retry(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    limiter: RateLimiter | None = None,
) -> httpx.Response:
    """GET com até MAX_RETRIES tentativas e backoff exponencial com jitter.

    Faz retry em erros de rede e em respostas 429/5xx. Ergue a última exceção
    se todas as tentativas falharem.
    """
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        if limiter is not None:
            limiter.wait()
        try:
            response = client.get(url, params=params)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            wait = BACKOFF_BASE_S**attempt + random.uniform(0, 0.5)
            logger.warning(
                "Falha de rede em {} (tentativa {}/{}): {}. Retry em {:.1f}s",
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
                f"{response.status_code} em {url}", request=response.request, response=response
            )
            wait = BACKOFF_BASE_S**attempt + random.uniform(0, 0.5)
            logger.warning(
                "HTTP {} em {} (tentativa {}/{}). Retry em {:.1f}s",
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


def _normalize(record: dict[str, Any]) -> dict[str, Any]:
    """Achata um registro da API para o schema CSV.

    A UF canônica vem de matriculas[0].junta.uf (duas letras: "SP", "PR").
    `junta.sigla` é a abreviação da própria Junta (JUCEPAR, JUCESP) e não
    serve como UF.
    """
    matriculas = record.get("matriculas") or []
    primary = matriculas[0] if matriculas else {}
    junta = primary.get("junta") or {}
    extras = "; ".join(
        f"{m.get('matricula', '')}@{(m.get('junta') or {}).get('uf', '')}" for m in matriculas[1:]
    )

    return {
        "id": record.get("id"),
        "slug": record.get("slug") or "",
        "nome": record.get("nome") or "",
        "uf": junta.get("uf") or "",
        "cidade": record.get("cidade") or "",
        "cep": record.get("cep") or "",
        "endereco": record.get("endereco") or "",
        "email": record.get("email") or "",
        "telefone": record.get("telefone") or "",
        "celular": record.get("celular") or "",
        "dominio": record.get("dominio") or "",
        "dominio_url": record.get("dominio_url") or "",
        "dominio_status": record.get("dominio_status") or "",
        "dominio_online": record.get("dominio_online"),
        "situacao": record.get("situacao") or "",
        "credenciamento": record.get("credenciamento") or "",
        "is_associado": record.get("isAssociado"),
        "nivel": record.get("nivel") or "",
        "junta_comercial": record.get("juntaComercial") or "",
        "matricula": record.get("matricula") or "",
        "ano_posse": record.get("anoPosse") or "",
        "matriculas_extras": extras,
        "facebook": record.get("facebook") or "",
        "instagram": record.get("instagram") or "",
        "linkedin": record.get("linkedin") or "",
        "youtube": record.get("youtube") or "",
        "twitter": record.get("twitter") or "",
        "tiktok": record.get("tiktok") or "",
        "imagem": record.get("imagem") or "",
        "url_perfil_innlei": (
            f"{BASE_URL}{PROFILE_ENDPOINT.format(id=record['id'])}"
            if record.get("id") is not None
            else ""
        ),
    }


def fetch_all_auctioneers(
    *,
    client: httpx.Client | None = None,
    page_size: int = PAGE_SIZE,
    limiter: RateLimiter | None = None,
) -> list[dict[str, Any]]:
    """Percorre /api/public/leiloeiros paginado e retorna todos os leiloeiros normalizados.

    Aceita um httpx.Client externo (para testes com MockTransport). Quando não
    fornecido, abre um client próprio e respeita o rate limit padrão.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
    if limiter is None:
        limiter = RateLimiter(min_interval_s=MIN_INTERVAL_S)

    try:
        first = _request_with_retry(
            client, LIST_ENDPOINT, params={"page": 1, "limit": page_size}, limiter=limiter
        ).json()
        total = int(first.get("total", 0))
        total_pages = int(first.get("totalPages", 1))
        logger.info("INNLEI total={} totalPages={} page_size={}", total, total_pages, page_size)

        records: list[dict[str, Any]] = [_normalize(r) for r in first.get("data", [])]
        for page in range(2, total_pages + 1):
            payload = _request_with_retry(
                client, LIST_ENDPOINT, params={"page": page, "limit": page_size}, limiter=limiter
            ).json()
            page_data = payload.get("data", [])
            records.extend(_normalize(r) for r in page_data)
            logger.info("Página {}/{} ok ({} registros)", page, total_pages, len(page_data))

        if total and len(records) != total:
            logger.warning(
                "Esperava {} leiloeiros, obteve {} — listagem pode ter mudado durante o crawl",
                total,
                len(records),
            )
        return records
    finally:
        if owns_client:
            client.close()


def write_csv(records: Iterable[dict[str, Any]], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record)
            n += 1
    return n


app = typer.Typer(help="Scrapers da lista pública de leiloeiros do INNLEI.")


@app.callback()
def _main() -> None:
    """Força Typer a tratar `run` como subcomando explícito."""


@app.command()
def run(
    output: Path = typer.Option(
        Path("data/intermediate/auctioneers_raw.csv"),
        "--output",
        "-o",
        help="Caminho do CSV de saída.",
    ),
    page_size: int = typer.Option(
        PAGE_SIZE, "--page-size", min=1, max=100, help="Itens por página (cap real = 100)."
    ),
) -> None:
    """Baixa todos os leiloeiros do INNLEI e grava em CSV."""
    logger.info("Iniciando descoberta INNLEI -> {}", output)
    started = time.monotonic()
    records = fetch_all_auctioneers(page_size=page_size)
    n = write_csv(records, output)
    elapsed = time.monotonic() - started
    logger.success("Gravados {} leiloeiros em {} ({:.1f}s)", n, output, elapsed)


if __name__ == "__main__":
    app()
