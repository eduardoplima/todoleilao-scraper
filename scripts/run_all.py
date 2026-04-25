"""Runner para todos os spiders do `leilao_scraper`.

  scripts/run_all.py [--limit N] [--exclude name1,name2] [--only name1,name2]

Comportamento:

1. Lista os spiders disponíveis via `scrapy list` (rodado dentro do projeto
   Scrapy). Por default exclui `dummy` e `playwright_example` (não são
   leiloeiros reais).
2. Para cada spider, dispara `scrapy crawl <name> -s CLOSESPIDER_ITEMCOUNT=N`
   em SUBPROCESSO ISOLADO. Falha de um spider não derruba os demais.
3. Coleta todos os JSONLs gravados em `data/raw/<spider>/*.jsonl` (apenas
   os arquivos do run atual — identificados pelo `started_at`) e consolida
   em `data/processed/properties.parquet` via pandas + pyarrow.
4. Imprime resumo final por spider: items, exit code, duração.

Saídas:
  - data/processed/properties.parquet (consolidado)
  - data/processed/run_log.json       (metadados do run)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import typer
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRAPY_PROJECT = PROJECT_ROOT / "scrapy_project"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

# Spiders que NÃO são leiloeiros reais — não entram no consolidado.
EXCLUDE_DEFAULT = {"dummy", "playwright_example"}

app = typer.Typer(help="Roda todos os spiders e consolida em parquet.")


def list_spiders() -> list[str]:
    """`scrapy list` no diretório do projeto."""
    result = subprocess.run(
        ["uv", "run", "scrapy", "list"],
        cwd=SCRAPY_PROJECT,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(name.strip() for name in result.stdout.splitlines() if name.strip())


def run_one(name: str, limit: int, started_at_iso: str) -> dict[str, Any]:
    """Roda um spider isolado em subprocesso. Retorna metadados do run."""
    logger.info("→ {} (limit={})", name, limit)
    t0 = time.monotonic()
    cmd = [
        "uv", "run", "scrapy", "crawl", name,
        "-s", f"CLOSESPIDER_ITEMCOUNT={limit}",
        "-s", "LOG_LEVEL=ERROR",
    ]
    proc = subprocess.run(
        cmd,
        cwd=SCRAPY_PROJECT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    elapsed = time.monotonic() - t0

    files_after = sorted((RAW_DIR / name).glob("*Z.jsonl")) if (RAW_DIR / name).exists() else []
    new_files = [f for f in files_after if f.stat().st_mtime >= _iso_to_epoch(started_at_iso)]

    items = 0
    for f in new_files:
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    items += 1

    return {
        "spider": name,
        "exit_code": proc.returncode,
        "elapsed_s": round(elapsed, 1),
        "items": items,
        "files": [str(f.relative_to(PROJECT_ROOT)) for f in new_files],
        "stderr_tail": proc.stderr[-400:] if proc.returncode != 0 else "",
    }


def _iso_to_epoch(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def consolidate(run_results: list[dict[str, Any]], output: Path) -> int:
    """Junta todos os JSONLs gerados nesse run em um Parquet único."""
    rows: list[dict[str, Any]] = []
    for r in run_results:
        for f_rel in r["files"]:
            f = PROJECT_ROOT / f_rel
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    obj["__source_file"] = str(f_rel)
                    rows.append(obj)

    if not rows:
        logger.warning("Nenhum item — não vou gravar parquet vazio")
        return 0

    df = pd.DataFrame(rows)

    # Normaliza colunas list/dict para parquet (pyarrow aceita, mas
    # converter aninhamento para JSON-string facilita SQL/df.explode posterior).
    for col in ("images", "documents"):
        if col in df.columns:
            df[col] = df[col].apply(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else None)
    if "address" in df.columns:
        df["address"] = df["address"].apply(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else None)

    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output, engine="pyarrow", compression="snappy", index=False)
    logger.success("→ {} ({} linhas, {} colunas)", output, len(df), len(df.columns))
    return len(df)


@app.command()
def main(
    limit: int = typer.Option(20, "--limit", "-n", help="CLOSESPIDER_ITEMCOUNT por spider."),
    exclude: str = typer.Option(
        ",".join(sorted(EXCLUDE_DEFAULT)),
        "--exclude", "-x",
        help="Spiders a pular (csv).",
    ),
    only: str = typer.Option(
        "", "--only", "-o",
        help="Roda só esses spiders (csv). Sobrescreve --exclude.",
    ),
    output: Path = typer.Option(
        PROCESSED_DIR / "properties.parquet", "--output",
        help="Caminho do parquet consolidado.",
    ),
    run_log: Path = typer.Option(
        PROCESSED_DIR / "run_log.json", "--run-log",
        help="Metadados JSON deste run.",
    ),
) -> None:
    """Executa todos os spiders e consolida em Parquet."""
    spiders = list_spiders()
    if only:
        wanted = {s.strip() for s in only.split(",") if s.strip()}
        spiders = [s for s in spiders if s in wanted]
    else:
        skip = {s.strip() for s in exclude.split(",") if s.strip()}
        spiders = [s for s in spiders if s not in skip]
    logger.info("Spiders: {}", spiders)

    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    results: list[dict[str, Any]] = []
    for s in spiders:
        try:
            results.append(run_one(s, limit, started_at))
        except subprocess.TimeoutExpired:
            results.append({
                "spider": s, "exit_code": -1, "elapsed_s": 600,
                "items": 0, "files": [], "stderr_tail": "TIMEOUT",
            })

    total = consolidate(results, output)

    run_metadata = {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "limit_per_spider": limit,
        "total_items_consolidated": total,
        "spiders": results,
    }
    run_log.parent.mkdir(parents=True, exist_ok=True)
    run_log.write_text(json.dumps(run_metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    # resumo na stdout
    logger.info("=" * 60)
    logger.info("RESUMO")
    logger.info("=" * 60)
    logger.info(f"{'spider':<25} {'exit':>4} {'tempo':>7} {'itens':>6}")
    for r in results:
        marker = "✓" if r["exit_code"] == 0 else "✗"
        logger.info(
            f"  {marker} {r['spider']:<23} {r['exit_code']:>4} {r['elapsed_s']:>6.1f}s {r['items']:>6}"
        )
    logger.info(f"  → {total} imóveis em {output}")


if __name__ == "__main__":
    app()
