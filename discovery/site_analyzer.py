"""Fase 4 — análise dos sites externos dos candidatos a leilão de imóveis.

Para cada leiloeiro classificado como high/medium pelo filter_real_estate,
faz duas coletas do mesmo site e compara:

  - **estática** via httpx (HTML como o servidor entrega)
  - **dinâmica** via Playwright headless (HTML após JS rodar)

A diferença em "links úteis" (anchors com keywords de imóveis/leilão no path)
é o que decide se o site é static / dynamic / hybrid e se a listagem
precisa de JS para aparecer.

Detecção de stack: meta generator + presença de paths conhecidos
(wp-content, /_next/, leilao.br, etc.). Saída em
data/intermediate/site_analysis.csv. Cache de HTML e screenshot em
data/intermediate/cache/sites/.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
import typer
from bs4 import BeautifulSoup
from loguru import logger
from playwright.async_api import (
    Browser,
    async_playwright,
)
from playwright.async_api import (
    TimeoutError as PWTimeoutError,
)

CACHE_DIR = Path("data/intermediate/cache/sites")
USER_AGENT = "TodoLeilaoBot/0.1 (+contato: eplima.cc@gmail.com)"
HTTPX_TIMEOUT = 20.0
PLAYWRIGHT_TIMEOUT_MS = 30_000
DEFAULT_CONCURRENCY = 3
SCREENSHOT_VIEWPORT = {"width": 1280, "height": 800}

USEFUL_PATH_KEYWORDS = (
    "imovel",
    "imoveis",
    "lote",
    "leilao",
    "leiloes",
    "praca",
    "edital",
    "ficha",
    "matricula",
    "produto",
)

ANALYSIS_COLUMNS = [
    "id",
    "slug",
    "nome",
    "uf",
    "cidade",
    "dominio",
    "confidence",
    "real_estate_score",
    "http_status",
    "final_url",
    "error",
    "tech_stack",
    "tech_signals",
    "static_link_count",
    "dynamic_link_count",
    "static_useful_links",
    "dynamic_useful_links",
    "rendering",
    "requires_js_for_listings",
    "html_title",
    "html_meta_generator",
    "screenshot_path",
]


# ---------- cache ---------------------------------------------------------


def _key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _meta_path(url: str) -> Path:
    return CACHE_DIR / f"{_key(url)}.meta.json"


def _static_html_path(url: str) -> Path:
    return CACHE_DIR / f"{_key(url)}.static.html"


def _dynamic_html_path(url: str) -> Path:
    return CACHE_DIR / f"{_key(url)}.dynamic.html"


def _screenshot_path(url: str) -> Path:
    return CACHE_DIR / f"{_key(url)}.png"


def _read_cache(url: str) -> dict[str, Any] | None:
    p = _meta_path(url)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(
    url: str,
    meta: dict[str, Any],
    static_html: str,
    dynamic_html: str,
    screenshot_bytes: bytes | None,
) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _meta_path(url).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if static_html:
        _static_html_path(url).write_text(static_html, encoding="utf-8", errors="replace")
    if dynamic_html:
        _dynamic_html_path(url).write_text(dynamic_html, encoding="utf-8", errors="replace")
    if screenshot_bytes:
        _screenshot_path(url).write_bytes(screenshot_bytes)


# ---------- analysis primitives -------------------------------------------


def count_links(html: str) -> tuple[int, int]:
    """Retorna (total, useful). Ignora javascript:/mailto:/tel:/fragmentos."""
    if not html:
        return 0, 0
    soup = BeautifulSoup(html, "lxml")
    total = 0
    useful = 0
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        href_low = href.lower()
        if href_low.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        total += 1
        if any(kw in href_low for kw in USEFUL_PATH_KEYWORDS):
            useful += 1
    return total, useful


def determine_rendering(static_useful: int, dynamic_useful: int) -> str:
    """Classifica em static/dynamic/hybrid/unknown a partir de useful link counts.

    - static: dynamic ≤ static (JS não adiciona listagens)
    - dynamic: dynamic ≥ 1.5×static AND dynamic - static ≥ 3
    - hybrid: dynamic > static mas abaixo do limite de "dynamic"
    - unknown: ambos zero (impossível decidir)
    """
    if dynamic_useful == 0 and static_useful == 0:
        return "unknown"
    if dynamic_useful <= static_useful:
        return "static"
    diff = dynamic_useful - static_useful
    ratio = dynamic_useful / max(static_useful, 1)
    if ratio >= 1.5 and diff >= 3:
        return "dynamic"
    if ratio >= 1.1 or diff >= 2:
        return "hybrid"
    return "static"


def requires_js_for_listings(static_useful: int, dynamic_useful: int) -> bool:
    """True se a listagem só aparece após JS.

    - static==0 e dynamic>0  → claramente precisa de JS
    - dynamic >> static (static < 30% do dynamic) com volume mínimo → idem
    """
    if dynamic_useful == 0:
        return False
    if static_useful == 0 and dynamic_useful > 0:
        return True
    if dynamic_useful >= 5 and static_useful < dynamic_useful * 0.3:
        return True
    return False


_META_GEN_RE = re.compile(
    r'<meta\s+[^>]*name=["\']generator["\'][^>]*content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE | re.DOTALL)


def extract_title_and_generator(html: str) -> tuple[str, str]:
    if not html:
        return "", ""
    title = ""
    m = _TITLE_RE.search(html)
    if m:
        title = " ".join(m.group(1).split())[:200]
    gen = ""
    m = _META_GEN_RE.search(html)
    if m:
        gen = m.group(1).strip()[:120]
    return title, gen


def detect_tech(
    static_html: str,
    dynamic_html: str,
    headers: dict[str, str],
    final_url: str,
) -> tuple[list[str], list[str]]:
    """Detecta stack a partir de meta generator + paths/atributos típicos + headers.

    Retorna (techs_dedupadas, sinais).
    """
    haystack = (static_html or "") + "\n" + (dynamic_html or "")
    haystack_low = haystack.lower()
    techs: list[str] = []
    signals: list[str] = []

    def add(label: str, signal: str) -> None:
        if label not in techs:
            techs.append(label)
        signals.append(signal)

    # meta generator
    m = _META_GEN_RE.search(haystack)
    if m:
        gen = m.group(1).strip()
        gen_low = gen.lower()
        signals.append(f"generator={gen[:60]}")
        if "wordpress" in gen_low:
            add("WordPress", f"generator={gen[:40]}")
        elif "wix" in gen_low:
            add("Wix", f"generator={gen[:40]}")
        elif "squarespace" in gen_low:
            add("Squarespace", f"generator={gen[:40]}")
        elif "joomla" in gen_low:
            add("Joomla", f"generator={gen[:40]}")
        elif "drupal" in gen_low:
            add("Drupal", f"generator={gen[:40]}")
        elif "shopify" in gen_low:
            add("Shopify", f"generator={gen[:40]}")
        elif "elementor" in gen_low:
            add("Elementor", f"generator={gen[:40]}")

    # WordPress paths
    if "wp-content/" in haystack_low or "wp-includes/" in haystack_low:
        add("WordPress", "wp-content/wp-includes")

    # JS frameworks
    if (
        "/_next/" in haystack_low
        or "__next_data__" in haystack_low
        or "self.__next_f" in haystack_low
    ):
        add("Next.js", "/_next/ or __NEXT_DATA__")
    if "/_nuxt/" in haystack_low or "window.__nuxt__" in haystack_low:
        add("Nuxt", "/_nuxt/ or __NUXT__")
    if "data-reactroot" in haystack_low or "react-dom" in haystack_low or "_react_" in haystack_low:
        add("React", "data-reactroot/react-dom")
    if "vue.js" in haystack_low or "v-cloak" in haystack_low or "data-v-" in haystack_low:
        add("Vue", "vue.js/v-cloak/data-v-")
    if "ng-app" in haystack_low or "ng-controller" in haystack_low or "ng-version" in haystack_low:
        add("Angular", "ng-app/ng-controller")
    if "jquery" in haystack_low:
        add("jQuery", "jquery")
    if "bootstrap" in haystack_low:
        add("Bootstrap", "bootstrap")

    # plataformas brasileiras de leilão
    final_low = (final_url or "").lower()
    if ".leilao.br" in final_low or ".leilao.br" in haystack_low:
        add("leilao.br platform", "leilao.br")
    if "sodresantoro" in haystack_low:
        add("Sodré Santoro", "sodresantoro")
    if "megaleiloes" in haystack_low:
        add("Mega Leilões", "megaleiloes")
    if "leilovip" in haystack_low:
        add("LeilôVIP", "leilovip")
    if "biddo" in haystack_low:
        add("Biddo", "biddo")
    if "superbid" in haystack_low:
        add("Superbid", "superbid")
    if "leilo " in haystack_low or "/leilo-" in haystack_low or "leilo.com" in haystack_low:
        signals.append("contains 'leilo'")

    # CDN/server
    server = (headers.get("server") or "").lower() if headers else ""
    if "cloudflare" in server:
        signals.append("server:cloudflare")
    if "nginx" in server:
        signals.append("server:nginx")
    if "apache" in server:
        signals.append("server:apache")

    return techs, signals[:12]


# ---------- single-site analyzer ------------------------------------------


async def _httpx_fetch(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "html": "",
        "http_status": "",
        "final_url": "",
        "headers": {},
        "error": "",
    }
    try:
        r = await client.get(url, timeout=HTTPX_TIMEOUT, follow_redirects=True)
        out["http_status"] = r.status_code
        out["final_url"] = str(r.url)
        out["headers"] = {k.lower(): v for k, v in r.headers.items()}
        ct = (r.headers.get("content-type") or "").lower()
        if r.status_code >= 400:
            out["error"] = f"http_{r.status_code}"
        elif "html" not in ct:
            out["error"] = f"non_html:{ct.split(';')[0].strip()}"
        else:
            out["html"] = r.text
    except httpx.TimeoutException:
        out["error"] = "httpx_timeout"
    except httpx.ConnectError as e:
        out["error"] = f"httpx_connect:{type(e).__name__}"
    except Exception as e:  # SSL, decoding, etc.
        out["error"] = f"httpx:{type(e).__name__}"
    return out


async def _playwright_fetch(
    browser: Browser, url: str, timeout_ms: int = PLAYWRIGHT_TIMEOUT_MS
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "html": "",
        "final_url": "",
        "screenshot": None,
        "error": "",
    }
    context = await browser.new_context(
        user_agent=USER_AGENT,
        ignore_https_errors=True,
        viewport=SCREENSHOT_VIEWPORT,
        locale="pt-BR",
    )
    page = await context.new_page()
    try:
        try:
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except PWTimeoutError:
            # networkidle pode não acontecer em sites com long-polling/analytics;
            # tenta usar o que já carregou
            out["error"] = "pw_networkidle_timeout"
        out["html"] = await page.content()
        out["final_url"] = page.url
        try:
            out["screenshot"] = await page.screenshot(type="png", full_page=False, timeout=10_000)
        except Exception:
            pass
    except PWTimeoutError:
        out["error"] = "pw_timeout"
    except Exception as e:
        out["error"] = f"pw:{type(e).__name__}"
    finally:
        await context.close()
    return out


def _build_record(
    row: dict[str, Any],
    httpx_out: dict[str, Any],
    pw_out: dict[str, Any],
    screenshot_saved: bool,
) -> dict[str, Any]:
    static_html = httpx_out.get("html", "")
    dynamic_html = pw_out.get("html", "")

    static_total, static_useful = count_links(static_html)
    dynamic_total, dynamic_useful = count_links(dynamic_html)

    techs, sigs = detect_tech(
        static_html,
        dynamic_html,
        httpx_out.get("headers") or {},
        pw_out.get("final_url") or httpx_out.get("final_url") or "",
    )
    title, generator = extract_title_and_generator(dynamic_html or static_html)

    # error = "incapaz de analisar". Se pelo menos um dos dois fetches retornou
    # HTML (mesmo com warnings tipo pw_networkidle_timeout), o site É analisável
    # e error fica vazio. As notas finais sobre a coleta vão para tech_signals.
    err_parts = []
    notes = []
    if httpx_out.get("error"):
        (err_parts if not static_html else notes).append(f"httpx={httpx_out['error']}")
    if pw_out.get("error"):
        (err_parts if not dynamic_html else notes).append(f"pw={pw_out['error']}")
    error = (
        "; ".join(err_parts) if (not static_html and not dynamic_html) else ("; ".join(err_parts))
    )
    # se houve warnings durante a coleta, registramos junto dos sinais
    if notes:
        sigs = sigs + tuple(notes) if isinstance(sigs, tuple) else list(sigs) + notes

    rendering = determine_rendering(static_useful, dynamic_useful)
    req_js = requires_js_for_listings(static_useful, dynamic_useful)

    return {
        "id": row.get("id"),
        "slug": row.get("slug") or "",
        "nome": row.get("nome") or "",
        "uf": row.get("uf") or "",
        "cidade": row.get("cidade") or "",
        "dominio": row.get("dominio") or "",
        "confidence": row.get("confidence") or "",
        "real_estate_score": row.get("real_estate_score") or "",
        "http_status": httpx_out.get("http_status") or "",
        "final_url": pw_out.get("final_url") or httpx_out.get("final_url") or "",
        "error": error,
        "tech_stack": "; ".join(techs),
        "tech_signals": " | ".join(sigs),
        "static_link_count": static_total,
        "dynamic_link_count": dynamic_total,
        "static_useful_links": static_useful,
        "dynamic_useful_links": dynamic_useful,
        "rendering": rendering,
        "requires_js_for_listings": req_js,
        "html_title": title,
        "html_meta_generator": generator,
        "screenshot_path": (
            str(_screenshot_path(row.get("dominio") or "")) if screenshot_saved else ""
        ),
    }


async def analyze_one(
    row: dict[str, Any],
    *,
    http_client: httpx.AsyncClient,
    browser: Browser,
    semaphore: asyncio.Semaphore,
    use_cache: bool = True,
    timeout_ms: int = PLAYWRIGHT_TIMEOUT_MS,
) -> dict[str, Any]:
    url = (row.get("dominio") or "").strip()
    if not url:
        return _build_record(row, {"error": "no_domain"}, {}, screenshot_saved=False)

    if use_cache:
        cached = _read_cache(url)
        if cached is not None:
            cached["_cache_hit"] = True
            # garantir que campos do row estejam atualizados
            for k in ("id", "slug", "nome", "uf", "cidade", "confidence", "real_estate_score"):
                if k in row:
                    cached[k] = row[k]
            return cached

    async with semaphore:
        httpx_out = await _httpx_fetch(http_client, url)
        pw_out = await _playwright_fetch(browser, url, timeout_ms=timeout_ms)

    screenshot_bytes = pw_out.get("screenshot")
    screenshot_saved = bool(screenshot_bytes)
    record = _build_record(row, httpx_out, pw_out, screenshot_saved=screenshot_saved)

    _write_cache(
        url,
        meta=record,
        static_html=httpx_out.get("html", "") or "",
        dynamic_html=pw_out.get("html", "") or "",
        screenshot_bytes=screenshot_bytes,
    )
    record["_cache_hit"] = False
    return record


# ---------- runner --------------------------------------------------------


async def analyze_all(
    rows: list[dict[str, Any]],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    use_cache: bool = True,
    timeout_ms: int = PLAYWRIGHT_TIMEOUT_MS,
) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)
    results: list[dict[str, Any]] = []
    progress = {"done": 0, "cache": 0, "fail": 0}
    total = len(rows)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)

    async with httpx.AsyncClient(headers=headers, limits=limits) as http_client:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:

                async def worker(row: dict[str, Any]) -> dict[str, Any]:
                    record = await analyze_one(
                        row,
                        http_client=http_client,
                        browser=browser,
                        semaphore=sem,
                        use_cache=use_cache,
                        timeout_ms=timeout_ms,
                    )
                    progress["done"] += 1
                    if record.get("_cache_hit"):
                        progress["cache"] += 1
                    if record.get("error"):
                        progress["fail"] += 1
                    if progress["done"] % 10 == 0 or progress["done"] == total:
                        logger.info(
                            "Progresso {}/{}  cache_hits={}  errors={}",
                            progress["done"],
                            total,
                            progress["cache"],
                            progress["fail"],
                        )
                    return record

                tasks = [worker(r) for r in rows]
                for completed in asyncio.as_completed(tasks):
                    results.append(await completed)
            finally:
                await browser.close()

    return results


def write_csv(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=ANALYSIS_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ---------- CLI -----------------------------------------------------------

app = typer.Typer(help="Analisa sites externos: tech stack, rendering, requires_js.")


@app.callback()
def _main() -> None:
    """Força Typer a tratar `run` como subcomando explícito."""


@app.command()
def run(
    input_csv: Path = typer.Option(
        Path("data/intermediate/auctioneers_real_estate.csv"),
        "--input",
        "-i",
    ),
    output: Path = typer.Option(
        Path("data/intermediate/site_analysis.csv"),
        "--output",
        "-o",
    ),
    concurrency: int = typer.Option(DEFAULT_CONCURRENCY, "--concurrency", "-c", min=1, max=10),
    timeout_ms: int = typer.Option(PLAYWRIGHT_TIMEOUT_MS, "--timeout-ms"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    only: str = typer.Option(
        "high,medium",
        "--only",
        help="Filtra confidence (csv): só linhas com confidence ∈ {only}.",
    ),
    limit: int = typer.Option(0, "--limit", help="Para debugging — analisa só N sites."),
) -> None:
    """Analisa cada candidato (high/medium) com httpx + Playwright."""
    confidences = {c.strip() for c in only.split(",") if c.strip()}
    with input_csv.open(encoding="utf-8") as fh:
        all_rows = list(csv.DictReader(fh))

    rows = [
        r
        for r in all_rows
        if r.get("confidence") in confidences and (r.get("dominio") or "").strip()
    ]
    if limit > 0:
        rows = rows[:limit]
    logger.info(
        "Analisando {} sites (confidence in {}, com domínio, limit={}, concurrency={})",
        len(rows),
        confidences,
        limit or "∞",
        concurrency,
    )

    started = time.monotonic()
    results = asyncio.run(
        analyze_all(rows, concurrency=concurrency, use_cache=not no_cache, timeout_ms=timeout_ms)
    )
    elapsed = time.monotonic() - started

    write_csv(results, output)

    rendering_dist: dict[str, int] = {}
    js_dist = {True: 0, False: 0}
    err_count = 0
    for r in results:
        rendering_dist[r["rendering"]] = rendering_dist.get(r["rendering"], 0) + 1
        js_dist[bool(r["requires_js_for_listings"])] += 1
        if r.get("error"):
            err_count += 1

    logger.success("Gravados {} sites em {} ({:.1f}s)", len(results), output, elapsed)
    logger.info("=== Distribuição de rendering ===")
    for k, v in sorted(rendering_dist.items(), key=lambda kv: -kv[1]):
        logger.info("  {:8s} {}", k, v)
    logger.info("requires_js_for_listings: True={} False={}", js_dist[True], js_dist[False])
    logger.info("Sites com error não vazio: {}", err_count)


if __name__ == "__main__":
    app()
