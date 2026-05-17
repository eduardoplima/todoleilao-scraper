-- public_v1.uf_stats + public_v1.municipality_stats
--
-- Mat views agregadas a partir de public_v1.lot_search, que devolvem 1 row por
-- UF (uf_stats) e 1 row por (UF, município) (municipality_stats). Substituem a
-- agregação que o frontend hoje faz em memória após puxar até 2000 rows do
-- lot_search — agregação que silenciosamente subconta quando uma UF passa de
-- 2000 lotes ativos (já ocorre hoje em RJ ~10k, GO ~4.7k, SP ~2k abertos).
--
-- Refresh: mesmo cronograma de lot_search (REFRESH MATERIALIZED VIEW CONCURRENTLY).
--   public_v1_refresh.sql é o lugar canônico — adicionar ambos lá.
--
-- Helpers do frontend (lib/supabase.ts) a serem trocados:
--   - getUfStats(uf)            → SELECT * FROM public_v1.uf_stats WHERE uf = $1
--   - getMunicipalityStats(...) → SELECT * FROM public_v1.municipality_stats
--                                   WHERE uf = $1 AND municipality_ibge_code = $2
--   - getMunicipalitiesByUf(uf) → SELECT municipality_ibge_code, municipality_name,
--                                        total_lots, open_lots
--                                   FROM public_v1.municipality_stats WHERE uf = $1
--   - getDistrictsByMunicipality → jsonb top_districts da municipality_stats

-- ---------------------------------------------------------------------------
-- 1) public_v1.uf_stats
-- ---------------------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS public_v1.uf_stats CASCADE;

CREATE MATERIALIZED VIEW public_v1.uf_stats AS
WITH per_lot AS (
  SELECT uf, current_status, kind, municipality_ibge_code, municipality_name,
         discount_pct
  FROM public_v1.lot_search
  WHERE uf IS NOT NULL
    AND data_quality_flag IS NULL  -- exclui lots com parsing suspeito
),
kind_counts AS (
  SELECT uf, kind, count(*) AS n
  FROM per_lot WHERE current_status = 'aberto'
  GROUP BY uf, kind
),
muni_counts AS (
  SELECT uf, municipality_ibge_code, municipality_name, count(*) AS n
  FROM per_lot WHERE current_status = 'aberto'
    AND municipality_ibge_code IS NOT NULL
  GROUP BY uf, municipality_ibge_code, municipality_name
),
top_kinds_agg AS (
  SELECT uf,
         jsonb_agg(jsonb_build_object('kind', kind, 'count', n)
                   ORDER BY n DESC) FILTER (WHERE rn <= 5) AS top_kinds
  FROM (
    SELECT uf, kind, n,
           row_number() OVER (PARTITION BY uf ORDER BY n DESC) AS rn
    FROM kind_counts
  ) ranked
  GROUP BY uf
),
top_munis_agg AS (
  SELECT uf,
         jsonb_agg(jsonb_build_object(
           'ibge_code', municipality_ibge_code,
           'name', municipality_name,
           'count', n
         ) ORDER BY n DESC) FILTER (WHERE rn <= 10) AS top_municipalities
  FROM (
    SELECT uf, municipality_ibge_code, municipality_name, n,
           row_number() OVER (PARTITION BY uf ORDER BY n DESC) AS rn
    FROM muni_counts
  ) ranked
  GROUP BY uf
)
SELECT
  pl.uf,
  count(*) AS total_lots,
  count(*) FILTER (WHERE current_status = 'aberto') AS open_lots,
  count(*) FILTER (WHERE current_status = 'arrematado') AS sold_lots,
  count(*) FILTER (WHERE current_status = 'suspenso') AS suspended_lots,
  round(avg(discount_pct) FILTER (WHERE discount_pct IS NOT NULL), 1) AS avg_discount_pct,
  round(avg(discount_pct) FILTER (WHERE current_status = 'aberto'
                                    AND discount_pct IS NOT NULL), 1) AS avg_discount_pct_open,
  COALESCE(tk.top_kinds, '[]'::jsonb) AS top_kinds,
  COALESCE(tm.top_municipalities, '[]'::jsonb) AS top_municipalities
FROM per_lot pl
LEFT JOIN top_kinds_agg tk USING (uf)
LEFT JOIN top_munis_agg tm USING (uf)
GROUP BY pl.uf, tk.top_kinds, tm.top_municipalities;

CREATE UNIQUE INDEX uf_stats_uf_idx ON public_v1.uf_stats (uf);

