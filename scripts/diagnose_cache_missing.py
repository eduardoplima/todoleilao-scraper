"""One-shot diagnostic: cross site_analysis_v2 × site_providers_v2 to figure
out why some rows ended with provider=cache_missing.

For each missing row, check whether the expected files exist on disk under
the canonical sha1-derived names. Then bucket by root cause.

Usage:
    python scripts/diagnose_cache_missing.py
"""
from __future__ import annotations

import csv
import hashlib
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_CSV = ROOT / "data" / "intermediate" / "site_analysis_v2.csv"
PROVIDERS_CSV = ROOT / "data" / "intermediate" / "site_providers_v2.csv"
CACHE_DIR = ROOT / "data" / "intermediate" / "cache" / "sites"


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def main() -> int:
    # Load providers, keep cache_missing rows; some slugs are empty in the
    # innlei feed, so dedupe by (slug, nome, final_url) tuple to match against
    # analysis rows reliably.
    missing_keys: set[tuple[str, str, str]] = set()
    with PROVIDERS_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["provider"] == "cache_missing":
                missing_keys.add((r.get("slug", ""), r.get("nome", ""),
                                  r.get("final_url", "")))
    print(f"providers v2 cache_missing rows: {len(missing_keys)}")

    # Load analysis rows for those slugs
    rows: list[dict] = []
    with ANALYSIS_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = (r.get("slug", ""), r.get("nome", ""), r.get("final_url", ""))
            if key in missing_keys:
                rows.append(r)
    print(f"analysis v2 rows matched: {len(rows)}")

    bucket_counts: Counter[str] = Counter()
    examples: dict[str, list[dict]] = {}
    samples: list[dict] = []

    for r in rows:
        slug = r["slug"]
        dominio = (r.get("dominio") or "").strip()
        final_url = (r.get("final_url") or "").strip()
        screenshot_path = (r.get("screenshot_path") or "").strip()
        http_status = (r.get("http_status") or "").strip()
        error = (r.get("error") or "").strip()

        # Derive expected sha1-paths based on dominio
        sha_dom = sha1(dominio) if dominio else ""
        sha_final = sha1(final_url) if final_url else ""

        static_dom = CACHE_DIR / f"{sha_dom}.static.html" if sha_dom else None
        dynamic_dom = CACHE_DIR / f"{sha_dom}.dynamic.html" if sha_dom else None
        png_dom = CACHE_DIR / f"{sha_dom}.png" if sha_dom else None
        meta_dom = CACHE_DIR / f"{sha_dom}.meta.json" if sha_dom else None

        static_final = CACHE_DIR / f"{sha_final}.static.html" if sha_final else None
        dynamic_final = CACHE_DIR / f"{sha_final}.dynamic.html" if sha_final else None

        # Path that detect_providers.html_paths_for() would resolve
        if screenshot_path:
            base = ROOT / screenshot_path
            static_resolved = base.with_suffix("").with_suffix(".static.html")
            dynamic_resolved = base.with_suffix("").with_suffix(".dynamic.html")
            resolved_exists = static_resolved.exists() or dynamic_resolved.exists()
        else:
            static_resolved = None
            dynamic_resolved = None
            resolved_exists = False

        static_dom_exists = bool(static_dom and static_dom.exists())
        dynamic_dom_exists = bool(dynamic_dom and dynamic_dom.exists())
        png_dom_exists = bool(png_dom and png_dom.exists())
        meta_dom_exists = bool(meta_dom and meta_dom.exists())
        static_final_exists = bool(static_final and static_final.exists())
        dynamic_final_exists = bool(dynamic_final and dynamic_final.exists())

        # Categorize
        http_int = int(http_status) if http_status.isdigit() else 0
        if error and not static_dom_exists and not dynamic_dom_exists:
            if http_int and http_int >= 400:
                bucket = "http_error_status"
            elif "httpx" in error and "pw=" in error:
                bucket = "both_fetches_failed"
            elif "httpx" in error and not error.startswith("pw"):
                bucket = "httpx_fail_only_no_pw_html"
            elif error.startswith("pw") and "httpx" not in error:
                bucket = "pw_fail_only_no_httpx_html"
            else:
                bucket = f"error:{error[:60]}"
        elif not screenshot_path and (static_dom_exists or dynamic_dom_exists):
            # HTML exists on disk but screenshot_path empty -> detect_providers blind
            bucket = "html_exists_but_screenshot_path_empty"
        elif screenshot_path and not resolved_exists and (static_dom_exists or dynamic_dom_exists):
            bucket = "html_exists_but_resolved_path_mismatch"
        elif not (static_dom_exists or dynamic_dom_exists):
            if not error:
                bucket = "no_error_but_no_html_saved"
            else:
                bucket = f"silent_skip:{error[:60]}"
        else:
            bucket = "other"

        bucket_counts[bucket] += 1
        examples.setdefault(bucket, []).append({
            "slug": slug,
            "dominio": dominio,
            "final_url": final_url,
            "http_status": http_status,
            "error": error,
            "screenshot_path": screenshot_path,
            "static_dom_exists": static_dom_exists,
            "dynamic_dom_exists": dynamic_dom_exists,
            "png_dom_exists": png_dom_exists,
            "meta_dom_exists": meta_dom_exists,
            "static_final_exists": static_final_exists,
            "dynamic_final_exists": dynamic_final_exists,
            "resolved_static": str(static_resolved) if static_resolved else "",
            "resolved_dynamic": str(dynamic_resolved) if dynamic_resolved else "",
        })

    print("\n=== Buckets ===")
    for bucket, n in bucket_counts.most_common():
        print(f"  {bucket}: {n}")

    print("\n=== Examples per bucket (up to 3 each) ===")
    for bucket in bucket_counts:
        print(f"\n[{bucket}]  total={bucket_counts[bucket]}")
        for ex in examples[bucket][:3]:
            print(f"  slug={ex['slug']}")
            print(f"    dominio={ex['dominio']}")
            print(f"    final_url={ex['final_url']}")
            print(f"    http_status={ex['http_status']}  error={ex['error']}")
            print(f"    screenshot_path={ex['screenshot_path'] or '<empty>'}")
            print(f"    static_dom_exists={ex['static_dom_exists']}  "
                  f"dynamic_dom_exists={ex['dynamic_dom_exists']}  "
                  f"png_dom_exists={ex['png_dom_exists']}  "
                  f"meta_dom_exists={ex['meta_dom_exists']}")
            print(f"    static_final_exists={ex['static_final_exists']}  "
                  f"dynamic_final_exists={ex['dynamic_final_exists']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
