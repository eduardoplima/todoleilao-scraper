"""Lint para `selectors.yaml` produzido pelo `site-recon-pilot`.

Uso:
    python -m validator.lint_selectors <path>/selectors.yaml

Verifica apenas a *estrutura* do arquivo (chaves obrigatórias, tipos),
não a validade semântica dos seletores em si.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console

app = typer.Typer(add_completion=False, help="Valida estrutura mínima de selectors.yaml.")

REQUIRED_FIELD_SELECTORS = (
    "title",
    "price_minimum",
    "price_market",
    "address_block",
    "images",
    "documents",
)

VALID_CARD_KIND = ("css", "xpath")
VALID_PAGINATION_KIND = ("path", "querystring", "none")


def _err(errors: list[str], path: str, msg: str) -> None:
    errors.append(f"{path}: {msg}")


def _check_listing(name: str, listing: Any, errors: list[str]) -> None:
    """`listing_active` ou `listing_closed`. None permitido para closed."""
    if listing is None:
        return  # caller decide se isso é OK
    if not isinstance(listing, dict):
        _err(errors, name, f"esperado mapping, veio {type(listing).__name__}")
        return
    for key in ("url_pattern", "card_selector", "card_kind", "pagination"):
        if key not in listing:
            _err(errors, name, f"chave ausente: {key}")
    if "url_pattern" in listing and not isinstance(listing["url_pattern"], str):
        _err(errors, f"{name}.url_pattern", "deve ser string")
    if "card_selector" in listing and not isinstance(listing["card_selector"], str):
        _err(errors, f"{name}.card_selector", "deve ser string")
    if "card_kind" in listing and listing["card_kind"] not in VALID_CARD_KIND:
        _err(
            errors,
            f"{name}.card_kind",
            f"esperado um de {VALID_CARD_KIND}, veio {listing['card_kind']!r}",
        )
    pag = listing.get("pagination")
    if pag is None or not isinstance(pag, dict):
        _err(errors, f"{name}.pagination", "deve ser mapping com kind/template")
        return
    if pag.get("kind") not in VALID_PAGINATION_KIND:
        _err(
            errors,
            f"{name}.pagination.kind",
            f"esperado um de {VALID_PAGINATION_KIND}, veio {pag.get('kind')!r}",
        )
    tmpl = pag.get("template")
    if tmpl is not None and not isinstance(tmpl, str):
        _err(errors, f"{name}.pagination.template", "deve ser string ou null")


def _check_detail(detail: Any, errors: list[str]) -> None:
    if not isinstance(detail, dict):
        _err(errors, "detail", f"esperado mapping, veio {type(detail).__name__}")
        return
    if "url_pattern" not in detail or not isinstance(detail.get("url_pattern"), str):
        _err(errors, "detail.url_pattern", "deve ser string")
    fs = detail.get("field_selectors")
    if not isinstance(fs, dict):
        _err(errors, "detail.field_selectors", "deve ser mapping")
        return
    for fname in REQUIRED_FIELD_SELECTORS:
        if fname not in fs:
            _err(errors, f"detail.field_selectors.{fname}", "ausente")
            continue
        sel = fs[fname]
        if sel is None:
            continue  # admitimos null com motivo no recon.md
        if not isinstance(sel, dict):
            _err(
                errors,
                f"detail.field_selectors.{fname}",
                "deve ser mapping com selector + kind (ou null)",
            )
            continue
        if "selector" not in sel or not isinstance(sel["selector"], str):
            _err(
                errors,
                f"detail.field_selectors.{fname}.selector",
                "deve ser string",
            )
        if "kind" not in sel or sel["kind"] not in VALID_CARD_KIND:
            _err(
                errors,
                f"detail.field_selectors.{fname}.kind",
                f"esperado um de {VALID_CARD_KIND}, veio {sel.get('kind')!r}",
            )


@app.command()
def lint(
    path: Path = typer.Argument(..., help="Caminho para selectors.yaml"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    console = Console(quiet=quiet)

    if not path.exists():
        console.print(f"[bold red]erro:[/bold red] arquivo não existe: {path}")
        raise typer.Exit(code=1)

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        console.print(f"[bold red]erro:[/bold red] YAML inválido em {path}: {e}")
        raise typer.Exit(code=1) from e

    if not isinstance(data, dict):
        console.print(
            f"[bold red]erro:[/bold red] esperado mapping no topo, veio {type(data).__name__}"
        )
        raise typer.Exit(code=1)

    errors: list[str] = []

    # auctioneer_slug
    slug = data.get("auctioneer_slug")
    if not isinstance(slug, str) or not slug.strip():
        _err(errors, "auctioneer_slug", "deve ser string não-vazia")

    # platform_hint pode ser None
    plat = data.get("platform_hint", None)
    if plat is not None and not isinstance(plat, str):
        _err(errors, "platform_hint", "deve ser string ou null")

    # listing_active obrigatório
    if "listing_active" not in data or data["listing_active"] is None:
        _err(errors, "listing_active", "obrigatório (não pode ser null)")
    else:
        _check_listing("listing_active", data["listing_active"], errors)

    # listing_closed pode ser null (com motivo no recon.md)
    if "listing_closed" in data:
        _check_listing("listing_closed", data["listing_closed"], errors)
    else:
        _err(errors, "listing_closed", "chave ausente; use null + motivo em recon.md")

    # detail obrigatório
    if "detail" not in data:
        _err(errors, "detail", "obrigatório")
    else:
        _check_detail(data["detail"], errors)

    if errors:
        console.print(f"[bold red]lint falhou ({len(errors)} erro(s))[/bold red]")
        for e in errors:
            console.print(f"  • {e}")
        raise typer.Exit(code=1)

    console.print(f"[bold green]selectors.yaml ok:[/bold green] {path}")


if __name__ == "__main__":
    app()
