"""Runner para todos os scrapers de Juntas Comerciais.

Uso::

    uv run python -m discovery.juntas_scraper [--output PATH]

Para cada Junta registrada em `REGISTRY`, executa o scraper. Captura
``NotImplementedError`` (Juntas-stub) e exceções de rede sem quebrar o
batch — relata um resumo ao final. Saída CSV no schema canônico::

    nome,matricula,junta_sigla,uf,situacao,juc_url,scraped_at

Implementação serial intencional: cada Junta tem seu próprio hostname e
RateLimiter; rodar em paralelo só ajudaria se houvesse muitas Juntas com
muitos registros (não é o caso). Manter serial é mais simples e respeita
melhor os hosts.
"""

from __future__ import annotations

import csv
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import typer
from loguru import logger

from . import CSV_COLUMNS, REGISTRY

# Suprime InsecureRequestWarning — algumas Juntas têm cadeia SSL inválida.
try:  # pragma: no cover - dependency optional
    from urllib3.exceptions import InsecureRequestWarning  # type: ignore

    warnings.simplefilter("ignore", InsecureRequestWarning)
except Exception:
    pass

app = typer.Typer(help="Runner dos scrapers das 27 Juntas Comerciais.")


@app.callback()
def _main() -> None:  # pragma: no cover - typer plumbing
    """Força Typer a tratar `run` como subcomando explícito."""


@app.command()
def run(
    output: Path = typer.Option(
        Path("data/intermediate/auctioneers_juntas.csv"),
        "--output",
        "-o",
        help="Caminho do CSV de saída.",
    ),
    only: str = typer.Option(
        "",
        "--only",
        help="Lista CSV de siglas para executar isoladamente (debug).",
    ),
) -> None:
    """Executa todos os scrapers e grava o CSV consolidado."""
    siglas = [s.strip().upper() for s in only.split(",") if s.strip()] or list(REGISTRY)
    logger.info("Iniciando scrape de {} Juntas -> {}", len(siglas), output)

    started = time.monotonic()
    all_records: list[dict[str, Any]] = []
    successes: list[tuple[str, int]] = []
    stubs: list[tuple[str, str]] = []
    failures: list[tuple[str, str]] = []

    for sigla in siglas:
        cls = REGISTRY.get(sigla)
        if cls is None:
            logger.warning("Sigla desconhecida: {}", sigla)
            continue
        try:
            with cls() as scraper:
                records = scraper.fetch_leiloeiros()
            all_records.extend(records)
            successes.append((sigla, len(records)))
        except NotImplementedError as exc:
            stubs.append((sigla, str(exc)))
            logger.info("[{}] stub: {}", sigla, exc)
        except Exception as exc:
            failures.append((sigla, f"{type(exc).__name__}: {exc}"))
            logger.error("[{}] falhou: {}", sigla, exc)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for record in all_records:
            writer.writerow(record)

    elapsed = time.monotonic() - started

    logger.success("Gravados {} leiloeiros em {} ({:.1f}s)", len(all_records), output, elapsed)
    logger.info("=== Resumo ===")
    for sigla, n in sorted(successes, key=lambda x: -x[1]):
        logger.info("  OK  {:<10} {:>5} leiloeiros", sigla, n)
    for sigla, reason in sorted(stubs):
        logger.info("  STUB {:<10} {}", sigla, reason)
    for sigla, reason in sorted(failures):
        logger.warning("  FAIL {:<10} {}", sigla, reason)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("run")
    app()
