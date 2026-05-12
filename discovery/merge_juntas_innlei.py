"""Merge INNLEI (`auctioneers_raw.csv`) com Juntas (`auctioneers_juntas.csv`).

Estratégia de match (em ordem de preferência):

1. **(matrícula normalizada, junta_sigla)** quando ambos os lados expõem
   matrícula. INNLEI tem `matricula` + `junta_comercial` (string longa) +
   `matriculas_extras` (formato ``MATR@UF; MATR@UF``); mapeamos `junta_comercial`
   para a sigla canônica antes de comparar.
2. **nome normalizado** (lowercase, sem acentos, strip de sufixos `Leilões`,
   `Leiloeiro Oficial`, etc.).

Saída: `data/intermediate/auctioneers_unified.csv` com schema::

    source_kind,nome,matricula,junta_sigla,uf,situacao,juc_url,
    innlei_id,innlei_slug,innlei_dominio,innlei_email,scraped_at

`source_kind ∈ {innlei_only, junta_only, both}`.

Imprime um relatório com contagens por UF e top junta_only.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table

# Map de "junta_comercial" (texto longo do INNLEI) -> sigla canônica.
JUNTA_NAME_TO_SIGLA = {
    "junta comercial do estado de sao paulo": "JUCESP",
    "junta comercial do estado de são paulo": "JUCESP",
    "junta comercial do parana": "JUCEPAR",
    "junta comercial do paraná": "JUCEPAR",
    "junta comercial do estado de minas gerais": "JUCEMG",
    "junta comercial do estado do rio de janeiro": "JUCERJA",
    "junta comercial do estado do rio grande do sul": "JUCISRS",
    "junta comercial industrial e servicos do rio grande do sul": "JUCISRS",
    "junta comercial do estado de santa catarina": "JUCESC",
    "junta comercial do estado da bahia": "JUCEB",
    "junta comercial do estado do ceara": "JUCEC",
    "junta comercial do estado do ceará": "JUCEC",
    "junta comercial do estado de goias": "JUCEG",
    "junta comercial do estado de goiás": "JUCEG",
    "junta comercial do estado de pernambuco": "JUCEPE",
    "junta comercial do estado do espirito santo": "JUCEES",
    "junta comercial do estado do espírito santo": "JUCEES",
    "junta comercial do estado do para": "JUCEPA",
    "junta comercial do estado do pará": "JUCEPA",
    "junta comercial do estado do maranhao": "JUCEMA",
    "junta comercial do estado do maranhão": "JUCEMA",
    "junta comercial do estado de mato grosso": "JUCEMAT",
    "junta comercial do estado de mato grosso do sul": "JUCEMS",
    "junta comercial do estado do rio grande do norte": "JUCERN",
    "junta comercial do estado da paraiba": "JUCEP",
    "junta comercial do estado da paraíba": "JUCEP",
    "junta comercial do estado do piaui": "JUCEPI",
    "junta comercial do estado do piauí": "JUCEPI",
    "junta comercial do estado de sergipe": "JUCESE",
    "junta comercial do estado de alagoas": "JUCEAL",
    "junta comercial do estado de tocantins": "JUCETINS",
    "junta comercial do estado do tocantins": "JUCETINS",
    "junta comercial do estado de rondonia": "JUCER",
    "junta comercial do estado de rondônia": "JUCER",
    "junta comercial do estado do amazonas": "JUCEA",
    "junta comercial do estado do amapa": "JUCAP",
    "junta comercial do estado do amapá": "JUCAP",
    "junta comercial do estado do acre": "JUCEAC",
    "junta comercial do estado de roraima": "JUCERR",
    "junta comercial industrial e servicos do distrito federal": "JCDF",
    "junta comercial do distrito federal": "JCDF",
}

UF_TO_SIGLA = {
    "SP": "JUCESP", "PR": "JUCEPAR", "MG": "JUCEMG", "RJ": "JUCERJA",
    "RS": "JUCISRS", "SC": "JUCESC", "BA": "JUCEB", "CE": "JUCEC",
    "GO": "JUCEG", "PE": "JUCEPE", "ES": "JUCEES", "PA": "JUCEPA",
    "MA": "JUCEMA", "MT": "JUCEMAT", "MS": "JUCEMS", "RN": "JUCERN",
    "PB": "JUCEP", "PI": "JUCEPI", "SE": "JUCESE", "AL": "JUCEAL",
    "TO": "JUCETINS", "RO": "JUCER", "AM": "JUCEA", "AP": "JUCAP",
    "AC": "JUCEAC", "RR": "JUCERR", "DF": "JCDF",
}

# Sufixos comuns nos nomes do INNLEI ("Leilões Oficial", "Leiloeiro Oficial").
NAME_SUFFIX_RE = re.compile(
    r"\s+(?:leil[oõ]es(?:\s+oficial)?|leiloeir[oa]\s+oficial|leil[oõ]es)\s*$",
    re.IGNORECASE,
)


def strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_name(s: str) -> str:
    s = strip_accents(s or "").lower().strip()
    s = NAME_SUFFIX_RE.sub("", s)
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_matricula(s: str) -> str:
    """Remove zeros à esquerda, separadores, sufixos /L /O, e canonicaliza."""
    s = (s or "").upper().strip()
    # Remove "MATRICULA" prefix se vier por engano
    s = re.sub(r"^MATR[ÍI]CULA\s*[:\-]?\s*", "", s, flags=re.IGNORECASE)
    # Remove pontuação não-alfanumérica
    s = re.sub(r"[^\w]", "", s)
    # Strip zeros iniciais
    s = s.lstrip("0") or s
    return s


def innlei_junta_sigla(junta_name: str, uf: str) -> str:
    """Resolve a sigla da Junta a partir do nome longo do INNLEI ou da UF."""
    key = strip_accents((junta_name or "").lower().strip())
    if key in JUNTA_NAME_TO_SIGLA:
        return JUNTA_NAME_TO_SIGLA[key]
    return UF_TO_SIGLA.get((uf or "").upper().strip(), "")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_innlei(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        logger.warning("INNLEI CSV não encontrado: {}", path)
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(row)
    logger.info("INNLEI: {} linhas carregadas de {}", len(out), path)
    return out


def load_juntas(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        logger.warning("Juntas CSV não encontrado: {}", path)
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(row)
    logger.info("Juntas: {} linhas carregadas de {}", len(out), path)
    return out


def merge(
    innlei: list[dict[str, Any]],
    juntas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Faz o merge, marcando `source_kind` em cada registro."""
    # Indices na Junta para lookup eficiente
    junta_by_matricula: dict[tuple[str, str], dict[str, Any]] = {}
    junta_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for j in juntas:
        sigla = (j.get("junta_sigla") or "").strip().upper()
        m_norm = normalize_matricula(j.get("matricula") or "")
        if sigla and m_norm:
            junta_by_matricula[(m_norm, sigla)] = j
        nm = normalize_name(j.get("nome") or "")
        if nm:
            junta_by_name[nm].append(j)

    matched_junta_ids: set[int] = set()  # by id()
    unified: list[dict[str, Any]] = []

    for inn in innlei:
        sigla = innlei_junta_sigla(inn.get("junta_comercial") or "", inn.get("uf") or "")
        m_norm = normalize_matricula(inn.get("matricula") or "")
        nm = normalize_name(inn.get("nome") or "")
        matched = None
        if sigla and m_norm:
            matched = junta_by_matricula.get((m_norm, sigla))
        # Tentar matrículas extras: "40@CE; 026@TO; 21/337-L@PR".
        # Importante: marcar TODAS as juntas casadas, mesmo quando já achamos
        # a primária — uma única pessoa pode ter matrícula em 10 Juntas e cada
        # uma delas precisa ser removida de `junta_only`.
        extras = inn.get("matriculas_extras") or ""
        for extra in [e.strip() for e in extras.split(";") if "@" in e]:
            mat_str, _, uf_str = extra.partition("@")
            extra_sigla = UF_TO_SIGLA.get(uf_str.upper().strip(), "")
            extra_m = normalize_matricula(mat_str)
            if extra_sigla and extra_m:
                candidate = junta_by_matricula.get((extra_m, extra_sigla))
                if candidate is not None:
                    matched_junta_ids.add(id(candidate))
                    if matched is None:
                        matched = candidate
                        sigla = extra_sigla
        if matched is None and nm:
            candidates = junta_by_name.get(nm, [])
            # Preferir candidato cuja sigla bate (quando temos sigla)
            if sigla:
                for c in candidates:
                    if (c.get("junta_sigla") or "").upper() == sigla:
                        matched = c
                        break
            if matched is None and len(candidates) == 1:
                matched = candidates[0]

        if matched is not None:
            matched_junta_ids.add(id(matched))
            unified.append(
                {
                    "source_kind": "both",
                    "nome": inn.get("nome") or matched.get("nome") or "",
                    "matricula": inn.get("matricula") or matched.get("matricula") or "",
                    "junta_sigla": sigla or matched.get("junta_sigla") or "",
                    "uf": inn.get("uf") or matched.get("uf") or "",
                    "situacao": inn.get("situacao") or matched.get("situacao") or "",
                    "juc_url": matched.get("juc_url") or "",
                    "innlei_id": inn.get("id") or "",
                    "innlei_slug": inn.get("slug") or "",
                    "innlei_dominio": inn.get("dominio") or inn.get("dominio_url") or "",
                    "innlei_email": inn.get("email") or "",
                    "scraped_at": now_iso(),
                },
            )
        else:
            unified.append(
                {
                    "source_kind": "innlei_only",
                    "nome": inn.get("nome") or "",
                    "matricula": inn.get("matricula") or "",
                    "junta_sigla": sigla,
                    "uf": inn.get("uf") or "",
                    "situacao": inn.get("situacao") or "",
                    "juc_url": "",
                    "innlei_id": inn.get("id") or "",
                    "innlei_slug": inn.get("slug") or "",
                    "innlei_dominio": inn.get("dominio") or inn.get("dominio_url") or "",
                    "innlei_email": inn.get("email") or "",
                    "scraped_at": now_iso(),
                },
            )

    # Junta-only: o que sobrou
    for j in juntas:
        if id(j) in matched_junta_ids:
            continue
        unified.append(
            {
                "source_kind": "junta_only",
                "nome": j.get("nome") or "",
                "matricula": j.get("matricula") or "",
                "junta_sigla": (j.get("junta_sigla") or "").upper(),
                "uf": (j.get("uf") or "").upper(),
                "situacao": j.get("situacao") or "",
                "juc_url": j.get("juc_url") or "",
                "innlei_id": "",
                "innlei_slug": "",
                "innlei_dominio": "",
                "innlei_email": "",
                "scraped_at": now_iso(),
            },
        )

    return unified


