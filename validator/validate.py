"""CLI de validação do item piloto.

Uso:
    python -m validator.validate <path>/pilot_item.json

Comportamento:
- Carrega o JSON, instancia ``PilotItem``.
- Aplica regras HARD (falha = exit 1) e SOFT (warning, exit 0).
- Calcula fill-rate por campo e escreve ``validation.json`` ao lado.
- Output rich na stderr/stdout; o programa fica silencioso para máquinas
  via ``--quiet``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from validator.pilot_item import PilotItem

app = typer.Typer(add_completion=False, help="Valida um pilot_item.json contra o schema PilotItem.")

# Campos cuja ausência conta como soft warning (cada um contribui para a lista,
# não falha o validador).
SOFT_FIELDS: tuple[str, ...] = (
    "property_type",
    "market_value_brl",
    "address.uf",
    "address.cep",
    "address.municipality_name",
)


def _is_filled(value: Any) -> bool:
    """Heurística para fill-rate: None/string vazia/lista vazia → não preenchido."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def _flatten_for_fill_rate(item: PilotItem) -> dict[str, bool]:
    """Achata o item nos campos que entram no fill-rate.

    Recursivo dentro de PilotAddress; listas top-level entram como bool de
    "tem ao menos 1". rounds/images/documents NÃO entram nominalmente — a
    presença de items é coberta pelos checks específicos (HARD/SOFT).
    """
    addr = item.address
    flat: dict[str, bool] = {
        "auctioneer_slug": _is_filled(item.auctioneer_slug),
        "source_listing_url": _is_filled(str(item.source_listing_url)),
        "source_lot_url": _is_filled(str(item.source_lot_url)),
        "title": _is_filled(item.title),
        "description": _is_filled(item.description),
        "property_type": _is_filled(item.property_type),
        "area_sqm": _is_filled(item.area_sqm),
        "total_area_sqm": _is_filled(item.total_area_sqm),
        "market_value_brl": _is_filled(item.market_value_brl),
        "auction_status": _is_filled(item.auction_status),
        "scraped_at": _is_filled(item.scraped_at),
        "parser_notes": _is_filled(item.parser_notes),
        # address.* (recursivo)
        "address.raw_text": _is_filled(addr.raw_text),
        "address.street_name": _is_filled(addr.street_name),
        "address.number": _is_filled(addr.number),
        "address.complement": _is_filled(addr.complement),
        "address.district": _is_filled(addr.district),
        "address.municipality_name": _is_filled(addr.municipality_name),
        "address.uf": _is_filled(addr.uf),
        "address.cep": _is_filled(addr.cep),
        # listas — bool de "tem ao menos 1"
        "rounds": _is_filled(item.rounds),
        "bids": _is_filled(item.bids),
        "images": _is_filled(item.images),
        "documents": _is_filled(item.documents),
        "encumbrances_raw": _is_filled(item.encumbrances_raw),
    }
    return flat


def _check_hard(item: PilotItem, json_path: Path) -> list[str]:
    """Retorna lista de hard failures (vazia = passou)."""
    failures: list[str] = []

    if not _is_filled(item.title):
        failures.append("title vazio")
    if not _is_filled(item.address.raw_text):
        failures.append("address.raw_text vazio")
    if not _is_filled(item.auction_status):
        failures.append("auction_status vazio")
    # source_lot_url — Pydantic já barra inválido, mas garantimos não-empty
    if not _is_filled(str(item.source_lot_url)):
        failures.append("source_lot_url vazio")

    # 1+ round com minimum_bid_brl preenchido
    has_bid = any(r.minimum_bid_brl is not None for r in item.rounds)
    if not has_bid:
        failures.append("nenhum round com minimum_bid_brl preenchido")

    # proveniência: pilot_source.html existe e contém literalmente a URL
    source_html = json_path.parent / "pilot_source.html"
    if not source_html.exists():
        failures.append(f"pilot_source.html não encontrado em {source_html.parent}")
    else:
        try:
            html = source_html.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            failures.append(f"falha ao ler pilot_source.html: {e}")
        else:
            url_str = str(item.source_lot_url)
            if url_str not in html:
                failures.append(
                    f"pilot_source.html não contém literalmente source_lot_url ({url_str!r}); "
                    "proveniência quebrada"
                )

    return failures


