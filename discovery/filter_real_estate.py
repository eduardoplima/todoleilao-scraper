"""Fase 3 — classificação de leiloeiros que atuam com imóveis.

Heurística pragmática (v1):

1. **strong**: palavras que, quando aparecem em title/description/keywords ou no
   nome do leiloeiro, são fortes indicadores de leilão de imóveis.
2. **medium**: palavras associadas a leilão judicial/extrajudicial em geral.
   Aparecem em sites de imóveis mas também em sites de veículos e outros bens.
3. Pesos maiores para title/description (curadoria humana) e nome do leiloeiro
   (assinatura comercial); menores para o body excerpt (ruidoso).

Confidence final:

- `high`   ≥ HIGH_THRESHOLD pontos
- `medium` ≥ MEDIUM_THRESHOLD pontos
- `unknown` caso contrário (inclui todos sem `dominio`)

Se o site tem erro/offline e o nome do leiloeiro não acende a heurística,
classificamos como `unknown` para revisão manual.
"""
from __future__ import annotations

import csv
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import typer
from loguru import logger

# --- vocabulário ----------------------------------------------------------------

# Mantemos apenas formas SEM acento — o haystack é normalizado antes.
# Listamos plurais explicitamente quando a forma plural não é substring do
# singular (ex.: "leilao" ⊄ "leiloes", "judicial" ⊄ "judiciais"). Quando o
# plural É substring (ex.: "casa" ⊂ "casas"), basta o singular.
STRONG_KEYWORDS = (
    "imovel", "imoveis",
    "apartamento",          # apartamentos via substring
    "casa",                 # casas via substring
    "terreno",              # terrenos via substring
    "lote",                 # lotes via substring
    "imobil",               # stem: imobiliaria/-rio/-rias/-rios
)
MEDIUM_KEYWORDS = (
    "judicial", "judiciais",
    "extrajudicial", "extrajudiciais",
    "matricul",             # stem: matricula/-as
    "edital", "editais",
    "praca",                # pracas via substring
    "leilao", "leiloes",
    "garagem", "garagens",
    "vaga",                 # vagas via substring
    "hipoteca",             # hipotecas via substring
    "alienacao", "alienacoes",
)

# --- pesos ----------------------------------------------------------------------

W_TITLE_STRONG = 5
W_TITLE_MEDIUM = 2
W_DESC_STRONG = 4
W_DESC_MEDIUM = 1.5
W_KEYWORDS_STRONG = 3
W_KEYWORDS_MEDIUM = 1
W_NAME_STRONG = 4
W_NAME_MEDIUM = 1
W_BODY_STRONG = 1
W_BODY_MEDIUM = 0.3

HIGH_THRESHOLD = 8.0
MEDIUM_THRESHOLD = 2.0

OUT_COLUMNS_EXTRA = [
    "real_estate_score",
    "confidence",
    "match_signals",
]


def _normalize(text: str) -> str:
    """Normaliza para matching: lowercase, sem acento, espaços simples."""
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", text)
    no_accent = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return no_accent.lower()


def _count_hits(haystack_norm: str, vocab: tuple[str, ...]) -> tuple[int, list[str]]:
    """Conta ocorrências (presença, não frequência) de termos do vocabulário."""
    matches = []
    for term in vocab:
        if _normalize(term) in haystack_norm:
            matches.append(term)
    return len(matches), matches


def score_row(row: dict[str, Any]) -> tuple[float, list[str]]:
    """Calcula score e lista de sinais para uma linha do enriched CSV."""
    name_norm = _normalize(row.get("nome") or "")
    title_norm = _normalize(row.get("site_title") or "")
    desc_norm = _normalize(row.get("site_description") or "")
    kw_norm = _normalize(row.get("site_keywords") or "")
    body_norm = _normalize(row.get("site_body_excerpt") or "")

    score = 0.0
    signals: list[str] = []

    sources = [
        (name_norm, W_NAME_STRONG, W_NAME_MEDIUM, "name"),
        (title_norm, W_TITLE_STRONG, W_TITLE_MEDIUM, "title"),
        (desc_norm, W_DESC_STRONG, W_DESC_MEDIUM, "desc"),
        (kw_norm, W_KEYWORDS_STRONG, W_KEYWORDS_MEDIUM, "keywords"),
        (body_norm, W_BODY_STRONG, W_BODY_MEDIUM, "body"),
    ]

    for haystack, w_strong, w_medium, src in sources:
        if not haystack:
            continue
        n_s, hits_s = _count_hits(haystack, STRONG_KEYWORDS)
        n_m, hits_m = _count_hits(haystack, MEDIUM_KEYWORDS)
        if n_s:
            score += w_strong * min(n_s, 3)  # cap por fonte para não inflar com repetição
            signals.extend(f"{src}+{h}" for h in hits_s[:3])
        if n_m:
            score += w_medium * min(n_m, 3)
            signals.extend(f"{src}~{h}" for h in hits_m[:3])

    return round(score, 2), signals