def write_unified(records: list[dict[str, Any]], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "source_kind", "nome", "matricula", "junta_sigla", "uf", "situacao", "juc_url",
        "innlei_id", "innlei_slug", "innlei_dominio", "innlei_email", "scraped_at",
    ]
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            writer.writerow(r)
    return len(records)


def print_report(records: list[dict[str, Any]]) -> None:
    console = Console()
    counts = Counter(r["source_kind"] for r in records)

    summary = Table(title="Merge INNLEI x Juntas — totais por origem")
    summary.add_column("source_kind")
    summary.add_column("total", justify="right")
    for k in ("innlei_only", "junta_only", "both"):
        summary.add_row(k, str(counts.get(k, 0)))
    summary.add_row("[bold]TOTAL", f"[bold]{len(records)}")
    console.print(summary)

    # Por UF
    by_uf: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        by_uf[r.get("uf") or "??"][r["source_kind"]] += 1
    uf_table = Table(title="Por UF")
    uf_table.add_column("UF")
    uf_table.add_column("innlei_only", justify="right")
    uf_table.add_column("junta_only", justify="right")
    uf_table.add_column("both", justify="right")
    uf_table.add_column("total", justify="right")
    for uf in sorted(by_uf):
        c = by_uf[uf]
        total = sum(c.values())
        uf_table.add_row(uf, str(c.get("innlei_only", 0)), str(c.get("junta_only", 0)),
                         str(c.get("both", 0)), str(total))
    console.print(uf_table)

    # Top junta_only
    junta_only = [r for r in records if r["source_kind"] == "junta_only"]
    by_sigla = Counter(r.get("junta_sigla") or "??" for r in junta_only)
    junta_table = Table(title="junta_only — gaps do INNLEI")
    junta_table.add_column("junta_sigla")
    junta_table.add_column("UF")
    junta_table.add_column("total", justify="right")
    for sigla, n in by_sigla.most_common():
        uf = next((r["uf"] for r in junta_only if r.get("junta_sigla") == sigla), "")
        junta_table.add_row(sigla, uf, str(n))
    console.print(junta_table)


app = typer.Typer(help="Merge dos CSVs INNLEI x Juntas.")


@app.callback()
def _main() -> None:  # pragma: no cover - typer plumbing
    """Força Typer a tratar `run` como subcomando explícito."""


@app.command()
def run(
    innlei_path: Path = typer.Option(
        Path("data/intermediate/auctioneers_raw.csv"),
        "--innlei",
        help="CSV de saída do INNLEI scraper.",
    ),
    juntas_path: Path = typer.Option(
        Path("data/intermediate/auctioneers_juntas.csv"),
        "--juntas",
        help="CSV de saída dos scrapers de Juntas.",
    ),
    output: Path = typer.Option(
        Path("data/intermediate/auctioneers_unified.csv"),
        "--output",
        "-o",
        help="Caminho do CSV unificado.",
    ),
) -> None:
    """Faz o merge e imprime relatório."""
    innlei = load_innlei(innlei_path)
    juntas = load_juntas(juntas_path)
    records = merge(innlei, juntas)
    n = write_unified(records, output)
    logger.success("Unified: {} linhas escritas em {}", n, output)
    print_report(records)


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 1:
        sys.argv.append("run")
    app()
