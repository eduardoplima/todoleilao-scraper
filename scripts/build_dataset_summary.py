"""Gera reports/dataset_summary.md a partir do `properties.parquet` consolidado.

Inclui:
  - Total por leiloeiro (com source_file count e first/last scrape).
  - Distribuição por estado, tipo, faixa de preço.
  - % de campos preenchidos por coluna (data quality).
  - Top 10 gaps de qualidade — colunas mais subdocumentadas, ordenadas por
    "impacto = (1 - fill_rate) * weight".
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import typer
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARQUET_PATH = PROJECT_ROOT / "data" / "processed" / "properties.parquet"
REPORT_PATH = PROJECT_ROOT / "reports" / "dataset_summary.md"

# Pesos para cálculo do "impact" — campos críticos pesam mais.
COLUMN_WEIGHTS = {
    "url": 10, "auctioneer": 10, "title": 8,
    "minimum_bid": 8, "market_value": 7, "discount_pct": 6,
    "property_type": 7, "address": 7,
    "first_auction_date": 5, "second_auction_date": 3,
    "area_sqm": 4, "total_area_sqm": 4,
    "bedrooms": 3, "bathrooms": 3, "parking_spots": 2,
    "images": 4, "documents": 2, "description": 5,
    "auction_phase": 4, "status": 3,
    "scraped_at": 2, "source_listing_url": 2,
    "raw_html_snapshot": 0,
}

PRICE_BUCKETS = [
    (0, 50_000, "≤ 50k"),
    (50_000, 150_000, "50k–150k"),
    (150_000, 300_000, "150k–300k"),
    (300_000, 600_000, "300k–600k"),
    (600_000, 1_500_000, "600k–1,5M"),
    (1_500_000, float("inf"), "> 1,5M"),
]


def _fill_rate(series: pd.Series) -> float:
    """% de células com valor non-null/non-empty."""
    if series.dtype == object:
        non_empty = series.notna() & series.astype(str).str.strip().ne("") & series.astype(str).str.strip().ne("[]") & series.astype(str).str.strip().ne("{}")
        return non_empty.mean()
    return series.notna().mean()


def _md_table(rows: list[list], headers: list[str], align: list[str] | None = None) -> str:
    align = align or [":---" for _ in headers]
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join(align) + "|")
    for r in rows:
        lines.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(lines)


def build(parquet: Path) -> str:
    df = pd.read_parquet(parquet)
    logger.info("Carregado: {} linhas, {} cols", len(df), len(df.columns))

    out: list[str] = []
    out.append("# Dataset summary — `data/processed/properties.parquet`")
    out.append("")
    out.append(f"Snapshot do consolidado de **{len(df)}** imóveis raspados pelos {df['auctioneer'].nunique() if 'auctioneer' in df.columns else 0} leiloeiros ativos no `scripts/run_all.py`. Atualizar com `uv run python -m scripts.build_dataset_summary`.")
    out.append("")
    out.append("## Total por leiloeiro")
    out.append("")
    if "auctioneer" in df.columns:
        per_auct = df.groupby("auctioneer").size().sort_values(ascending=False).rename("itens")
        rows = [[a, n] for a, n in per_auct.items()]
        out.append(_md_table(rows, ["leiloeiro", "itens"], [":---", "---:"]))
    out.append("")

    # ---- distribuições ----
    out.append("## Distribuição por estado")
    out.append("")
    if "address" in df.columns:
        states = df["address"].dropna().apply(_extract_state).dropna()
        if len(states):
            top = states.value_counts().sort_values(ascending=False)
            rows = [[uf, n, f"{n / len(df):.1%}"] for uf, n in top.items()]
            out.append(_md_table(rows, ["UF", "itens", "%"], [":---", "---:", "---:"]))
    out.append("")

    out.append("## Distribuição por tipo de imóvel")
    out.append("")
    if "property_type" in df.columns:
        ptype_counts = df["property_type"].fillna("(none)").value_counts()
        rows = [[t, n, f"{n / len(df):.1%}"] for t, n in ptype_counts.items()]
        out.append(_md_table(rows, ["property_type", "itens", "%"], [":---", "---:", "---:"]))
    out.append("")

    out.append("## Distribuição por faixa de preço (`minimum_bid`)")
    out.append("")
    if "minimum_bid" in df.columns:
        prices = pd.to_numeric(df["minimum_bid"], errors="coerce").dropna()
        rows = []
        for lo, hi, label in PRICE_BUCKETS:
            mask = (prices >= lo) & (prices < hi)
            n = int(mask.sum())
            pct = n / len(df) if len(df) else 0
            rows.append([label, n, f"{pct:.1%}"])
        rows.append(["(sem preço)", int(prices.isna().sum() + (len(df) - len(prices))), "—"])
        out.append(_md_table(rows, ["faixa", "itens", "% do total"], [":---", "---:", "---:"]))
        out.append("")
        out.append(f"_Estatísticas:_ mín = R$ {prices.min():,.2f}, mediana = R$ {prices.median():,.2f}, "
                   f"média = R$ {prices.mean():,.2f}, máx = R$ {prices.max():,.2f}.")
    out.append("")

    # ---- data quality ----
    out.append("## Data quality — % preenchimento por coluna")
    out.append("")
    quality_rows = []
    for col in df.columns:
        if col.startswith("__"):
            continue
        rate = _fill_rate(df[col])
        quality_rows.append((col, rate))
    quality_rows.sort(key=lambda x: -x[1])
    rows = [[c, f"{r:.1%}"] for c, r in quality_rows]
    out.append(_md_table(rows, ["coluna", "fill rate"], [":---", "---:"]))
    out.append("")

    # ---- gaps ----
    out.append("## Top 10 gaps de qualidade")
    out.append("")
    out.append("Score = `(1 - fill_rate) × weight`. Weight reflete importância no schema canônico do CLAUDE.md.")
    out.append("")
    gaps = []
    for col, rate in quality_rows:
        weight = COLUMN_WEIGHTS.get(col, 1)
        impact = round((1 - rate) * weight, 2)
        if impact > 0:
            gaps.append([col, f"{rate:.1%}", weight, impact])
    gaps.sort(key=lambda r: -r[3])
    out.append(_md_table(gaps[:10], ["coluna", "fill rate", "weight", "impact"], [":---", "---:", "---:", "---:"]))
    out.append("")

    out.append("### Onde mexer primeiro")
    out.append("")
    if gaps:
        for g in gaps[:5]:
            out.append(f"- **`{g[0]}`** ({g[1]} preenchido) — impact {g[3]}.")
    out.append("")

    return "\n".join(out)


def _extract_state(addr: str) -> str | None:
    """address vem serializado como JSON string ou dict."""
    import json as _json
    if isinstance(addr, dict):
        return addr.get("state") or None
    if isinstance(addr, str) and addr.strip().startswith("{"):
        try:
            return _json.loads(addr).get("state") or None
        except Exception:
            return None
    return None


app = typer.Typer(help="Gera reports/dataset_summary.md")


@app.callback()
def _main() -> None: pass


@app.command()
def run(
    parquet: Path = typer.Option(PARQUET_PATH, "--parquet"),
    output: Path = typer.Option(REPORT_PATH, "--output"),
) -> None:
    md = build(parquet)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(md, encoding="utf-8")
    logger.success("→ {} ({} bytes)", output, len(md))


if __name__ == "__main__":
    app()