def _check_soft(item: PilotItem) -> list[str]:
    """Retorna lista de soft warnings (não falha)."""
    warnings: list[str] = []
    for path in SOFT_FIELDS:
        head, _, tail = path.partition(".")
        if tail:
            obj = getattr(item, head, None)
            value = getattr(obj, tail, None) if obj is not None else None
        else:
            value = getattr(item, head, None)
        if not _is_filled(value):
            warnings.append(f"{path} ausente")

    if not item.images:
        warnings.append("nenhuma imagem listada")
    if not item.documents:
        warnings.append("nenhum documento listado (edital/matrícula)")

    return warnings


def _render(
    console: Console,
    json_path: Path,
    passed_hard: bool,
    hard_failures: list[str],
    soft_warnings: list[str],
    fill_rate: dict[str, float],
) -> None:
    status_label = "[bold green]PASSOU[/bold green]" if passed_hard else "[bold red]FALHOU[/bold red]"
    console.print(f"\n[bold]validator[/bold] :: {json_path} :: {status_label}")

    if hard_failures:
        console.print("\n[bold red]HARD failures:[/bold red]")
        for f in hard_failures:
            console.print(f"  • {f}")
    if soft_warnings:
        console.print("\n[bold yellow]SOFT warnings:[/bold yellow]")
        for w in soft_warnings:
            console.print(f"  • {w}")

    table = Table(title="Fill rate por campo")
    table.add_column("campo", style="cyan")
    table.add_column("preenchido", justify="right")
    for k, v in fill_rate.items():
        cell = "[green]●[/green]" if v >= 1.0 else "[red]○[/red]"
        table.add_row(k, cell)
    console.print(table)


def _validation_payload(
    passed_hard: bool,
    hard_failures: list[str],
    soft_warnings: list[str],
    fill_rate: dict[str, float],
) -> dict[str, Any]:
    return {
        "passed_hard": passed_hard,
        "hard_failures": hard_failures,
        "soft_warnings": soft_warnings,
        "fill_rate": fill_rate,
        "validated_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def _decimal_safe(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(f"Não serializável: {type(o)}")


@app.command()
def validate(
    path: Path = typer.Argument(..., exists=False, help="Caminho para pilot_item.json"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suprime output rich"),
) -> None:
    console = Console(quiet=quiet, stderr=False)

    if not path.exists():
        console.print(f"[bold red]erro:[/bold red] arquivo não existe: {path}")
        raise typer.Exit(code=1)
    if path.name != "pilot_item.json":
        console.print(
            f"[bold yellow]aviso:[/bold yellow] esperado 'pilot_item.json', recebi {path.name!r}"
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        console.print(f"[bold red]erro:[/bold red] JSON inválido em {path}: {e}")
        raise typer.Exit(code=1) from e

    try:
        item = PilotItem.model_validate(raw)
    except ValidationError as e:
        console.print("[bold red]erro:[/bold red] item não satisfaz schema PilotItem")
        console.print(str(e))
        # Persiste o resultado mesmo no fallo de schema
        out = _validation_payload(
            passed_hard=False,
            hard_failures=[f"schema: {err['loc']}: {err['msg']}" for err in e.errors()],
            soft_warnings=[],
            fill_rate={},
        )
        (path.parent / "validation.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2, default=_decimal_safe),
            encoding="utf-8",
        )
        raise typer.Exit(code=1) from e

    flat = _flatten_for_fill_rate(item)
    fill_rate = {k: (1.0 if v else 0.0) for k, v in flat.items()}

    hard_failures = _check_hard(item, path)
    soft_warnings = _check_soft(item)
    passed_hard = not hard_failures

    payload = _validation_payload(passed_hard, hard_failures, soft_warnings, fill_rate)
    (path.parent / "validation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_decimal_safe),
        encoding="utf-8",
    )

    _render(console, path, passed_hard, hard_failures, soft_warnings, fill_rate)

    raise typer.Exit(code=0 if passed_hard else 1)


if __name__ == "__main__":
    app()
