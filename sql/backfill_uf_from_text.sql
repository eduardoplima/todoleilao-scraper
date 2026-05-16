-- =============================================================================
-- backfill_uf_from_text.sql
-- Frente 1: Backfill UF em core.address usando regex sobre texto livre.
-- Estratégia:
--   1. Usa a função existente core.try_extract_city_uf (padrão "Cidade/UF")
--      sobre raw_text, description e source_url via LATERAL.
--   2. Complementa com core.infer_uf_from_text para padrões adicionais:
--      ",UF," (endereço CSV), "UF" precedido de espaço ou "|", etc.
--   3. Prefere raw_text > description > source_url.
--
-- Aplique:
--   psql "$SUPABASE_DB_URL" -f sql/backfill_uf_from_text.sql
--
-- Ou via Python:
--   python -c "open('sql/backfill_uf_from_text.sql').read()"  (ver scripts/run_backfill_uf.py)
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Função auxiliar infer_uf_from_text
--    Tenta vários padrões regex em ordem de confiabilidade.
--    Retorna a UF válida mais provável ou NULL.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.infer_uf_from_text(p_text text)
RETURNS char(2)
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
  v_uf_set text[] := ARRAY[
    'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA',
    'MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN',
    'RS','RO','RR','SC','SP','SE','TO'
  ];
  v_matches text[][];
  m text[];
  v_uf text;
BEGIN
  IF p_text IS NULL OR length(trim(p_text)) = 0 THEN
    RETURN NULL;
  END IF;

  -- Padrão 1: "Cidade / UF" ou "Cidade - UF" ou "Cidade– UF"
  -- (já coberto por try_extract_city_uf, mas repetido aqui para completar)
  -- Pega ÚLTIMO match (mais à direita) — geralmente é o do lote
  SELECT upper(trim(m2[2])) INTO v_uf
  FROM (
    SELECT m2, position(m2[1] in p_text) as pos
    FROM regexp_matches(p_text,
      '([A-ZÀ-Úa-zà-ú][A-ZÀ-Úa-zà-ú\s.''\-]{2,40})\s*[/\-–]\s*([A-Z]{2})(?:\s|\.|$|,|"|<)',
      'g') m2
    WHERE upper(trim(m2[2])) = ANY(v_uf_set)
  ) matches
  ORDER BY pos DESC
  LIMIT 1;
  IF v_uf IS NOT NULL THEN RETURN v_uf; END IF;

  -- Padrão 2: ", UF," ou ", UF, CEP" (endereço CSV: "Rua X, Cidade, UF, CEP")
  SELECT upper(trim(m2[1])) INTO v_uf
  FROM regexp_matches(p_text,
    ',\s*([A-Z]{2})\s*(?:,\s*CEP|$|\s*\||\s*\.)',
    'g') m2
  WHERE upper(trim(m2[1])) = ANY(v_uf_set)
  LIMIT 1;
  IF v_uf IS NOT NULL THEN RETURN v_uf; END IF;

  -- Padrão 3: "UF" precedido por espaço ou "|" e seguido de fim/pontuação
  -- Ex: "Brasília DF | Matrícula"
  SELECT upper(trim(m2[1])) INTO v_uf
  FROM regexp_matches(p_text,
    '(?:^|\s|\|)\s*([A-Z]{2})\s*(?:\s|\||$|\.|\,)',
    'g') m2
  WHERE upper(trim(m2[1])) = ANY(v_uf_set)
    -- Filtrar falsos positivos comuns (siglas de órgãos, etc.)
    AND upper(trim(m2[1])) NOT IN ('DE','DA','DO','EM','NO','NA','AS','OS','UF','BR')
  LIMIT 1;
  IF v_uf IS NOT NULL THEN RETURN v_uf; END IF;

  RETURN NULL;
END;
$$;

-- -----------------------------------------------------------------------------
-- 2. UPDATE em core.address: preenche uf onde está NULL
--    Usa try_extract_city_uf (via LATERAL, para o padrão principal)
--    e infer_uf_from_text como fallback (texto combinado).
-- -----------------------------------------------------------------------------
WITH inferred AS (
  SELECT DISTINCT ON (ad.id)
    ad.id,
    COALESCE(
      r1.uf,   -- raw_text via try_extract_city_uf
      r2.uf,   -- description via try_extract_city_uf
      r3.uf,   -- source_url via try_extract_city_uf
      core.infer_uf_from_text(
        COALESCE(al.description,'') || ' ' ||
        COALESCE(al.source_url,'') || ' ' ||
        COALESCE(ad.raw_text,'')
      )
    ) AS uf
  FROM core.address ad
  JOIN core.spatial_unit su ON su.address_id = ad.id
  JOIN core.lot_unit_link lu ON lu.spatial_unit_id = su.id
  JOIN core.auction_lot al ON al.id = lu.lot_id
  LEFT JOIN LATERAL core.try_extract_city_uf(ad.raw_text) r1 ON TRUE
  LEFT JOIN LATERAL core.try_extract_city_uf(al.description) r2 ON TRUE
  LEFT JOIN LATERAL core.try_extract_city_uf(al.source_url) r3 ON TRUE
  WHERE ad.uf IS NULL OR ad.uf = ''
)
UPDATE core.address a
SET
  uf = i.uf,
  updated_at = now()
FROM inferred i
WHERE a.id = i.id
  AND i.uf IS NOT NULL;

COMMIT;

-- Diagnóstico pós-execução:
SELECT
  count(*) FILTER (WHERE uf IS NULL OR uf = '') AS still_no_uf,
  count(*) FILTER (WHERE uf IS NOT NULL AND uf <> '') AS has_uf,
  count(*) AS total
FROM core.address;
