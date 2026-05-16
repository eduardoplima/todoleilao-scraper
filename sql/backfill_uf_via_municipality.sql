-- =============================================================================
-- backfill_uf_via_municipality.sql
-- Frente 2: Backfill UF via lookup em core.municipality (único resultado = sem ambiguidade).
-- Só processa endereços que ainda têm uf IS NULL após Frente 1.
--
-- Estratégia:
--   1. Extrai candidatos de cidade de padrões textuais BR:
--      - "em <CIDADE>", "no <CIDADE>", "na <CIDADE>", "município de <CIDADE>"
--      - "CIDADE: <CIDADE>"
--   2. Para cada candidato: lookup exato em core.municipality via unaccent_lite.
--   3. Se resultado único → usa UF; se ambíguo → NULL (não preenche errado).
--
-- Aplique após backfill_uf_from_text.sql.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Função infer_uf_from_city_lookup
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.infer_uf_from_city_lookup(p_text text)
RETURNS char(2)
LANGUAGE plpgsql STABLE PARALLEL SAFE AS $$
DECLARE
  v_uf_set text[] := ARRAY[
    'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA',
    'MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN',
    'RS','RO','RR','SC','SP','SE','TO'
  ];
  v_candidate text;
  v_uf text;
  v_count int;
BEGIN
  IF p_text IS NULL OR length(trim(p_text)) = 0 THEN
    RETURN NULL;
  END IF;

  -- Extrai candidatos de cidade em sequência de padrões
  FOR v_candidate IN
    -- Padrão A: "município de X", "no município de X"
    SELECT trim(m[1])
    FROM regexp_matches(p_text,
      'munic[íi]pio\s*(?:de\s+|:\s*)([A-ZÀ-Úa-zà-ú][A-ZÀ-Úa-zà-ú\s.'']{2,40}?)(?:\s*,|\s*\.|$|\s*\()',
      'gi') m
    WHERE length(trim(m[1])) >= 3

    UNION ALL

    -- Padrão B: "em X," ou "na X," ou "no X," (seguido de vírgula ou ponto)
    SELECT trim(m[1])
    FROM regexp_matches(p_text,
      '(?:^|\s)(?:em|na|no)\s+([A-ZÀ-Úa-zA-Záéíóúâêîôûãõàèìòù][A-ZÀ-Úa-zA-Záéíóúâêîôûãõàèìòù\s.'']{2,40}?)\s*(?:,|\.|$)',
      'gi') m
    WHERE length(trim(m[1])) >= 3
      AND lower(trim(m[1])) NOT IN ('que','uma','um','que','pra','por','com','sem','seu','sua')

    UNION ALL

    -- Padrão C: "CIDADE: X" (padrão leffa-style)
    SELECT trim(m[1])
    FROM regexp_matches(p_text,
      'CIDADE\s*:\s*([A-ZÀ-Úa-zà-ú][A-ZÀ-Úa-zà-ú\s.'']{2,40}?)(?:\s*/|\s*,|\s*$|\s*\|)',
      'gi') m
    WHERE length(trim(m[1])) >= 3

  LOOP
    -- Lookup exato em municipality
    SELECT uf, count(*) OVER ()
    INTO v_uf, v_count
    FROM core.municipality
    WHERE core.unaccent_lite(name) = core.unaccent_lite(v_candidate)
    LIMIT 2;  -- pega até 2 pra detectar ambiguidade

    -- Conta resultados
    SELECT count(*) INTO v_count
    FROM core.municipality
    WHERE core.unaccent_lite(name) = core.unaccent_lite(v_candidate);

    IF v_count = 1 THEN
      -- Resultado único: sem ambiguidade, retorna UF
      SELECT uf INTO v_uf
      FROM core.municipality
      WHERE core.unaccent_lite(name) = core.unaccent_lite(v_candidate);
      RETURN v_uf::char(2);
    END IF;
    -- Se 0 ou >1 resultados: continua para próximo candidato
  END LOOP;

  RETURN NULL;
END;
$$;

-- -----------------------------------------------------------------------------
-- 2. UPDATE: aplica lookup apenas onde UF ainda é NULL após Frente 1
-- -----------------------------------------------------------------------------
WITH inferred AS (
  SELECT DISTINCT ON (ad.id)
    ad.id,
    core.infer_uf_from_city_lookup(
      COALESCE(al.description,'') || ' ' ||
      COALESCE(al.source_url,'') || ' ' ||
      COALESCE(ad.raw_text,'')
    ) AS uf
  FROM core.address ad
  JOIN core.spatial_unit su ON su.address_id = ad.id
  JOIN core.lot_unit_link lu ON lu.spatial_unit_id = su.id
  JOIN core.auction_lot al ON al.id = lu.lot_id
  WHERE ad.uf IS NULL OR ad.uf = ''
)
UPDATE core.address a
SET
  uf = i.uf::core.uf_code,
  updated_at = now()
FROM inferred i
WHERE a.id = i.id
  AND i.uf IS NOT NULL
  AND i.uf ~ '^(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)$';

COMMIT;

-- Diagnóstico:
SELECT
  count(*) FILTER (WHERE uf IS NULL OR uf = '') AS still_no_uf,
  count(*) FILTER (WHERE uf IS NOT NULL AND uf <> '') AS has_uf,
  count(*) AS total
FROM core.address;
