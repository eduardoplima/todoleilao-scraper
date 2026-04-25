"""Gera reports/site_analysis.md consolidando os artefatos das fases 1-5.

Lê site_analysis.csv + listing_urls.csv, gera um gráfico matplotlib em
reports/figures/rendering_distribution.png e um markdown com:

  - Resumo (counts / percents)
  - Agrupamento por rendering
  - Top 10 com mais items
  - Lista de sites para revisão manual
  - Recomendação de ordem de implementação dos spiders
  - Tabela completa em <details>

Reroda quando os CSVs mudam.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import pandas as pd
import typer
from loguru import logger

REPORTS_DIR = Path("reports")
FIGURES_DIR = REPORTS_DIR / "figures"

RENDERING_COLORS = {
    "static": "#3aa657",
    "hybrid": "#f0a531",
    "dynamic": "#d8523f",
    "unknown": "#9e9e9e",
}


def load_data(
    site_analysis: Path, listing_urls: Path
) -> pd.DataFrame:
    sa = pd.read_csv(site_analysis)
    lf = pd.read_csv(listing_urls)

    # Merge por `id` quando disponível (chave primária do INNLEI). CSVs antigos
    # do listing_finder (sem `id`) caem num fallback posicional baseado na
    # premissa de que asyncio.gather preserva ordem dos inputs.
    if "id" in lf.columns:
        df = sa.merge(
            lf[["id", "listing_url", "items_detected", "sample_item_url", "needs_manual_review"]],
            on="id",
            how="left",
        )
    else:
        sa_acc = sa[sa["error"].fillna("").str.strip() == ""].reset_index(drop=True)
        sa_err = sa[sa["error"].fillna("").str.strip() != ""].reset_index(drop=True)
        assert len(sa_acc) == len(lf), (
            f"Tamanhos divergentes: site_analysis acessíveis={len(sa_acc)}, "
            f"listing_urls={len(lf)} — não dá para fazer merge posicional."
        )
        sa_acc = pd.concat(
            [
                sa_acc,
                lf[["listing_url", "items_detected", "sample_item_url", "needs_manual_review"]]
                .reset_index(drop=True),
            ],
            axis=1,
        )
        df = pd.concat([sa_acc, sa_err], ignore_index=True)

    df["items_detected"] = df["items_detected"].fillna(0).astype(int)
    df["needs_manual_review"] = (
        df["needs_manual_review"].fillna("True").astype(str).str.lower() == "true"
    )
    df["rendering"] = df["rendering"].fillna("unknown")
    return df


def render_chart(df: pd.DataFrame, output: Path) -> None:
    counts = (
        df["rendering"]
        .value_counts()
        .reindex(["static", "hybrid", "dynamic", "unknown"], fill_value=0)
    )
    colors = [RENDERING_COLORS[k] for k in counts.index]
    total = int(counts.sum())

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=130)
    bars = ax.bar(counts.index, counts.values, color=colors, edgecolor="white", width=0.6)
    for rect, value in zip(bars, counts.values):
        pct = value / total * 100 if total else 0
        ax.text(
            rect.get_x() + rect.get_width() / 2,
            rect.get_height() + total * 0.01,
            f"{value} ({pct:.1f}%)",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )
    ax.set_title(
        f"Rendering dos sites de leiloeiros candidatos a imóveis (n={total})",
        fontsize=12,
    )
    ax.set_ylabel("número de sites")
    ax.set_ylim(0, max(counts.values) * 1.15 if max(counts.values) > 0 else 1)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="x", labelsize=11)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def _md_row(values: list[str]) -> str:
    safe = []
    for v in values:
        s = "" if v is None else str(v)
        s = s.replace("|", "\\|").replace("\n", " ").strip()
        safe.append(s)
    return "| " + " | ".join(safe) + " |"


def _truncate(s: str, n: int) -> str:
    s = "" if s is None else str(s)
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def build_markdown(df: pd.DataFrame, chart_path: Path) -> str:
    total = len(df)
    by_rendering = df["rendering"].value_counts().to_dict()
    accessible = (df["error"].fillna("").str.strip() == "").sum()
    with_listing = (df["listing_url"].fillna("").astype(str).str.strip() != "").sum()
    items_ok = (df["items_detected"] >= 5).sum()
    needs_review = df["needs_manual_review"].sum()
    requires_js = (df["requires_js_for_listings"].astype(str).str.lower() == "true").sum()

    static_n = by_rendering.get("static", 0)
    dynamic_n = by_rendering.get("dynamic", 0)
    hybrid_n = by_rendering.get("hybrid", 0)
    unknown_n = by_rendering.get("unknown", 0)

    # caminho relativo do chart a partir do report (reports/site_analysis.md)
    chart_rel = chart_path.relative_to(REPORTS_DIR).as_posix()

    lines: list[str] = []
    lines.append("# Análise dos sites dos leiloeiros (fases 4-5)")
    lines.append("")
    lines.append(
        f"Consolidação dos artefatos de descoberta para os **{total} candidatos** "
        f"que passaram em `confidence ∈ {{high, medium}}` no `filter_real_estate` "
        f"e cujos sites externos foram analisados em `site_analyzer` + `listing_finder`."
    )
    lines.append("")
    lines.append(f"_Gerado a partir de `data/intermediate/site_analysis.csv` + `listing_urls.csv`._")
    lines.append("")

    # ---- TL;DR ----
    lines.append("## TL;DR")
    lines.append("")
    lines.append(f"- **Total analisado**: {total}")
    lines.append(f"- **Sites acessíveis** (sem erro de rede): {accessible} ({accessible/total:.1%})")
    lines.append(f"- **Listing URL identificada**: {with_listing} ({with_listing/total:.1%})")
    lines.append(f"- **Validação OK** (≥5 itens com preço na URL candidata): {items_ok} ({items_ok/total:.1%})")
    lines.append(f"- **Precisam de revisão manual**: {needs_review} ({needs_review/total:.1%})")
    lines.append(f"- **Sites que exigem JS para mostrar listagem**: {requires_js} ({requires_js/total:.1%})")
    lines.append("")

    # ---- Distribuição de rendering ----
    lines.append("## Distribuição de rendering")
    lines.append("")
    lines.append(f"![Distribuição de rendering]({chart_rel})")
    lines.append("")
    lines.append("| rendering | sites | % |")
    lines.append("|---|---:|---:|")
    for key in ("static", "hybrid", "dynamic", "unknown"):
        n = by_rendering.get(key, 0)
        lines.append(f"| `{key}` | {n} | {n/total:.1%} |")
    lines.append(f"| **total** | **{total}** | 100.0% |")
    lines.append("")
    lines.append(
        "Leitura: `static` é JSP/PHP/SSR retornando o HTML completo na resposta inicial; "
        "`dynamic` exige JavaScript pra popular a listagem; `hybrid` mistura — parte "
        "vem no HTML, parte é hidratada client-side; `unknown` quando nem httpx nem "
        "Playwright encontraram links úteis (sites com home minimalista ou bloqueados)."
    )
    lines.append("")

    # ---- Top 10 ----
    lines.append("## Top 10 com mais imóveis detectados")
    lines.append("")
    lines.append(
        "Métrica = ocorrências de preço (`R$ X.XXX,XX`) na URL candidata da listagem, via httpx."
    )
    lines.append("")
    top = df.nlargest(10, "items_detected")[
        ["nome", "uf", "dominio", "rendering", "listing_url", "items_detected"]
    ].copy()
    lines.append("| # | leiloeiro | UF | site | rendering | listing_url | items |")
    lines.append("|---:|---|---|---|---|---|---:|")
    for i, (_, r) in enumerate(top.iterrows(), 1):
        lines.append(_md_row([
            str(i),
            _truncate(r["nome"], 40),
            r["uf"] or "??",
            _truncate(r["dominio"], 45),
            r["rendering"],
            _truncate(r["listing_url"] or "", 80),
            str(r["items_detected"]),
        ]))
    lines.append("")

    # ---- Recomendação de ordem dos spiders ----
    lines.append("## Plano de implementação dos spiders")
    lines.append("")
    lines.append(
        "Ordenamos por **(rendering, items_detected desc)**: estáticos primeiro "
        "(simples Scrapy + parse), depois hybrid (Scrapy com pequenas concessões), "
        "depois dynamic (precisam de `scrapy-playwright`)."
    )
    lines.append("")

    priority_order = {"static": 1, "hybrid": 2, "dynamic": 3, "unknown": 4}
    plan = df[df["items_detected"] >= 5].copy()
    plan["__rank"] = plan["rendering"].map(priority_order)
    plan = plan.sort_values(["__rank", "items_detected"], ascending=[True, False])

    # bucketize: top 20 estáticos, top 10 hybrid, top 10 dynamic
    bucket_targets = [
        ("static", 20),
        ("hybrid", 10),
        ("dynamic", 10),
    ]
    cum = 0
    for rendering_key, n in bucket_targets:
        sub = plan[plan["rendering"] == rendering_key].head(n)
        if sub.empty:
            continue
        lines.append(f"### Bloco {priority_order[rendering_key]} — `rendering = {rendering_key}` (top {len(sub)})")
        lines.append("")
        lines.append("| ord | leiloeiro | UF | site | listing_url | items | tech_stack |")
        lines.append("|---:|---|---|---|---|---:|---|")
        for _, r in sub.iterrows():
            cum += 1
            lines.append(_md_row([
                str(cum),
                _truncate(r["nome"], 35),
                r["uf"] or "??",
                _truncate(r["dominio"], 40),
                _truncate(r["listing_url"] or "", 60),
                str(r["items_detected"]),
                _truncate(r.get("tech_stack") or "", 35),
            ]))
        lines.append("")

    lines.append(
        "Observação: muitos leiloeiros compartilham domínios (ex.: `*.leilao.br`, "
        "`shopleiloes.*`, `superbid`). Antes de começar, **dedupe por domínio raiz** "
        "para evitar 280 spiders quando o número real de plataformas é uma fração disso."
    )
    lines.append("")

    # Distinct domínios
    distinct_domains = (
        plan["dominio"].dropna().str.extract(r"https?://([^/]+)")[0].dropna().nunique()
    )
    lines.append(
        f"Estimativa rápida: as {len(plan)} linhas validadas usam apenas "
        f"~**{distinct_domains}** hosts distintos."
    )
    lines.append("")

    # ---- Sites para revisão manual ----
    lines.append("## Sites para revisão manual")
    lines.append("")
    review = df[df["needs_manual_review"]].copy()
    review["__rank"] = review["rendering"].map(priority_order)
    review = review.sort_values(["confidence", "__rank", "items_detected"], ascending=[True, True, False])
    lines.append(
        f"São **{len(review)} sites** ({len(review)/total:.1%}) onde o detector achou "
        f"<5 itens com preço na URL candidata. Causas mais comuns: layouts que não "
        f"casam com o vocab de keywords, SPAs que precisam de JS na própria listagem "
        f"(o validate é httpx-only), ou sites institucionais sem catálogo na home."
    )
    lines.append("")
    lines.append("### Por categoria")
    lines.append("")
    cat = review.groupby(["confidence", "rendering"]).size().rename("n").reset_index()
    lines.append("| confidence | rendering | sites |")
    lines.append("|---|---|---:|")
    for _, r in cat.iterrows():
        lines.append(_md_row([r["confidence"], r["rendering"], str(r["n"])]))
    lines.append("")
    lines.append("### Lista (até 50 primeiros)")
    lines.append("")
    sample = review.head(50)
    lines.append("| leiloeiro | UF | site | confidence | rendering | requires_js | nota |")
    lines.append("|---|---|---|---|---|:---:|---|")
    for _, r in sample.iterrows():
        lines.append(_md_row([
            _truncate(r["nome"], 35),
            r["uf"] or "??",
            _truncate(r["dominio"], 45),
            r["confidence"],
            r["rendering"],
            "Y" if str(r.get("requires_js_for_listings")).lower() == "true" else "N",
            _truncate(r.get("error") or r.get("html_title") or "", 40),
        ]))
    lines.append("")
    if len(review) > 50:
        lines.append(f"_(+{len(review) - 50} adicionais omitidos — ver tabela completa abaixo.)_")
        lines.append("")

    # ---- Tabela completa ----
    lines.append("## Tabela completa")
    lines.append("")
    lines.append("<details>")
    lines.append(f"<summary>Todos os {total} candidatos (clique para expandir)</summary>")
    lines.append("")
    lines.append(
        "| leiloeiro | UF | site | confidence | http | rendering | listing_url | items | review |"
    )
    lines.append("|---|---|---|---|---|---|---|---:|:---:|")
    full = df.sort_values(
        ["needs_manual_review", "items_detected"], ascending=[True, False]
    )
    for _, r in full.iterrows():
        lines.append(_md_row([
            _truncate(r["nome"], 35),
            r["uf"] or "??",
            _truncate(r["dominio"], 40),
            r["confidence"],
            str(r.get("http_status") or "—"),
            r["rendering"],
            _truncate(r.get("listing_url") or "", 60),
            str(r["items_detected"]),
            "⚠" if r["needs_manual_review"] else "✓",
        ]))
    lines.append("")
    lines.append("</details>")
    lines.append("")

    return "\n".join(lines)


app = typer.Typer(help="Constrói reports/site_analysis.md.")


@app.callback()
def _main() -> None:
    """Força Typer a tratar `run` como subcomando explícito."""


@app.command()
def run(
    site_analysis: Path = typer.Option(
        Path("data/intermediate/site_analysis.csv"), "--site-analysis"
    ),
    listing_urls: Path = typer.Option(
        Path("data/intermediate/listing_urls.csv"), "--listing-urls"
    ),
    output_md: Path = typer.Option(REPORTS_DIR / "site_analysis.md", "--output", "-o"),
    chart_path: Path = typer.Option(
        FIGURES_DIR / "rendering_distribution.png", "--chart"
    ),
) -> None:
    df = load_data(site_analysis, listing_urls)
    logger.info("Carregado: {} linhas", len(df))

    render_chart(df, chart_path)
    logger.info("Gráfico → {}", chart_path)

    md = build_markdown(df, chart_path)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(md, encoding="utf-8")
    logger.success("Relatório → {} ({} bytes)", output_md, len(md))


if __name__ == "__main__":
    app()
