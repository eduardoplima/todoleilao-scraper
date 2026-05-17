"""Repair pass for rows in site_analysis_v2.csv that ended up with
provider=cache_missing because their `dominio` was stored without an
``http(s)://`` scheme. httpx raised ``UnsupportedProtocol`` / ``ValueError``,
Playwright raised a generic ``Error``, and no HTML ever hit disk.

This script:

  1. Reads ``data/intermediate/site_analysis_v2.csv``.
  2. For every row where the dominio lacks a scheme AND an HTML cache miss
     exists, re-fetches with ``https://`` prepended (falling back to
     ``http://`` if needed) using httpx + the Chrome UA from the spiders.
  3. On 2xx + html content-type, writes the static HTML/meta into
     ``data/intermediate/cache/sites/<sha1(new_url)>.{static.html,meta.json}``,
     identical to what site_analyzer would have done.
  4. Updates the row in-place with the new dominio, final_url, http_status,
     basic tech_* fields, html_title/meta_generator, link counts, rendering
     defaults (``static``) and ``screenshot_path`` (even though no PNG was
     taken — detect_providers only uses the path string to derive html files).
  5. Writes the patched CSV back to ``site_analysis_v2.csv`` (overwrite).

This is a one-shot cleanup; production code in ``site_analyzer.py`` is
untouched. Run with ``--only-slug rodolfo-da-rosa-schontag`` to repair just
the one example from the task description, or no flag to fix all 90.

Idempotent: if html cache already exists for a row, the script skips it.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from discovery._common_ua import BROWSER_USER_AGENT  # noqa: E402
from discovery.site_analyzer import (  # noqa: E402
    ANALYSIS_COLUMNS,
    count_links,
    detect_tech,
    determine_rendering,
    extract_title_and_generator,
    requires_js_for_listings,
)

ANALYSIS_CSV = ROOT / "data" / "intermediate" / "site_analysis_v2.csv"
CACHE_DIR = ROOT / "data" / "intermediate" / "cache" / "sites"
HTTPX_TIMEOUT = 20.0


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def has_scheme(s: str) -> bool:
    return s.lower().startswith(("http://", "https://"))


def fetch_one(url: str) -> dict[str, Any]:
    headers = {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    out: dict[str, Any] = {
        "html": "",
        "http_status": "",
        "final_url": "",
        "headers": {},
        "error": "",
    }
    try:
        r = httpx.get(
            url,
            timeout=HTTPX_TIMEOUT,
            follow_redirects=True,
            headers=headers,
            verify=False,  # some leiloeiro sites have stale chains
        )
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
    except Exception as e:
        out["error"] = f"httpx:{type(e).__name__}"
    return out


def candidate_urls(raw_dominio: str) -> list[str]:
    base = raw_dominio.strip().lstrip("/")
    if has_scheme(base):
        return [base]
    return [f"https://{base}", f"http://{base}"]


def write_cache(url: str, static_html: str, meta: dict[str, Any]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = sha1(url)
    (CACHE_DIR / f"{key}.static.html").write_text(
        static_html, encoding="utf-8", errors="replace"
    )
    (CACHE_DIR / f"{key}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return CACHE_DIR / f"{key}.png"  # path even if no PNG; detect_providers only uses string


def patch_row(row: dict[str, str], dry_run: bool = False) -> tuple[bool, str]:
    """Returns (patched, note)."""
    dom = (row.get("dominio") or "").strip()
    if has_scheme(dom):
        return False, "scheme already present"

    for url in candidate_urls(dom):
        result = fetch_one(url)
        if result["html"]:
            break
    else:  # nobreak: all candidates failed
        return False, f"all fetches failed: {result['error']}"

    final_url = result["final_url"] or url
    static_html = result["html"]
    static_total, static_useful = count_links(static_html)
    techs, sigs = detect_tech(static_html, "", result.get("headers") or {}, final_url)
    title, generator = extract_title_and_generator(static_html)
    rendering = determine_rendering(static_useful, 0)
    req_js = requires_js_for_listings(static_useful, 0)

    screenshot_rel = (
        f"data/intermediate/cache/sites/{sha1(url)}.png"
    )

    new_row = dict(row)
    new_row.update(
        {
            "dominio": url,
            "http_status": str(result["http_status"]),
            "final_url": final_url,
            "error": "",
            "tech_stack": "; ".join(techs),
            "tech_signals": " | ".join(sigs) + (" | repatched=cache_missing_fix"
                                                if sigs else "repatched=cache_missing_fix"),
            "static_link_count": str(static_total),
            "dynamic_link_count": "0",
            "static_useful_links": str(static_useful),
            "dynamic_useful_links": "0",
            "rendering": rendering,
            "requires_js_for_listings": "True" if req_js else "False",
            "html_title": title,
            "html_meta_generator": generator,
            "screenshot_path": screenshot_rel,
        }
    )
    row.update(new_row)

    if not dry_run:
        # meta json mirrors what site_analyzer would write (a subset of the row).
        meta = {k: new_row.get(k, "") for k in ANALYSIS_COLUMNS}
        write_cache(url, static_html, meta)
    return True, f"ok http={result['http_status']} final={final_url}"


def main() -> int:
    only_slug = None
    for i, a in enumerate(sys.argv[1:]):
        if a == "--only-slug" and i + 2 <= len(sys.argv) - 1:
            only_slug = sys.argv[i + 2]

    with ANALYSIS_CSV.open(encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
        fieldnames = (next(csv.reader(open(ANALYSIS_CSV, encoding="utf-8")))) if False else None

    fieldnames = ANALYSIS_COLUMNS

    targets = []
    for r in all_rows:
        if only_slug and r.get("slug") != only_slug:
            continue
        dom = (r.get("dominio") or "").strip()
        if dom and not has_scheme(dom):
            targets.append(r)

    print(f"will attempt to patch {len(targets)} rows "
          f"(only_slug={only_slug or '<all>'})")

    fixed = 0
    failed = 0
    for r in targets:
        ok, note = patch_row(r)
        if ok:
            fixed += 1
            print(f"  [OK]   slug={r.get('slug') or '<empty>'} dom={r['dominio']}  {note}")
        else:
            failed += 1
            print(f"  [FAIL] dom={(r.get('dominio') or '')}  {note}")
        time.sleep(0.5)  # polite

    if fixed:
        with ANALYSIS_CSV.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(all_rows)
        print(f"\nrewrote {ANALYSIS_CSV} with {fixed} patched rows ({failed} failed)")
    else:
        print("nothing to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
