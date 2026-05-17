"""Tiny wrapper: run detect_providers.main() against the *_v2 artefacts
without modifying scripts/detect_providers.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.detect_providers as dp  # noqa: E402

dp.CSV_IN = ROOT / "data" / "intermediate" / "site_analysis_v2.csv"
dp.CSV_OUT = ROOT / "data" / "intermediate" / "site_providers_v2.csv"
dp.MD_OUT = ROOT / "reports" / "providers_v2.md"

if __name__ == "__main__":
    sys.exit(dp.main())
