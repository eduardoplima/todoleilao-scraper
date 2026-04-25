"""Fase 5 — localiza a URL da listagem de imóveis em cada site analisado.

Estratégia (em ordem):

1. Lê o HTML em cache do `site_analyzer` (preferindo o `dynamic.html` por ser
   mais completo). Não re-baixa a home — economia significativa, já que o
   analyzer já gastou Playwright nelas.
2. Pontua cada `<a>` por:
   - texto-âncora (`Imóveis`, `Ativos Imobiliários`, `Leilões`, `Lotes`, ...)
   - padrão de path (`/imoveis`, `/leiloes`, `categoria=imovel`, ...)
3. Tenta `<base>/sitemap.xml` e adiciona URLs cujo path contenha keywords.
4. Faz GET nas top-N candidatas via httpx e conta quantas ocorrências de
   preço (`R$ X.XXX,XX`) cada uma contém. >5 vira "items_detected".
5. Sites com `requires_js_for_listings=True` e items_detected<5 ganham nota
   `requires_js` — o httpx não vê listagens renderizadas no client.

Saída em `data/intermediate/listing_urls.csv`:
auctioneer_slug, site, listing_url, items_detected, sample_item_url, notes,
needs_manual_review.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import re
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
import typer
from bs4 import BeautifulSoup
from loguru import logger

CACHE_DIR = Path("data/intermediate/cache/sites")  # mesmo cache do site_analyzer
USER_AGENT = "TodoLeilaoBot/0.1 (+contato: eplima.cc@gmail.com)"
HTTPX_TIMEOUT = 15.0
DEFAULT_CONCURRENCY = 5
TOP_N_CANDIDATES = 5
ITEMS_THRESHOLD = 5  # >5 elementos com preço → listagem confirmada

# vocab para texto-âncora (sem acento — comparação normalizada)
TEXT_STRONG = ("imoveis", "imovel", "ativos imobiliarios", "imobiliario", "imobiliarios")
TEXT_MEDIUM = ("leiloes", "leilao", "lotes")

# substrings de path
PATH_STRONG = ("/imoveis", "/imovel", "/ativos-imobiliarios", "/imobiliario")
PATH_MEDIUM = ("/leiloes", "/leilao", "/lotes", "categoria=imovel", "tipo=imovel")

PRICE_RE = re.compile(r"R\$\s*[\d.,]+")

OUT_COLUMNS = [
    "id",
    "auctioneer_slug",
    "site",
    "listing_url",
    "items_detected",
    "sample_item_url",
    "notes",
    "needs_manual_review",
]


def _norm(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text or "")
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower().strip()


def _key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _read_cached_html(url: str) -> tuple[str, str]:
    if not url:
        return "", ""
    s_p = CACHE_DIR / f"{_key(url)}.static.html"
    d_p = CACHE_DIR / f"{_key(url)}.dynamic.html"
    s = s_p.read_text(encoding="utf-8", errors="replace") if s_p.exists() else ""
    d = d_p.read_text(encoding="utf-8", errors="replace") if d_p.exists() else ""
    return s, d


# ---------- scoring -------------------------------------------------------


def score_candidate(text: str, href: str) -> tuple[int, list[str]]:
    """Pontua um candidato (texto-âncora, href). 0 = descartar."""
    text_norm = _norm(text)
    href_norm = href.lower()
    score = 0
    reasons: list[str] = []

    for kw in TEXT_STRONG:
        if kw in text_norm:
            score += 10
            reasons.append(f"text+{kw}")
            break
    else:
        for kw in TEXT_MEDIUM:
            if kw in text_norm:
                score += 5
                reasons.append(f"text~{kw}")
                break

    for kw in PATH_STRONG:
        if kw in href_norm:
            score += 6
            reasons.append(f"path+{kw}")
            break
    else:
        for kw in PATH_MEDIUM:
            if kw in href_norm:
                score += 3
                reasons.append(f"path~{kw}")
                break

    return score, reasons


def find_candidates(html: str, base_url: str) -> list[tuple[str, int, list[str], str]]:
    """Retorna [(abs_url, score, reasons, anchor_text)] ordenado por score desc."""
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    best: dict[str, tuple[int, list[str], str]] = {}
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        text = a.get_text(" ", strip=True)
        score, reasons = score_candidate(text, href)
        if score == 0:
            continue
        absolute = urljoin(base_url, href)
        prev = best.get(absolute)
        if prev is None or prev[0] < score:
            best[absolute] = (score, reasons, text[:80])
    return sorted(
        ((u, s, r, t) for u, (s, r, t) in best.items()),
        key=lambda x: -x[1],
    )


def filter_sitemap_urls(urls: list[str]) -> list[tuple[str, int, list[str], str]]:
    """Aplica score só por path nas URLs de sitemap."""
    out = []
    for u in urls:
        score, reasons = score_candidate("", u)
        if score > 0:
            out.append((u, score, reasons + ["from-sitemap"], ""))
    out.sort(key=lambda x: -x[1])
    return out


# ---------- item detection ------------------------------------------------


def detect_items(html: str, base_url: str = "") -> tuple[int, str]:
    """Conta ocorrências de preço (R$) e tenta achar um link próximo a uma delas."""
    if not html:
        return 0, ""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator=" ")
    n = len(PRICE_RE.findall(text))

    sample = ""
    for el in soup.find_all(string=PRICE_RE):
        ancestor = el.parent
        for _ in range(8):
            if ancestor is None:
                break
            try:
                a = ancestor.find("a", href=True)
            except AttributeError:
                a = None
            if a:
                href = (a.get("href") or "").strip()
                if href and not href.startswith(("javascript:", "mailto:", "tel:", "#")):
                    sample = urljoin(base_url, href) if base_url else href
                    break
            ancestor = ancestor.parent
        if sample:
            break

    return n, sample


# ---------- network -------------------------------------------------------


async def fetch_sitemap(client: httpx.AsyncClient, base_url: str) -> list[str]:
    """Tenta GET /sitemap.xml. Falha silenciosa retorna []."""
    if not base_url:
        return []
    sm_url = urljoin(base_url, "/sitemap.xml")
    try:
        r = await client.get(sm_url, timeout=HTTPX_TIMEOUT, follow_redirects=True)
    except Exception:
        return []
    if r.status_code != 200:
        return []
    try:
        soup = BeautifulSoup(r.text, "xml")
        return [loc.get_text(strip=True) for loc in soup.find_all("loc")]
    except Exception:
        return []


async def validate_candidate(client: httpx.AsyncClient, candidate_url: str) -> tuple[int, str, str]:
    """Retorna (items_count, sample_item_url, error)."""
    try:
        r = await client.get(candidate_url, timeout=HTTPX_TIMEOUT, follow_redirects=True)
    except httpx.TimeoutException:
        return 0, "", "timeout"
    except Exception as e:
        return 0, "", f"{type(e).__name__}"

    if r.status_code >= 400:
        return 0, "", f"http_{r.status_code}"
    ct = (r.headers.get("content-type") or "").lower()
    if "html" not in ct:
        return 0, "", f"non_html:{ct.split(';')[0].strip()}"
    n, sample = detect_items(r.text, str(r.url))
    return n, sample, ""


# ---------- per-site main flow --------------------------------------------


async def find_listing_for_site(
    client: httpx.AsyncClient,
    site_row: dict[str, Any],
    *,
    max_validate: int = TOP_N_CANDIDATES,
) -> dict[str, Any]:
    site = (site_row.get("dominio") or "").strip()
    base = (site_row.get("final_url") or site).strip()

    static_html, dynamic_html = _read_cached_html(site)
    primary_html = dynamic_html or static_html

    candidates = find_candidates(primary_html, base or site)
    notes: list[str] = []

    if base:
        sm_urls = await fetch_sitemap(client, base)
        if sm_urls:
            notes.append(f"sitemap={len(sm_urls)}urls")
            existing = {c[0] for c in candidates}
            for u, s, r, t in filter_sitemap_urls(sm_urls)[:5]:
                if u not in existing:
                    candidates.append((u, s + 1, r, t))
                    existing.add(u)
        else:
            notes.append("no_sitemap")

    candidates.sort(key=lambda x: -x[1])

    best_count = 0
    best_url = ""
    best_sample = ""
    best_reasons: list[str] = []
    tried = 0

    for cand_url, _score, reasons, _text in candidates[:max_validate]:
        items, sample, err = await validate_candidate(client, cand_url)
        tried += 1
        if err and items == 0 and not best_url:
            # registra o melhor candidato mesmo se a validação falhou
            best_url, best_reasons = cand_url, reasons
        if items > best_count:
            best_count = items
            best_url = cand_url
            best_sample = sample
            best_reasons = reasons
        if items >= 20:  # forte sinal — para de iterar
            break

    if not candidates:
        notes.append("no_candidates_in_html")
    notes.append(f"tried={tried}")
    if best_reasons:
        notes.append("matched=" + ",".join(best_reasons))
    if (
        site_row.get("requires_js_for_listings") or ""
    ).strip().lower() == "true" and best_count < ITEMS_THRESHOLD:
        notes.append("requires_js")

    needs_manual = best_count < ITEMS_THRESHOLD

    return {
        "id": site_row.get("id") or "",
        "auctioneer_slug": site_row.get("slug") or "",
        "site": site,
        "listing_url": best_url,
        "items_detected": best_count,
        "sample_item_url": best_sample,
        "notes": "; ".join(notes),
        "needs_manual_review": needs_manual,
    }


async def find_all_listings(
    rows: list[dict[str, Any]],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9"}
    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)
    total = len(rows)
    progress = {"done": 0, "with_listing": 0, "items_ok": 0}

    async with httpx.AsyncClient(headers=headers, limits=limits) as client:

        async def worker(row):
            async with sem:
                result = await find_listing_for_site(client, row)
            progress["done"] += 1
            if result["listing_url"]:
                progress["with_listing"] += 1
            if result["items_detected"] >= ITEMS_THRESHOLD:
                progress["items_ok"] += 1
            if progress["done"] % 25 == 0 or progress["done"] == total:
                logger.info(
                    "Progresso {}/{}  com_url={}  items>={}={}",
                    progress["done"],
                    total,
                    progress["with_listing"],
                    ITEMS_THRESHOLD,
                    progress["items_ok"],
                )
            return result

        return await asyncio.gather(*[worker(r) for r in rows])


# ---------- CLI -----------------------------------------------------------

app = typer.Typer(help="Localiza a URL da listagem de imóveis em cada site analisado.")


@app.callback()
def _main() -> None:
    """Força Typer a tratar `run` como subcomando explícito."""


@app.command()
def run(
    input_csv: Path = typer.Option(Path("data/intermediate/site_analysis.csv"), "--input", "-i"),
    output: Path = typer.Option(Path("data/intermediate/listing_urls.csv"), "--output", "-o"),
    concurrency: int = typer.Option(DEFAULT_CONCURRENCY, "--concurrency", "-c"),
    only_accessible: bool = typer.Option(True, "--only-accessible/--all"),
) -> None:
    with input_csv.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    if only_accessible:
        rows = [
            r
            for r in rows
            if not (r.get("error") or "").strip() and (r.get("dominio") or "").strip()
        ]

    logger.info("Buscando listagem em {} sites (concurrency={})", len(rows), concurrency)
    started = time.monotonic()
    results = asyncio.run(find_all_listings(rows, concurrency=concurrency))
    elapsed = time.monotonic() - started

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        writer.writerows(results)

    total = len(results)
    with_url = sum(1 for r in results if r["listing_url"])
    items_ok = sum(1 for r in results if r["items_detected"] >= ITEMS_THRESHOLD)
    needs_review = sum(1 for r in results if r["needs_manual_review"])

    logger.success("Gravados {} em {} ({:.1f}s)", total, output, elapsed)
    logger.info("=== Resumo ===")
    logger.info("Total sites:                 {}", total)
    logger.info("Listing URL encontrada:      {}  ({:.1%})", with_url, with_url / max(total, 1))
    logger.info(
        "Validação OK (>={} items): {}  ({:.1%})",
        ITEMS_THRESHOLD,
        items_ok,
        items_ok / max(total, 1),
    )
    logger.info(
        "Needs manual review:         {}  ({:.1%})", needs_review, needs_review / max(total, 1)
    )


if __name__ == "__main__":
    app()
