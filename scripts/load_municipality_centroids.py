"""Carga pontual de centroides + multipolígonos + área dos municípios IBGE.

Usa `geobr` (IPEA) que envelopa o shapefile oficial da Malha Municipal.
Roda uma vez (idempotente — re-execução só atualiza o que mudar).

Uso:
    uv sync --group geo
    set -a && source .env && set +a
    uv run python scripts/load_municipality_centroids.py [--year 2022] [--simplified]

Resolve as issues:
    - geom=0% em public_v1.lot_search → fallback `centroid` populado.
    - Mapa de calor por município (Plano Mestre §8.2 #4).
    - RPC public_v1.lots_near (precisa de geometria).
    - Mapa do detalhe /lote/[handle].

NÃO resolve:
    - Geocoding fino (endereço exato dentro do município).
    - Issues de occupancy/amenities/court/auctioneer no lot_detail.

Pesado (geopandas + fiona). Não vai pra produção; rodar local-only.
"""
from __future__ import annotations

import argparse
import os
import sys
from contextlib import closing
from decimal import Decimal

import geobr
import psycopg
from shapely import wkb


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2022, help="ano da malha IBGE (default: 2022)")
    parser.add_argument(
        "--simplified",
        action="store_true",
        help="usa shapefile simplificado (~10x menor; precisão suficiente para centroide e mapas web)",
    )
    parser.add_argument(
        "--dsn",
        default=os.environ.get("SUPABASE_DB_URL"),
        help="dsn (default: $SUPABASE_DB_URL)",
    )
    args = parser.parse_args()

    if not args.dsn:
        print("ERR: defina SUPABASE_DB_URL ou use --dsn", file=sys.stderr)
        return 1

    print(f"[1/4] Baixando malha municipal {args.year} (simplified={args.simplified}) via geobr…")
    gdf = geobr.read_municipality(year=args.year, simplified=args.simplified)
    print(f"      {len(gdf)} municípios baixados")

    # Garante CRS 4326 (WGS84). geobr default é SIRGAS 2000 EPSG:4674; reprojetar.
    if gdf.crs is None or str(gdf.crs).upper() not in {"EPSG:4326"}:
        print(f"[2/4] Reprojetando {gdf.crs} → EPSG:4326…")
        gdf = gdf.to_crs(epsg=4326)
    else:
        print("[2/4] CRS já em EPSG:4326")

    # Equal-area projection (Albers Brasil) p/ calcular área em km² confiável
    print("[3/4] Calculando centroides + área (km²)…")
    gdf_eq = gdf.to_crs("ESRI:102033")  # South America Albers Equal Area
    gdf["centroid_4326"] = gdf_eq.geometry.centroid.to_crs(4326)
    gdf["area_km2"] = (gdf_eq.geometry.area / 1_000_000.0).round(2)

    # Normaliza ibge_code: geobr usa column `code_muni` como int64 (7 dígitos).
    rows: list[tuple[str, bytes, bytes, float]] = []
    for _, row in gdf.iterrows():
        ibge_code = str(int(row["code_muni"])).zfill(7)
        # PostGIS aceita EWKB. shapely.wkb.dumps inclui SRID se configurado;
        # alternativa robusta: ST_GeomFromEWKB(BYTEA) com SRID embutido.
        geom_wkb = wkb.dumps(row.geometry, srid=4326, hex=False, output_dimension=2)
        cent_wkb = wkb.dumps(row["centroid_4326"], srid=4326, hex=False, output_dimension=2)
        rows.append((ibge_code, geom_wkb, cent_wkb, Decimal(f"{float(row['area_km2']):.2f}")))

    print(f"[4/4] UPDATE em core.municipality (5570 rows, batch via staging temp)…")
    with closing(psycopg.connect(args.dsn)) as conn:
        with conn.cursor() as cur:
            # Tabela temp evita 5570 round-trips de UPDATE
            cur.execute(
                """
                CREATE TEMP TABLE _muni_geom (
                  ibge_code text PRIMARY KEY,
                  geom      bytea,
                  centroid  bytea,
                  area_km2  numeric(12,2)
                ) ON COMMIT DROP
                """
            )
            with cur.copy(
                "COPY _muni_geom (ibge_code, geom, centroid, area_km2) FROM STDIN (FORMAT BINARY)"
            ) as copy:
                copy.set_types(["text", "bytea", "bytea", "numeric"])
                for r in rows:
                    copy.write_row(r)

            cur.execute(
                """
                UPDATE core.municipality m SET
                  geom     = ST_GeomFromEWKB(t.geom),
                  centroid = ST_GeomFromEWKB(t.centroid),
                  area_km2 = COALESCE(t.area_km2, m.area_km2)
                FROM _muni_geom t
                WHERE m.ibge_code = t.ibge_code
                """
            )
            print(f"      {cur.rowcount} municípios atualizados")
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FILTER (WHERE centroid IS NOT NULL) AS w_centroid,
                       count(*) FILTER (WHERE geom IS NOT NULL)     AS w_geom,
                       count(*) FILTER (WHERE area_km2 IS NOT NULL) AS w_area,
                       count(*) AS total
                FROM core.municipality
                """
            )
            wc, wg, wa, t = cur.fetchone()
            print(
                f"\n=== core.municipality pós-carga ===\n"
                f"  centroid: {wc}/{t} ({wc*100//t}%)\n"
                f"  geom:     {wg}/{t} ({wg*100//t}%)\n"
                f"  area_km2: {wa}/{t} ({wa*100//t}%)"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
