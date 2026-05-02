"""Seleciona representante por provider para o /recon-arch.

Cruza site_providers.csv (provider de cada site) com site_analysis.csv
(useful_links e demais metadados) e, para cada provider em escopo,
escolhe o site representante (max useful_links com filtros de saúde).
Escreve specs/_providers/<provider>/_input.json para cada selecionado.

Uso::

    uv run python scripts/select_arch_batch.py --providers all
    uv run python scripts/select_arch_batch.py --providers soleon
    uv run python scripts/select_arch_batch.py --providers soleon,leilao_pro
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import typer

app = typer.Typer(add_completion=False)

REPO = Path(__file__).resolve().parents[1]
ANALYSIS_CSV = REPO / "data" / "intermediate" / "site_analysis.csv"
PROVIDERS_CSV = REPO / "data" / "intermediate" / "site_providers.csv"
OUT_DIR = REPO / "specs" / "_providers"

# Providers excluídos: sites próprios sem padrão multi-tenant + parking.
EXCLUDED_PROVIDERS: frozenset[str] = frozenset({
    "proprio_html",
    "desconhecido",
    "parked_ww17",
})

CONFIANCA_RANK = {"high": 3, "medium": 2, "low": 1, "n/a": 0}


def _load_analysis_by_url() -> dict[str, dict]:
    """Mapa de final_url → linha completa do site_analysis.csv."""
    if not ANALYSIS_CSV.exists():
        raise FileNotFoundError(ANALYSIS_CSV)
    out: dict[str, dict] = {}
    with ANALYSIS_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            url = (r.get("final_url") or "").strip()
            if url:
                out[url] = r
    return out


def _load_providers() -> list[dict]:
    if not PROVIDERS_CSV.exists():
        raise FileNotFoundError(PROVIDERS_CSV)
    rows: list[dict] = []
    with PROVIDERS_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def _score(analysis_row: dict | None) -> tuple[int, int, float]:
    """Tupla de score para tiebreak: (useful_links, confianca_rank, real_estate_score)."""
    if analysis_row is None:
        return (0, 0, 0.0)
    try:
        su = int(analysis_row.get("static_useful_links") or 0)
    except ValueError:
        su = 0
    try:
        du = int(analysis_row.get("dynamic_useful_links") or 0)
    except ValueError:
        du = 0
    try:
        res = float(analysis_row.get("real_estate_score") or 0)
    except ValueError:
        res = 0.0
    confianca = (analysis_row.get("confidence") or "").strip().lower()
    return (su + du, CONFIANCA_RANK.get(confianca, 0), res)


def _passes_health_filter(prov_row: dict, analysis_row: dict | None) -> bool:
    if analysis_row is None:
        return False
    if (analysis_row.get("error") or "").strip():
        return False
    if (analysis_row.get("http_status") or "").strip() != "200":
        return False
    if prov_row.get("cache_used") == "cache_missing":
        return False
    return True


def _group_by_provider(
    providers: list[dict], analysis_by_url: dict[str, dict], wanted: set[str] | None
) -> dict[str, list[tuple[dict, dict | None]]]:
    """provider → list of (provider_row, analysis_row)."""
    groups: dict[str, list[tuple[dict, dict | None]]] = {}
    for p in providers:
        prov = p.get("provider", "")
        if prov in EXCLUDED_PROVIDERS:
            continue
        if wanted is not None and prov not in wanted:
            continue
        url = (p.get("final_url") or "").strip()
        analysis = analysis_by_url.get(url)
        groups.setdefault(prov, []).append((p, analysis))
    return groups


def _pick_representative(
    members: list[tuple[dict, dict | None]],
) -> tuple[dict, dict] | None:
    """Filtra por saúde, ordena por score, retorna (prov_row, analysis_row)."""
    healthy = [(p, a) for p, a in members if _passes_health_filter(p, a)]
    if not healthy:
        # fallback: ignora cache_missing/http_status filter, mantém só "sem error"
        healthy = [
            (p, a) for p, a in members if a is not None and not (a.get("error") or "").strip()
        ]
    if not healthy:
        return None
    healthy.sort(key=lambda pa: _score(pa[1]), reverse=True)
    p, a = healthy[0]
    assert a is not None
    return p, a


def _build_input(
    provider: str, rep_prov: dict, rep_analysis: dict, members: list[tuple[dict, dict | None]]
) -> dict:
    others: list[dict] = []
    for p, a in members:
        if p is rep_prov:
            continue
        score_tuple = _score(a)
        others.append({
            "slug": (p.get("slug") or "").strip(),
            "nome": (p.get("nome") or "").strip(),
            "final_url": (p.get("final_url") or "").strip(),
            "useful_links": score_tuple[0],
            "cache_used": p.get("cache_used") or "",
        })
    others.sort(key=lambda o: o["useful_links"], reverse=True)
    return {
        "provider": provider,
        "representative": {
            "slug": (rep_prov.get("slug") or "").strip(),
            "nome": (rep_prov.get("nome") or "").strip(),
            "final_url": (rep_prov.get("final_url") or "").strip(),
            "site_analysis_row": rep_analysis,
        },
        "sites_in_provider": others[:5],
        "n_sites_in_provider": len(members),
    }


def _parse_wanted(arg: str) -> set[str] | None:
    arg = arg.strip()
    if not arg or arg == "all":
        return None
    return {p.strip() for p in arg.split(",") if p.strip()}


@app.command()
def main(
    providers: str = typer.Option(
        "all", "--providers", help="'all' ou lista CSV de providers (ex.: 'soleon,leilao_pro')."
    ),
) -> None:
    if not ANALYSIS_CSV.exists():
        typer.echo(f"site_analysis.csv não existe em {ANALYSIS_CSV}", err=True)
        raise typer.Exit(2)
    if not PROVIDERS_CSV.exists():
        typer.echo(
            f"site_providers.csv não existe em {PROVIDERS_CSV}. "
            "Rode scripts/detect_providers.py primeiro.",
            err=True,
        )
        raise typer.Exit(2)

    wanted = _parse_wanted(providers)
    analysis = _load_analysis_by_url()
    prov_rows = _load_providers()
    groups = _group_by_provider(prov_rows, analysis, wanted)

    if not groups:
        typer.echo("Nenhum provider em escopo (após filtros e exclusões).", err=True)
        raise typer.Exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    selected = 0
    for provider, members in sorted(groups.items()):
        pick = _pick_representative(members)
        if pick is None:
            typer.echo(f"# skip {provider}: nenhum site saudável", err=True)
            continue
        rep_prov, rep_analysis = pick
        payload = _build_input(provider, rep_prov, rep_analysis, members)

        spec_dir = OUT_DIR / provider
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "_input.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        sys.stdout.write(
            f"{provider}\t{payload['representative']['final_url']}\t{len(members)}\n"
        )
        selected += 1

    if selected == 0:
        typer.echo("Nenhum representante saudável encontrado para os providers selecionados.", err=True)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
