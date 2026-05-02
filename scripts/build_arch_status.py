"""Agregador de status do recon arquitetural por provider.

Lê todos os ``specs/_providers/*/validation.json`` e gera
``specs/_providers/_status.md`` com:
- tabela por provider (passed_hard, fill_rate, bids_present, gotchas)
- top 5 campos com pior fill-rate (entre providers tentados)
- providers em escopo ainda não tentados

Uso:
    uv run python scripts/build_arch_status.py
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean

import typer
from rich.console import Console

app = typer.Typer(add_completion=False)


REPO_ROOT = Path(__file__).resolve().parents[1]
PROVIDERS_DIR = REPO_ROOT / "specs" / "_providers"
SITE_PROVIDERS_CSV = REPO_ROOT / "data" / "intermediate" / "site_providers.csv"
STATUS_MD = PROVIDERS_DIR / "_status.md"

EXCLUDED_PROVIDERS: frozenset[str] = frozenset({
    "proprio_html",
    "desconhecido",
    "parked_ww17",
})


def _provider_counts() -> Counter[str]:
    if not SITE_PROVIDERS_CSV.exists():
        return Counter()
    counts: Counter[str] = Counter()
    with SITE_PROVIDERS_CSV.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            prov = r.get("provider", "")
            if prov:
                counts[prov] += 1
    return counts


def _bids_present(spec_dir: Path) -> bool:
    item = spec_dir / "pilot_item.json"
    if not item.exists():
        return False
    try:
        data = json.loads(item.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    bids = data.get("bids") or []
    return isinstance(bids, list) and len(bids) > 0


def _load_attempts() -> list[dict]:
    rows: list[dict] = []
    if not PROVIDERS_DIR.exists():
        return rows
    for sub in sorted(PROVIDERS_DIR.iterdir()):
        if not sub.is_dir():
            continue
        if sub.name.startswith("_"):
            continue
        validation = sub / "validation.json"
        if not validation.exists():
            continue
        try:
            data = json.loads(validation.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {
                "passed_hard": False,
                "hard_failures": [f"validation.json inválido em {sub.name}"],
                "soft_warnings": [],
                "fill_rate": {},
            }

        notes = ""
        item = sub / "pilot_item.json"
        if item.exists():
            try:
                pj = json.loads(item.read_text(encoding="utf-8"))
                notes = (pj.get("parser_notes") or "")[:140]
            except json.JSONDecodeError:
                notes = "[pilot_item.json inválido]"

        fill_rate = data.get("fill_rate") or {}
        fr_global = mean(fill_rate.values()) if fill_rate else 0.0

        rows.append({
            "provider": sub.name,
            "passed_hard": bool(data.get("passed_hard")),
            "fill_rate_global": fr_global,
            "fill_rate": fill_rate,
            "hard_failures": data.get("hard_failures") or [],
            "soft_warnings": data.get("soft_warnings") or [],
            "parser_notes": notes,
            "bids_present": _bids_present(sub),
        })
    return rows


def _aggregate_field_fill(rows: list[dict]) -> dict[str, float]:
    field_values: dict[str, list[float]] = {}
    for r in rows:
        for k, v in r["fill_rate"].items():
            field_values.setdefault(k, []).append(float(v))
    return {k: mean(vs) for k, vs in field_values.items()}


def _format(rows: list[dict], counts: Counter[str]) -> str:
    lines: list[str] = []
    lines.append("# Recon arquitetural por provider — status")
    lines.append("")
    lines.append("Gerado por `scripts/build_arch_status.py`. Não editar manualmente.")
    lines.append("")

    if not rows:
        lines.append("Nenhum provider com `validation.json` ainda. Rode `/recon-arch`.")
        lines.append("")
    else:
        lines.append("## Providers tentados")
        lines.append("")
        lines.append("| provider | n_sites | passed_hard | fill_rate | bids | gotchas |")
        lines.append("| --- | ---: | :---: | ---: | :---: | --- |")
        for r in sorted(rows, key=lambda x: (not x["passed_hard"], x["provider"])):
            ok = "✅" if r["passed_hard"] else "❌"
            bids = "✅" if r["bids_present"] else "—"
            fr = f"{r['fill_rate_global']:.0%}"
            n = counts.get(r["provider"], 0)
            gotchas = (r["parser_notes"] or "—").replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{r['provider']}` | {n} | {ok} | {fr} | {bids} | {gotchas} |")
        lines.append("")

    field_fill = _aggregate_field_fill(rows)
    if field_fill:
        worst = sorted(field_fill.items(), key=lambda kv: kv[1])[:5]
        lines.append("## Top 5 campos com pior fill-rate")
        lines.append("")
        lines.append("| campo | fill-rate médio |")
        lines.append("| --- | ---: |")
        for k, v in worst:
            lines.append(f"| `{k}` | {v:.0%} |")
        lines.append("")

    attempted = {r["provider"] for r in rows}
    pending = [
        (prov, n) for prov, n in counts.most_common()
        if prov not in EXCLUDED_PROVIDERS and prov not in attempted
    ]
    lines.append("## Providers em escopo ainda não tentados")
    lines.append("")
    if not pending:
        lines.append("Nenhum — todos os providers em escopo foram tentados.")
        lines.append("")
    else:
        lines.append("| provider | n_sites |")
        lines.append("| --- | ---: |")
        for prov, n in pending:
            lines.append(f"| `{prov}` | {n} |")
        lines.append("")

    return "\n".join(lines)


@app.command()
def main(
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    console = Console(quiet=quiet)
    PROVIDERS_DIR.mkdir(parents=True, exist_ok=True)
    rows = _load_attempts()
    counts = _provider_counts()
    md = _format(rows, counts)
    STATUS_MD.write_text(md, encoding="utf-8")
    console.print(
        f"[green]wrote[/green] {STATUS_MD.relative_to(REPO_ROOT)} "
        f"({len(rows)} providers tentados)"
    )


if __name__ == "__main__":
    app()
