"""Auditoria diária de qualidade dos lotes — alerta % suspeitos por spider.

Conta, em janela rolante de N dias (default 7), quantos lotes ATIVOS
por `core.source.short_name` têm `data_quality_flag` preenchido. Quando
o ratio passa de THRESHOLD_PCT (default 1%), emite WARNING e retorna
exit code != 0.

Uso em CI / cron:
    .venv/bin/python3 scripts/data_quality_audit.py
    .venv/bin/python3 scripts/data_quality_audit.py --window-days 14 --threshold 2.0

Saída JSON (`--json`) facilita integração com webhook (Slack, Sentry).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

import psycopg


@dataclass
class Row:
    host: str
    total: int
    flagged: int

    @property
    def pct(self) -> float:
        return 100.0 * self.flagged / self.total if self.total else 0.0


def audit(
    dsn: str, *, window_days: int, threshold_pct: float, min_lots: int
) -> tuple[list[Row], list[Row]]:
    """Retorna (todos, ofensores) — ofensores = ratio > threshold AND total >= min_lots."""
    sql = f"""
        SELECT s.short_name AS host,
               count(*) AS total,
               count(*) FILTER (
                 WHERE al.data_quality_flag IS NOT NULL
               ) AS flagged
        FROM core.auction_lot al
        JOIN core.source s ON s.id = al.source_id
        WHERE al.last_seen_at > now() - interval '{int(window_days)} days'
          AND al.current_status IN ('aberto','futuro')
        GROUP BY s.short_name
        HAVING count(*) >= %s
        ORDER BY 3::float / NULLIF(count(*),0) DESC NULLS LAST, count(*) DESC
    """
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.execute(sql, (min_lots,))
        rows = [Row(*r) for r in cur.fetchall()]
    offenders = [r for r in rows if r.pct > threshold_pct]
    return rows, offenders


def main() -> int:
    p = argparse.ArgumentParser(description="Audita data_quality_flag por host.")
    p.add_argument("--window-days", type=int, default=7,
                   help="Janela rolante (default 7d).")
    p.add_argument("--threshold", type=float, default=1.0,
                   help="% de flaggados acima do qual emite alerta (default 1.0).")
    p.add_argument("--min-lots", type=int, default=20,
                   help="Hosts com menos lots ativos que isso são ignorados "
                        "(ruído estatístico).")
    p.add_argument("--json", action="store_true",
                   help="Output em JSON para integração com webhook.")
    args = p.parse_args()

    dsn = os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        print("SUPABASE_DB_URL não setado", file=sys.stderr)
        return 2

    rows, offenders = audit(
        dsn,
        window_days=args.window_days,
        threshold_pct=args.threshold,
        min_lots=args.min_lots,
    )

    if args.json:
        payload = {
            "window_days": args.window_days,
            "threshold_pct": args.threshold,
            "totals": {"total_lots": sum(r.total for r in rows),
                       "total_flagged": sum(r.flagged for r in rows)},
            "offenders": [
                {"host": o.host, "total": o.total, "flagged": o.flagged,
                 "pct": round(o.pct, 2)} for o in offenders
            ],
        }
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"Janela: últimos {args.window_days} dias | Threshold: {args.threshold}% "
              f"| Min lots/host: {args.min_lots}")
        print(f"{'HOST':<40} {'TOTAL':>8} {'FLAG':>6} {'PCT':>7}")
        for r in rows:
            mark = "  ⚠" if r.pct > args.threshold else ""
            print(f"{r.host:<40} {r.total:>8} {r.flagged:>6} {r.pct:>6.2f}%{mark}")

    if offenders:
        print(file=sys.stderr)
        for o in offenders:
            print(
                f"WARNING: {o.host} acima do threshold: "
                f"{o.pct:.2f}% ({o.flagged}/{o.total})",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