def classify(row: dict[str, Any]) -> dict[str, Any]:
    score, signals = score_row(row)
    # signals codificam '+' para strong, '~' para medium
    has_strong = any("+" in s for s in signals)

    # HIGH só é atribuído quando há pelo menos UM strong keyword.
    # Caso contrário, vira medium — sites de leilão geral (ex.: veículos)
    # acumulam pontos só com palavras como "leilão judicial" e seriam
    # classificados como high incorretamente sem este guarda.
    if has_strong and score >= HIGH_THRESHOLD:
        confidence = "high"
    elif score >= MEDIUM_THRESHOLD:
        confidence = "medium"
    else:
        confidence = "unknown"

    out = dict(row)
    out["real_estate_score"] = score
    out["confidence"] = confidence
    out["match_signals"] = "|".join(signals)
    return out


def _load(input_csv: Path) -> tuple[list[dict[str, Any]], list[str]]:
    with input_csv.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        cols = list(reader.fieldnames or [])
    return rows, cols


def _write(rows: list[dict[str, Any]], output: Path, base_columns: list[str]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = base_columns + [c for c in OUT_COLUMNS_EXTRA if c not in base_columns]
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _print_examples(rows: list[dict[str, Any]], confidence: str, n: int = 5) -> None:
    sample = [r for r in rows if r["confidence"] == confidence][:n]
    if not sample:
        logger.info("[{}] (sem amostras)", confidence)
        return
    logger.info("=== Exemplos {} (até {}) ===", confidence, n)
    for r in sample:
        title = (r.get("site_title") or "").strip()[:70]
        signals = (r.get("match_signals") or "")[:120]
        logger.info(
            "  • [{}] {} ({}) score={} signals={}{}",
            r.get("uf") or "??",
            (r.get("nome") or "").strip()[:50],
            (r.get("dominio") or "").strip()[:60] or "(sem dominio)",
            r["real_estate_score"],
            signals,
            f' title="{title}"' if title else "",
        )


app = typer.Typer(help="Filtra leiloeiros que atuam com imóveis.")


@app.callback()
def _main() -> None:
    """Força Typer a tratar `run` como subcomando explícito."""


@app.command()
def run(
    input_csv: Path = typer.Option(
        Path("data/intermediate/auctioneers_enriched.csv"),
        "--input",
        "-i",
    ),
    output: Path = typer.Option(
        Path("data/intermediate/auctioneers_real_estate.csv"),
        "--output",
        "-o",
    ),
    examples: int = typer.Option(5, "--examples", "-n", min=0, max=50),
) -> None:
    rows, base = _load(input_csv)
    logger.info("Lidos {} leiloeiros de {}", len(rows), input_csv)

    classified = [classify(r) for r in rows]
    _write(classified, output, base)

    counts = Counter(r["confidence"] for r in classified)
    total = len(classified)
    logger.success("Gravados {} leiloeiros em {}", total, output)
    logger.info("=== Estatísticas ===")
    logger.info("Total:   {}", total)
    logger.info("high:    {}  ({:.1%})", counts["high"], counts["high"] / total if total else 0)
    logger.info("medium:  {}  ({:.1%})", counts["medium"], counts["medium"] / total if total else 0)
    logger.info("unknown: {}  ({:.1%})", counts["unknown"], counts["unknown"] / total if total else 0)

    if examples:
        for conf in ("high", "medium", "unknown"):
            _print_examples(classified, conf, n=examples)


if __name__ == "__main__":
    app()
