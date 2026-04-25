"""Fase 2 — enriquecimento via SITE EXTERNO de cada leiloeiro.

Como mostrado em `reports/innlei_recon.md`, o perfil INNLEI praticamente não
adiciona nada à listagem (apenas bairro, numero, tiktok) e não tem o campo
mais importante para a fase 3: o tipo de leilão. O sinal real está no site
declarado em `dominio`. Este módulo, portanto, ignora o perfil INNLEI e vai
direto buscar título, meta description, meta keywords e um trecho do texto
visível de cada site externo.

Para cada leiloeiro, gera as colunas:
  site_status_code, site_final_url, site_title, site_description,
  site_keywords, site_body_excerpt, site_error.

Sem `dominio`, todas as colunas ficam vazias e `site_error="no_domain"`.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx
import typer
from bs4 import BeautifulSoup
from loguru import logger

CACHE_DIR = Path("data/intermediate/cache/external_sites")
USER_AGENT = "TodoLeilaoBot/0.1 (+contato: eplima.cc@gmail.com)"
DEFAULT_TIMEOUT = 12.0
DEFAULT_CONCURRENCY = 5
BODY_EXCERPT_CHARS = 4000

ENRICH_COLUMNS = [
    "site_status_code",
    "site_final_url",
    "site_title",
    "site_description",
    "site_keywords",
    "site_body_excerpt",
    "site_error",
]


def _cache_path(url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def _read_cache(url: str) -> dict[str, Any] | None:
    path = _cache_path(url)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(url: str, payload: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(url).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def extract_meta(html: str) -> dict[str, str]:
    """Extrai title / meta description / meta keywords / excerto visível.

    Removemos tags ruidosas (script/style/noscript) antes de pegar o texto.
    """
    soup = BeautifulSoup(html, "lxml")

    title = soup.title.get_text(strip=True) if soup.title else ""

    def _meta(name: str) -> str:
        # case-insensitive: aceita name="description" ou name="DESCRIPTION"
        for tag in soup.find_all("meta"):
            if (tag.get("name") or "").lower() == name and tag.get("content"):
                return tag["content"].strip()
            if (tag.get("property") or "").lower() == f"og:{name}" and tag.get("content"):
                return tag["content"].strip()
        return ""

    description = _meta("description")
    keywords = _meta("keywords")

    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    body_text = soup.get_text(separator=" ", strip=True)
    body_excerpt = " ".join(body_text.split())[:BODY_EXCERPT_CHARS]

    return {
        "site_title": title,
        "site_description": description,
        "site_keywords": keywords,
        "site_body_excerpt": body_excerpt,
    }


async def fetch_one(
    client: httpx.AsyncClient,
    url: str,
    *,
    use_cache: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    if use_cache:
        cached = _read_cache(url)
        if cached is not None:
            cached["_cache_hit"] = True
            return cached

    payload: dict[str, Any] = {
        "url": url,
        "fetched_at": int(time.time()),
        "site_status_code": "",
        "site_final_url": "",
        "site_title": "",
        "site_description": "",
        "site_keywords": "",
        "site_body_excerpt": "",
        "site_error": "",
    }
    try:
        response = await client.get(url, timeout=timeout, follow_redirects=True)
        payload["site_status_code"] = response.status_code
        payload["site_final_url"] = str(response.url)
        content_type = (response.headers.get("content-type") or "").lower()
        if response.status_code >= 400:
            payload["site_error"] = f"http_{response.status_code}"
        elif "html" not in content_type:
            payload["site_error"] = f"non_html:{content_type.split(';')[0]}"
        else:
            payload.update(extract_meta(response.text))
    except httpx.TimeoutException:
        payload["site_error"] = "timeout"
    except httpx.TooManyRedirects:
        payload["site_error"] = "too_many_redirects"
    except httpx.ConnectError as exc:
        payload["site_error"] = f"connect:{exc.__class__.__name__}"
    except httpx.RequestError as exc:
        payload["site_error"] = f"request:{exc.__class__.__name__}"
    except Exception as exc:  # SSL errors, decoding, etc.
        payload["site_error"] = f"other:{type(exc).__name__}"

    _write_cache(url, payload)
    payload["_cache_hit"] = False
    return payload


async def enrich_dataframe(
    rows: list[dict[str, Any]],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float = DEFAULT_TIMEOUT,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """Para cada linha com `dominio`, busca metadata do site e mescla nas colunas."""
    targets: list[tuple[int, str]] = []
    for i, row in enumerate(rows):
        dom = (row.get("dominio") or "").strip()
        if dom:
            targets.append((i, dom))

    logger.info(
        "Enriquecendo {} sites externos (concurrency={}, timeout={}s, cache={})",
        len(targets),
        concurrency,
        timeout,
        use_cache,
    )

    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }

    progress = {"done": 0, "cache": 0, "fail": 0}
    total = len(targets)

    async with httpx.AsyncClient(
        headers=headers, limits=limits, http2=False, verify=True
    ) as client:

        async def worker(idx: int, url: str) -> tuple[int, dict[str, Any]]:
            async with sem:
                payload = await fetch_one(client, url, use_cache=use_cache, timeout=timeout)
            progress["done"] += 1
            if payload.get("_cache_hit"):
                progress["cache"] += 1
            if payload.get("site_error"):
                progress["fail"] += 1
            if progress["done"] % 50 == 0 or progress["done"] == total:
                logger.info(
                    "Progresso {}/{}  cache_hits={}  errors={}",
                    progress["done"],
                    total,
                    progress["cache"],
                    progress["fail"],
                )
            return idx, payload

        results = await asyncio.gather(*(worker(i, u) for i, u in targets))

    enriched = [dict(r) for r in rows]  # cópia
    for row in enriched:
        for col in ENRICH_COLUMNS:
            row.setdefault(col, "")
        if not (row.get("dominio") or "").strip():
            row["site_error"] = "no_domain"

    for idx, payload in results:
        for col in ENRICH_COLUMNS:
            enriched[idx][col] = payload.get(col, "") or ""

    return enriched


def write_csv(rows: list[dict[str, Any]], output: Path, base_columns: list[str]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = base_columns + [c for c in ENRICH_COLUMNS if c not in base_columns]
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


app = typer.Typer(help="Enriquecimento de leiloeiros consultando o site externo declarado.")


@app.callback()
def _main() -> None:
    """Força Typer a tratar `run` como subcomando explícito."""


@app.command()
def run(
    input_csv: Path = typer.Option(
        Path("data/intermediate/auctioneers_raw.csv"),
        "--input",
        "-i",
        help="CSV gerado pelo innlei_scraper.",
    ),
    output: Path = typer.Option(
        Path("data/intermediate/auctioneers_enriched.csv"),
        "--output",
        "-o",
        help="CSV enriquecido.",
    ),
    concurrency: int = typer.Option(
        DEFAULT_CONCURRENCY,
        "--concurrency",
        "-c",
        min=1,
        max=20,
        help="Conexões simultâneas (default 5).",
    ),
    timeout: float = typer.Option(
        DEFAULT_TIMEOUT, "--timeout", "-t", help="Timeout por requisição (s)."
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Ignora cache local (re-baixa todos os sites)."
    ),
) -> None:
    """Le auctioneers_raw.csv e produz auctioneers_enriched.csv com metadados do site externo."""
    logger.info("Lendo {}", input_csv)
    with input_csv.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        base_columns = list(reader.fieldnames or [])
    logger.info("{} linhas no CSV de entrada", len(rows))

    started = time.monotonic()
    enriched = asyncio.run(
        enrich_dataframe(rows, concurrency=concurrency, timeout=timeout, use_cache=not no_cache)
    )
    elapsed = time.monotonic() - started

    write_csv(enriched, output, base_columns)

    total = len(enriched)
    with_domain = sum(1 for r in enriched if (r.get("dominio") or "").strip())
    no_domain = total - with_domain
    online = sum(1 for r in enriched if not r.get("site_error") and r.get("site_status_code"))
    error = sum(1 for r in enriched if r.get("site_error") and r["site_error"] != "no_domain")

    logger.success("Gravados {} leiloeiros em {} ({:.1f}s)", total, output, elapsed)
    logger.info("=== Resumo ===")
    logger.info("Total leiloeiros: {}", total)
    logger.info("Com dominio:      {}", with_domain)
    logger.info("Sem dominio:      {}", no_domain)
    logger.info("Site online (sem erro):    {}", online)
    logger.info("Site com erro/offline:     {}", error)


if __name__ == "__main__":
    app()
