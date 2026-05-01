"""Classify each auctioneer in site_analysis.csv by the platform/vendor of
its homepage, using the HTML already cached on disk by site_analyzer.

No HTTP fetches, no LLM, no per-site agent: pure deterministic regex
matching over local files. Output:

  - reports/providers.md            (two markdown tables)
  - data/intermediate/site_providers.csv  (raw rows for downstream use)
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, NamedTuple
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
CSV_IN = ROOT / "data" / "intermediate" / "site_analysis.csv"
CSV_OUT = ROOT / "data" / "intermediate" / "site_providers.csv"
MD_OUT = ROOT / "reports" / "providers.md"


class Detection(NamedTuple):
    provider: str
    confidence: str  # high | medium | low | n/a
    signal: str


def html_paths_for(screenshot_path: str) -> tuple[Path | None, Path | None]:
    if not screenshot_path:
        return None, None
    base = ROOT / screenshot_path
    static = base.with_suffix("").with_suffix(".static.html")
    dynamic = base.with_suffix("").with_suffix(".dynamic.html")
    return (static if static.exists() else None,
            dynamic if dynamic.exists() else None)


def load_html(static: Path | None, dynamic: Path | None) -> tuple[str, str]:
    """Returns (text, source_label). Prefers static, falls back to dynamic."""
    for path, label in ((static, "static"), (dynamic, "dynamic")):
        if path is None:
            continue
        try:
            return path.read_text(encoding="utf-8", errors="ignore"), label
        except OSError:
            continue
    return "", ""


# Rules are evaluated in order; first match wins. Each rule is a callable
# (html_lower, final_url, dominio, tech_signals_lower, tech_stack_lower,
#  meta_generator_lower) -> Detection | None.

def rule_soleon(html, final_url, dom, signals, stack, meta_gen):
    if 'name="author" content="soleon' in html:
        return Detection("soleon", "high", "meta_author=SOLEON")
    if "tecnologia soleon" in html:
        return Detection("soleon", "high", "footer:Tecnologia SOLEON")
    if "soleon.com.br" in html:
        return Detection("soleon", "medium", "link:soleon.com.br")
    return None


def rule_leilao_br(html, final_url, dom, signals, stack, meta_gen):
    host = (urlparse(final_url).hostname or "").lower()
    if host.endswith(".leilao.br") or host == "leilao.br":
        return Detection("leilao_br", "high", f"host={host}")
    if "leilao.br" in signals or "leilao.br platform" in stack:
        if "leilao.br" in html:
            return Detection("leilao_br", "medium", "tech_signals+html=leilao.br")
    return None


def rule_suporte_leiloes(html, final_url, dom, signals, stack, meta_gen):
    host = (urlparse(final_url).hostname or "").lower()
    if host.endswith(".suporteleiloes.com.br"):
        return Detection("suporte_leiloes", "high", f"host={host}")
    if "cdn.suporteleiloes.com.br" in html:
        return Detection("suporte_leiloes", "high", "cdn.suporteleiloes.com.br")
    if "suporteleiloes.com.br" in html:
        return Detection("suporte_leiloes", "medium", "link:suporteleiloes.com.br")
    return None


def rule_sishp(html, final_url, dom, signals, stack, meta_gen):
    if "/sishp/leilao/" in html or "/sishp/lote/" in html:
        return Detection("sishp", "high", "path=/sishp/")
    if "lancenoleilao.com.br" in html or "lancetotal.com.br" in html:
        return Detection("sishp", "medium", "lancetotal/lancenoleilao link")
    if re.search(r"\bsishp\b", html):
        return Detection("sishp", "medium", "string:sishp")
    return None


def rule_leilao_pro(html, final_url, dom, signals, stack, meta_gen):
    if 'name="author" content="leilão pro' in html or \
       'name="author" content="leilao pro' in html:
        return Detection("leilao_pro", "high", "meta_author=Leilão Pro")
    if "https://www.leilao.pro" in html or "://leilao.pro" in html:
        return Detection("leilao_pro", "high", "link:leilao.pro")
    return None


def rule_leilotech(html, final_url, dom, signals, stack, meta_gen):
    if "leilotech.com.br" in html or "leilotech.workers.dev" in html:
        return Detection("leilotech", "high", "leilotech.com.br")
    return None


def rule_plataforma_leiloar(html, final_url, dom, signals, stack, meta_gen):
    if "plataformaleiloar.com.br" in html:
        return Detection("plataforma_leiloar", "high", "plataformaleiloar.com.br")
    if 'name="author" content="plataforma leiloar' in html:
        return Detection("plataforma_leiloar", "high", "meta_author=Plataforma Leiloar")
    return None


def rule_leiloes_judiciais_br(html, final_url, dom, signals, stack, meta_gen):
    if ("leiloesjudiciaisbrasil.com.br" in html
            or "atendimento.leiloesjudiciais.com.br" in html
            or "cesvibrasil.com.br" in html):
        return Detection("leiloes_judiciais_br", "high", "leiloesjudiciaisbrasil/cesvibrasil")
    return None


def rule_bomvalor(html, final_url, dom, signals, stack, meta_gen):
    if "bomvalor.com.br" in html:
        return Detection("bomvalor", "high", "bomvalor.com.br")
    return None


def rule_palacio_dos_leiloes(html, final_url, dom, signals, stack, meta_gen):
    host = (urlparse(final_url).hostname or "").lower()
    if "palaciodosleiloes" in host:
        return Detection("palacio_dos_leiloes", "high", f"host={host}")
    if 'name="author" content="palácio dos leilões' in html:
        return Detection("palacio_dos_leiloes", "high", "meta_author")
    return None


def rule_softgt(html, final_url, dom, signals, stack, meta_gen):
    if "softgt.com.br" in html:
        return Detection("softgt", "high", "link:softgt.com.br")
    if 'name="author" content="softgt' in html:
        return Detection("softgt", "high", "meta_author=SoftGT")
    if "softgt - todos os direitos" in html or "softgt informatica" in html:
        return Detection("softgt", "medium", "footer:SoftGT")
    return None


def rule_leiloesbr(html, final_url, dom, signals, stack, meta_gen):
    if "leiloesbr.com.br" in html:
        return Detection("leiloesbr", "high", "link:leiloesbr.com.br")
    return None


def rule_leiloesweb(html, final_url, dom, signals, stack, meta_gen):
    if "leiloesweb.com.br" in html:
        return Detection("leiloesweb", "high", "link:leiloesweb.com.br")
    return None


def rule_wix(html, final_url, dom, signals, stack, meta_gen):
    if "wix.com" in meta_gen or "parastorage.com" in html or "wixstatic.com" in html:
        return Detection("wix", "high", "wix/parastorage")
    return None


def rule_degrau_publicidade(html, final_url, dom, signals, stack, meta_gen):
    # White-label de agência: vários leiloeiros usam o mesmo template feito
    # pela Degrau Publicidade. Não é plataforma SaaS, mas sites compartilham
    # estrutura — vale agrupar.
    if "degraupublicidade.com.br" in html:
        return Detection("degrau_publicidade", "medium", "link:degraupublicidade.com.br")
    return None


def rule_s4b_digital(html, final_url, dom, signals, stack, meta_gen):
    # S4B Digital (Sport4Biz, Superbid Group) — assets compartilhados via
    # static.s4bdigital.net. 37 sites de leiloeiros parceiros referenciam.
    # Não é a plataforma Superbid em si (host superbid.net), é a integração
    # de assets/widgets da rede Superbid Group. Provider separado para não
    # confundir com superbid puro.
    if "s4bdigital.net" in html:
        return Detection("s4b_digital", "high", "s4bdigital.net")
    return None


def rule_parked_ww17(html, final_url, dom, signals, stack, meta_gen):
    # Domínios servidos por parking provider sob ww17.* (HTML < 2KB,
    # apenas redireciona/exibe ad). Sites de leiloeiros que abandonaram
    # ou reapontaram o domínio.
    host = (urlparse(final_url).hostname or "").lower()
    if host.startswith("ww17.") and len(html) < 5000:
        return Detection("parked_ww17", "medium", "host=ww17.* + html<5KB")
    return None


def rule_superbid(html, final_url, dom, signals, stack, meta_gen):
    # Só captura por host. Antes a regra também aceitava `superbid` em
    # tech_signals/stack, mas isso falsamente classificava ~42 sites cujo
    # único vínculo com a Superbid era um link "veja também" no rodapé.
    host = (urlparse(final_url).hostname or "").lower()
    if "superbid" in host:
        return Detection("superbid", "high", f"host={host}")
    return None


def rule_mega_leiloes(html, final_url, dom, signals, stack, meta_gen):
    host = (urlparse(final_url).hostname or "").lower()
    if "megaleiloes" in host:
        return Detection("mega_leiloes", "high", f"host={host}")
    if "megaleiloes.com.br" in html:
        return Detection("mega_leiloes", "medium", "link:megaleiloes.com.br")
    return None


def rule_sodre_santoro(html, final_url, dom, signals, stack, meta_gen):
    host = (urlparse(final_url).hostname or "").lower()
    if "sodresantoro" in host or "sodresantoro.com.br" in html:
        return Detection("sodre_santoro", "high", "sodresantoro")
    return None


def rule_leilovip(html, final_url, dom, signals, stack, meta_gen):
    host = (urlparse(final_url).hostname or "").lower()
    if "leilovip" in host or "leilovip" in signals:
        return Detection("leilovip", "high", "leilovip")
    return None


def rule_biddo(html, final_url, dom, signals, stack, meta_gen):
    if "biddo" in signals or "biddo" in stack:
        return Detection("biddo", "medium", "tech_signals=biddo")
    return None


def rule_e_leiloes(html, final_url, dom, signals, stack, meta_gen):
    if "e-leil&otilde;es" in html or "e-leilões" in html:
        if "leilao.br" in html or "_nuxt" in html:
            return Detection("e_leiloes", "medium", "E-LEILÕES + leilao.br/nuxt")
    return None


def rule_wordpress(html, final_url, dom, signals, stack, meta_gen):
    if "wordpress" in stack or "wordpress" in meta_gen:
        return Detection("wordpress", "medium", "stack=WordPress")
    if "/wp-content/" in html or "/wp-includes/" in html:
        return Detection("wordpress", "medium", "path=/wp-content/")
    return None


def rule_proprio_html(html, final_url, dom, signals, stack, meta_gen):
    # Site without a known platform marker but with recognizable basic stack.
    # Lower confidence — likely a custom-built site.
    if html and ("jquery" in stack or "bootstrap" in stack):
        return Detection("proprio_html", "low", f"stack={stack or 'plain'}")
    return None


RULES = [
    rule_soleon,
    rule_leilao_br,
    rule_suporte_leiloes,
    rule_sishp,
    rule_leilao_pro,
    rule_leilotech,
    rule_plataforma_leiloar,
    rule_leiloes_judiciais_br,
    rule_bomvalor,
    rule_palacio_dos_leiloes,
    rule_s4b_digital,
    rule_parked_ww17,
    rule_softgt,
    rule_leiloesbr,
    rule_leiloesweb,
    rule_wix,
    rule_degrau_publicidade,
    rule_superbid,
    rule_mega_leiloes,
    rule_sodre_santoro,
    rule_leilovip,
    rule_biddo,
    rule_e_leiloes,
    rule_wordpress,
    rule_proprio_html,
]


def classify(row: dict) -> tuple[Detection, str]:
    """Returns (detection, cache_label)."""
    static_p, dynamic_p = html_paths_for(row.get("screenshot_path") or "")
    html, cache_label = load_html(static_p, dynamic_p)
    if not html:
        return Detection("cache_missing", "n/a", "no html cache"), ""

    html_lower = html.lower()
    final_url = (row.get("final_url") or "").lower()
    dominio = (row.get("dominio") or "").lower()
    signals = (row.get("tech_signals") or "").lower()
    stack = (row.get("tech_stack") or "").lower()
    meta_gen = (row.get("html_meta_generator") or "").lower()

    for rule in RULES:
        det = rule(html_lower, final_url, dominio, signals, stack, meta_gen)
        if det is not None:
            return det, cache_label
    return Detection("desconhecido", "n/a", "no rule matched"), cache_label


def short_domain(final_url: str, dominio: str) -> str:
    host = urlparse(final_url or dominio or "").hostname or ""
    return host.lstrip("www.") if host.startswith("www.") else host


def md_escape(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").strip()


def write_report(rows: list[dict], totals: Counter[str], total_rows: int) -> None:
    MD_OUT.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    lines: list[str] = []
    lines.append("# Plataformas/fornecedores dos leiloeiros\n")
    lines.append(f"Gerado por `scripts/detect_providers.py` em {now}.\n")
    lines.append(f"Total de leiloeiros analisados: {total_rows}.\n")

    lines.append("## Tabela 2 — total por provedor\n")
    lines.append("| provedor | total | % |")
    lines.append("|----------|------:|--:|")
    for provider, n in totals.most_common():
        pct = (n / total_rows * 100) if total_rows else 0.0
        lines.append(f"| {provider} | {n} | {pct:.1f}% |")
    lines.append("")

    lines.append("## Tabela 1 — site → provedor\n")
    lines.append("| slug | nome | domínio | provedor | confiança | sinal |")
    lines.append("|------|------|---------|----------|-----------|-------|")
    for r in sorted(rows, key=lambda x: (x["slug"] or x["nome"]).lower()):
        lines.append(
            "| {slug} | {nome} | {dom} | {prov} | {conf} | {sinal} |".format(
                slug=md_escape(r["slug"]),
                nome=md_escape(r["nome"]),
                dom=md_escape(r["dominio_curto"]),
                prov=r["provider"],
                conf=r["confianca"],
                sinal=md_escape(r["sinal"]),
            )
        )
    lines.append("")

    MD_OUT.write_text("\n".join(lines), encoding="utf-8")


def write_csv(rows: list[dict]) -> None:
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = ["slug", "nome", "final_url", "provider", "confianca", "sinal", "cache_used"]
    with CSV_OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({
                "slug": r["slug"],
                "nome": r["nome"],
                "final_url": r["final_url"],
                "provider": r["provider"],
                "confianca": r["confianca"],
                "sinal": r["sinal"],
                "cache_used": r["cache_used"],
            })


def main() -> int:
    if not CSV_IN.exists():
        print(f"missing {CSV_IN}", file=sys.stderr)
        return 2

    rows: list[dict] = []
    totals: Counter[str] = Counter()
    with CSV_IN.open(encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            det, cache_used = classify(raw)
            rows.append({
                "slug": raw.get("slug") or "",
                "nome": raw.get("nome") or "",
                "final_url": raw.get("final_url") or "",
                "dominio_curto": short_domain(raw.get("final_url") or "",
                                              raw.get("dominio") or ""),
                "provider": det.provider,
                "confianca": det.confidence,
                "sinal": det.signal,
                "cache_used": cache_used,
            })
            totals[det.provider] += 1

    write_csv(rows)
    write_report(rows, totals, len(rows))
    print(f"wrote {MD_OUT.relative_to(ROOT)} ({len(rows)} analisados, "
          f"{len(totals)} providers distintos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
