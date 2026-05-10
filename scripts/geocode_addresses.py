"""Geocoding fino dos endereços via Nominatim/OSM.

Substitui o `geom = centroide municipal` (precisão de cidade inteira) por
ponto exato do endereço (precisão de rua/número), permitindo plotar pins
distintos no mapa do front.

Uso:
    set -a && source .env && set +a
    uv run python scripts/geocode_addresses.py [--limit 100] [--rate 1.0]

Filosofia:
  - Nominatim: gratuito, rate-limit 1 req/s, exige User-Agent identificável.
  - Cache local em core.geocode_cache: evita re-fetch (regra de uso do OSM).
  - Threshold de confiança: só atualiza geom quando importance >= 0.4.
    Abaixo disso, mantém o centroide municipal (que é equivalente em
    qualidade ao "achei só a cidade" do Nominatim).
  - Idempotente: re-execução só processa o que ainda não foi tentado.

Roda local (não vai pra produção). Quando volume crescer, migrar pra
Maptiler ou self-hosted Nominatim (Docker).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from contextlib import closing

import httpx
import psycopg

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "TodoLeilao/0.1 (eplima.cc@gmail.com)"  # Nominatim policy
DEFAULT_TIMEOUT = 15
MIN_CONFIDENCE_FOR_UPDATE = 0.40  # abaixo disso, fica com centroide


def build_query(addr: dict) -> str:
    """Monta a string de busca do Nominatim a partir do address row."""
    parts = []
    street = (addr.get("street_name") or "").strip()
    number = (addr.get("number") or "").strip()
    if street:
        if number and number.lower() not in {"s/n", "sn", "sem numero", "0"}:
            parts.append(f"{street}, {number}")
        else:
            parts.append(street)
    district = (addr.get("district") or "").strip()
    if district:
        parts.append(district)
    city = (addr.get("municipality_name") or "").strip()
    if city:
        parts.append(city)
    uf = (addr.get("uf") or "").strip()
    if uf:
        parts.append(uf)
    parts.append("Brasil")
    return ", ".join(p for p in parts if p)


def query_hash(provider: str, query: str) -> str:
    norm = query.lower().strip()
    return hashlib.sha256(f"{provider}::{norm}".encode("utf-8")).hexdigest()


def call_nominatim(client: httpx.Client, query: str) -> dict | None:
    r = client.get(
        NOMINATIM_URL,
        params={
            "q": query,
            "format": "json",
            "limit": 1,
            "countrycodes": "br",
            "addressdetails": 1,
        },
        headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt"},
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()
    results = r.json()
    return results[0] if results else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200,
                        help="máximo de endereços a processar nesta execução")
    parser.add_argument("--rate", type=float, default=1.0,
                        help="req/s pro Nominatim (default 1; >1 viola TOS)")
    parser.add_argument("--dsn", default=os.environ.get("SUPABASE_DB_URL"))
    args = parser.parse_args()

    if not args.dsn:
        print("ERR: SUPABASE_DB_URL não definida", file=sys.stderr)
        return 1
    if args.rate > 1.0:
        print(f"ERR: rate {args.rate} viola TOS do Nominatim (max 1.0)", file=sys.stderr)
        return 1

    interval = 1.0 / args.rate
    stats = {"processed": 0, "cache_hit": 0, "geocoded": 0, "skipped_low_conf": 0,
             "no_result": 0, "errors": 0}

    with closing(psycopg.connect(args.dsn)) as conn, \
         httpx.Client() as http:

        # 1. Pega pendentes
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, street_name, number, district, municipality_code, uf,
                       (SELECT name FROM core.municipality m WHERE m.ibge_code = a.municipality_code) AS municipality_name
                FROM core.address a
                WHERE a.municipality_code IS NOT NULL
                  AND a.street_name IS NOT NULL
                  AND (a.geocoding_source IS NULL
                       OR a.geocoding_source = 'municipality_centroid')
                ORDER BY (a.number IS NOT NULL) DESC,  -- precisas primeiro
                         a.created_at DESC
                LIMIT %s
            """, (args.limit,))
            cols = [d[0] for d in cur.description]
            pending = [dict(zip(cols, row)) for row in cur.fetchall()]

        print(f"[geocode] {len(pending)} endereços pendentes (limit {args.limit}, rate {args.rate}/s)")
        if not pending:
            return 0

        last_call = 0.0
        for i, addr in enumerate(pending, 1):
            query = build_query(addr)
            qhash = query_hash("nominatim", query)

            # Cache hit?
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT found, lat, lng, confidence FROM core.geocode_cache WHERE query_hash = %s",
                    (qhash,),
                )
                row = cur.fetchone()

            if row is not None:
                found, lat, lng, conf = row
                stats["cache_hit"] += 1
                source = "cache"
                raw = None
            else:
                # respeita rate limit
                gap = time.monotonic() - last_call
                if gap < interval:
                    time.sleep(interval - gap)
                last_call = time.monotonic()

                try:
                    result = call_nominatim(http, query)
                except Exception as e:
                    stats["errors"] += 1
                    print(f"  [{i}/{len(pending)}] ERR {e!r} :: {query[:80]}")
                    continue

                if result is None:
                    found, lat, lng, conf, raw = False, None, None, None, None
                    stats["no_result"] += 1
                else:
                    found = True
                    lat = float(result["lat"])
                    lng = float(result["lon"])
                    importance = float(result.get("importance") or 0)
                    # Bumps adicionais: address-level results no Nominatim têm importance
                    # baixa pra ruas/casas. Combina com presença de "house_number" no
                    # addressdetails pra subir confidence.
                    conf = importance
                    addrd = result.get("address") or {}
                    if addrd.get("house_number"):
                        conf = max(conf, 0.85)
                    elif addrd.get("road"):
                        conf = max(conf, 0.55)
                    conf = round(min(max(conf, 0), 1), 2)
                    raw = result
                source = "nominatim"

                # grava cache
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO core.geocode_cache
                            (query_hash, query, provider, found, lat, lng, confidence, raw)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (query_hash) DO NOTHING
                        """,
                        (qhash, query, "nominatim", found, lat, lng, conf,
                         json.dumps(raw) if raw else None),
                    )
                conn.commit()

            stats["processed"] += 1

            # Decide se atualiza o address
            if not found:
                stats["no_result"] += (0 if source == "cache" else 0)  # já contou no fetch
                continue
            if conf is None or float(conf) < MIN_CONFIDENCE_FOR_UPDATE:
                stats["skipped_low_conf"] += 1
                continue

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE core.address
                    SET geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                        geocoding_source = %s,
                        geocoding_confidence = %s,
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (lng, lat, "nominatim", float(conf), addr["id"]),
                )
            conn.commit()
            stats["geocoded"] += 1

            if i % 25 == 0 or i == len(pending):
                print(f"  [{i}/{len(pending)}] {source:9s} conf={conf!s:5s} :: {addr.get('municipality_name','?')[:25]:25s} :: {query[:60]}")

    print("\n=== stats ===")
    for k, v in stats.items():
        print(f"  {k:20s} {v}")

    # Refresh MV (geom mudou)
    with closing(psycopg.connect(args.dsn, autocommit=True)) as conn, conn.cursor() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY public_v1.lot_search")
    print("\npublic_v1.lot_search refreshed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