COMMENT ON MATERIALIZED VIEW public_v1.uf_stats IS
  '1 row por UF com counts + avg discount + top 5 kinds + top 10 municípios. '
  'Substitui agregação em memória no frontend (que tinha cap de 2000 rows).';


-- ---------------------------------------------------------------------------
-- 2) public_v1.municipality_stats
-- ---------------------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS public_v1.municipality_stats CASCADE;

CREATE MATERIALIZED VIEW public_v1.municipality_stats AS
WITH per_lot AS (
  SELECT uf, municipality_ibge_code, municipality_name,
         current_status, kind, district, discount_pct
  FROM public_v1.lot_search
  WHERE uf IS NOT NULL AND municipality_ibge_code IS NOT NULL
    AND data_quality_flag IS NULL  -- exclui lots com parsing suspeito
),
kind_counts AS (
  SELECT uf, municipality_ibge_code, kind, count(*) AS n
  FROM per_lot WHERE current_status = 'aberto'
  GROUP BY uf, municipality_ibge_code, kind
),
district_counts AS (
  SELECT uf, municipality_ibge_code, district, count(*) AS n
  FROM per_lot WHERE current_status = 'aberto' AND district IS NOT NULL AND district <> ''
  GROUP BY uf, municipality_ibge_code, district
),
top_kinds_agg AS (
  SELECT uf, municipality_ibge_code,
         jsonb_agg(jsonb_build_object('kind', kind, 'count', n)
                   ORDER BY n DESC) FILTER (WHERE rn <= 5) AS top_kinds
  FROM (
    SELECT uf, municipality_ibge_code, kind, n,
           row_number() OVER (PARTITION BY uf, municipality_ibge_code ORDER BY n DESC) AS rn
    FROM kind_counts
  ) ranked
  GROUP BY uf, municipality_ibge_code
),
top_districts_agg AS (
  SELECT uf, municipality_ibge_code,
         jsonb_agg(jsonb_build_object('district', district, 'count', n)
                   ORDER BY n DESC) FILTER (WHERE rn <= 15) AS top_districts
  FROM (
    SELECT uf, municipality_ibge_code, district, n,
           row_number() OVER (PARTITION BY uf, municipality_ibge_code ORDER BY n DESC) AS rn
    FROM district_counts
  ) ranked
  GROUP BY uf, municipality_ibge_code
)
SELECT
  pl.uf,
  pl.municipality_ibge_code,
  max(pl.municipality_name) AS municipality_name,
  count(*) AS total_lots,
  count(*) FILTER (WHERE current_status = 'aberto') AS open_lots,
  count(*) FILTER (WHERE current_status = 'arrematado') AS sold_lots,
  count(*) FILTER (WHERE current_status = 'suspenso') AS suspended_lots,
  round(avg(discount_pct) FILTER (WHERE discount_pct IS NOT NULL), 1) AS avg_discount_pct,
  round(avg(discount_pct) FILTER (WHERE current_status = 'aberto'
                                    AND discount_pct IS NOT NULL), 1) AS avg_discount_pct_open,
  COALESCE(tk.top_kinds, '[]'::jsonb) AS top_kinds,
  COALESCE(td.top_districts, '[]'::jsonb) AS top_districts
FROM per_lot pl
LEFT JOIN top_kinds_agg tk USING (uf, municipality_ibge_code)
LEFT JOIN top_districts_agg td USING (uf, municipality_ibge_code)
GROUP BY pl.uf, pl.municipality_ibge_code, tk.top_kinds, td.top_districts;

CREATE UNIQUE INDEX municipality_stats_pk_idx
  ON public_v1.municipality_stats (uf, municipality_ibge_code);
CREATE INDEX municipality_stats_uf_open_idx
  ON public_v1.municipality_stats (uf, open_lots DESC);

COMMENT ON MATERIALIZED VIEW public_v1.municipality_stats IS
  '1 row por (UF, município IBGE) com counts + avg discount + top 5 kinds + top 15 districts. '
  'Cobre getMunicipalitiesByUf, getMunicipalityStats e getDistrictsByMunicipality.';


-- ---------------------------------------------------------------------------
-- Grants iguais ao lot_search (PostgREST acessa via anon/auth)
-- ---------------------------------------------------------------------------

GRANT SELECT ON public_v1.uf_stats           TO anon, authenticated, service_role;
GRANT SELECT ON public_v1.municipality_stats TO anon, authenticated, service_role;
