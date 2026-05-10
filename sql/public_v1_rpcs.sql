-- =============================================================================
-- public_v1_rpcs.sql
-- RPCs (funções remotas) expostas via PostgREST sob o schema public_v1.
-- Versão 0.1.0 — 2026-05-10
--
-- Aplicar:
--   psql "$SUPABASE_DB_URL" -f sql/public_v1_rpcs.sql
--
-- Convenções:
--   - Funções declaradas como STABLE PARALLEL SAFE quando puramente leitura.
--   - GRANT EXECUTE para anon e authenticated (PostgREST exige).
--   - Nomes de parâmetros começam com `p_` para evitar colisão com colunas.
--   - PostgREST chama via POST /rest/v1/rpc/<name> com JSON body.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- A. lots_near(lat, lng, radius_km, limit) — busca por proximidade
-- -----------------------------------------------------------------------------
-- Caso de uso: "Imóveis perto de você" (geolocalização do navegador) e
-- "Imóveis no raio de N km do bairro X" (geocoder de input do usuário).
--
-- Precisão: hoje os lots usam centroide do município como `geom` (carga IBGE
-- via geobr). Suficiente pra raios ≥ 1km. Geocoding fino (ponto exato do
-- endereço) entra como upgrade quando alguma feature exigir.
--
-- Performance: usa operador KNN (`<->`) em GIST sobre lot_search.geom_gix.
-- ST_DWithin no filtro pra evitar cálculo de distância em lots distantes.
-- Cast geography apenas para que o radius esteja em metros (geometry usa
-- graus em SRID 4326). Pra 917 lots roda em <5ms.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public_v1.lots_near(
  p_lat        double precision,
  p_lng        double precision,
  p_radius_km  double precision DEFAULT 50,
  p_limit      integer          DEFAULT 50
)
RETURNS TABLE (
  lot_id                  uuid,
  lot_number              text,
  source_url              text,
  current_status          core.lot_status,
  appraisal_value         core.brl,
  scraped_at              timestamptz,
  kind                    core.unit_kind,
  useful_area             core.area_m2,
  private_area            core.area_m2,
  total_area              core.area_m2,
  bedrooms                smallint,
  bathrooms               smallint,
  parking_spots           smallint,
  uf                      core.uf_code,
  municipality_ibge_code  core.ibge_municipality_code,
  municipality_name       text,
  district                text,
  geom                    extensions.geometry(Point, 4326),
  next_round_number       smallint,
  next_round_at           timestamptz,
  minimum_bid             core.brl,
  discount_pct            numeric,
  thumb_url               text,
  slug                    text,
  distance_km             numeric
)
LANGUAGE sql STABLE PARALLEL SAFE
AS $$
  WITH point AS (
    SELECT extensions.ST_SetSRID(extensions.ST_MakePoint(p_lng, p_lat), 4326) AS g
  )
  SELECT
    s.lot_id, s.lot_number, s.source_url, s.current_status, s.appraisal_value,
    s.scraped_at, s.kind, s.useful_area, s.private_area, s.total_area,
    s.bedrooms, s.bathrooms, s.parking_spots,
    s.uf, s.municipality_ibge_code, s.municipality_name, s.district, s.geom,
    s.next_round_number, s.next_round_at, s.minimum_bid, s.discount_pct,
    s.thumb_url, s.slug,
    ROUND(
      (extensions.ST_Distance(s.geom::extensions.geography, p.g::extensions.geography) / 1000.0)::numeric,
      2
    ) AS distance_km
  FROM public_v1.lot_search s, point p
  WHERE s.geom IS NOT NULL
    AND extensions.ST_DWithin(
          s.geom::extensions.geography,
          p.g::extensions.geography,
          p_radius_km * 1000.0
        )
  ORDER BY s.geom <-> p.g
  LIMIT p_limit;
$$;

GRANT EXECUTE ON FUNCTION public_v1.lots_near(double precision, double precision, double precision, integer)
  TO anon, authenticated;

COMMIT;
