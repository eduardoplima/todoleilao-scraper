"""Conta lots criados nas últimas N horas por spider (source).

Usado pelos wrappers de batch (`scripts/run_batch_*.sh`) pra detectar
spider que rodou 0 items (degradação silenciosa). Retorna exit 0 sempre
— os scripts decidem se exit 1 baseado no count delta.

Uso:
    python scripts/spider_run_health.py --since-minutes 60 --host example.com
        → imprime "10" (lots criados nesses minutos pro host)
    python scripts/spider_run_health.py --since-minutes 1440
        → imprime tabela com todos os hosts ativos nas últimas 24h
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg


def count_lots(dsn: str, since_minutes: int, host: str | None) -> int | None:
    interval = f"{int(since_minutes)} minutes"
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        if host:
            cur.execute(
                """
                SELECT count(*) FROM core.auction_lot al
                JOIN core.source s ON s.id = al.source_id
                WHERE al.created_at > now() - interval %s
                  AND s.short_name = %s
                """,
                (interval, host),
            )
            return cur.fetchone()[0]
        cur.execute(
            """
            SELECT s.short_name, count(*) AS n
            FROM core.auction_lot al
            JOIN core.source s ON s.id = al.source_id
            WHERE al.created_at > now() - interval %s
            GROUP BY 1 ORDER BY 2 DESC
            """,
            (interval,),
        )
        rows = cur.fetchall()
        for name, n in rows:
            print(f"{name}\t{n}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since-minutes", type=int, default=1440)
    parser.add_argument("--host", default=None,
                        help="Se passado, imprime só o count desse host (output: número).")
    parser.add_argument("--dsn", default=os.environ.get("SUPABASE_DB_URL"))
    args = parser.parse_args()

    if not args.dsn:
        print("ERR: SUPABASE_DB_URL não definida", file=sys.stderr)
        return 1

    result = count_lots(args.dsn, args.since_minutes, args.host)
    if args.host and result is not None:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
