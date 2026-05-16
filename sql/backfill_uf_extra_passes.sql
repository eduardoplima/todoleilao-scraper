-- =============================================================================
-- backfill_uf_extra_passes.sql
-- Passes adicionais de backfill UF (Frentes 2+):
--   1. core.infer_uf_from_state_name: match de nome de estado por extenso
--   2. UPDATE por IBGE 7-dígitos em raw_text
--   3. UPDATE de UF a partir de source_url (slug -UF/)
--   4. city-before-dash lookup ("BETIM - BAIRRO" → UF via municipality)
--
-- Aplicar após backfill_uf_from_text.sql e backfill_uf_via_municipality.sql.
-- =============================================================================

BEGIN;

-- 1. Função: infer UF pelo nome de estado por extenso (Paraná, São Paulo, etc.)
CREATE OR REPLACE FUNCTION core.infer_uf_from_state_name(p_text text)
RETURNS char(2)
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
  v_norm text;
BEGIN
  IF p_text IS NULL OR length(trim(p_text)) = 0 THEN RETURN NULL; END IF;
  v_norm := core.unaccent_lite(p_text);
  -- Ordem: estados compostos primeiro (evitar match parcial)
  IF v_norm ~  '\mrio grande do sul\M' THEN RETURN 'RS'; END IF;
  IF v_norm ~  '\mrio grande do norte\M' THEN RETURN 'RN'; END IF;
  IF v_norm ~  '\mrio de janeiro\M' THEN RETURN 'RJ'; END IF;
  IF v_norm ~  '\mminas gerais\M' THEN RETURN 'MG'; END IF;
  IF v_norm ~  '\msanta catarina\M' THEN RETURN 'SC'; END IF;
  IF v_norm ~  '\mmato grosso do sul\M' THEN RETURN 'MS'; END IF;
  IF v_norm ~  '\mmato grosso\M' AND v_norm !~ '\mmato grosso do sul\M' THEN RETURN 'MT'; END IF;
  IF v_norm ~  '\mespirito santo\M' THEN RETURN 'ES'; END IF;
  IF v_norm ~  '\mdistrito federal\M' THEN RETURN 'DF'; END IF;
  IF v_norm ~  '\msao paulo\M' THEN RETURN 'SP'; END IF;
  IF v_norm ~  '\mparana\M' THEN RETURN 'PR'; END IF;
  IF v_norm ~  '\mpernambuco\M' THEN RETURN 'PE'; END IF;
  IF v_norm ~  '\mmaranhao\M' THEN RETURN 'MA'; END IF;
  IF v_norm ~  '\mparaiba\M' THEN RETURN 'PB'; END IF;
  IF v_norm ~  '\mgoias\M' THEN RETURN 'GO'; END IF;
  IF v_norm ~  '\mceara\M' THEN RETURN 'CE'; END IF;
  IF v_norm ~  '\mbahia\M' THEN RETURN 'BA'; END IF;
  IF v_norm ~  '\mpiaui\M' THEN RETURN 'PI'; END IF;
  IF v_norm ~  '\malagoas\M' THEN RETURN 'AL'; END IF;
  IF v_norm ~  '\msergipe\M' THEN RETURN 'SE'; END IF;
  IF v_norm ~  '\mtocantins\M' THEN RETURN 'TO'; END IF;
  IF v_norm ~  '\mrondonia\M' THEN RETURN 'RO'; END IF;
  IF v_norm ~  '\mamazonas\M' THEN RETURN 'AM'; END IF;
  IF v_norm ~  '\mamapa\M' THEN RETURN 'AP'; END IF;
  IF v_norm ~  '\mroraima\M' THEN RETURN 'RR'; END IF;
  IF v_norm ~  '\macre\M' THEN RETURN 'AC'; END IF;
  -- "Para" é ambíguo (Paraná, Paraíba, Pará); só retorna PA se explícito "Pará"
  IF v_norm ~  '\mpara\M' AND v_norm !~ '\m(parana|paraib)\M' THEN RETURN 'PA'; END IF;
  RETURN NULL;
END;
$$;

-- 2. Aplica infer_uf_from_state_name sobre texto combinado
WITH inferred AS (
  SELECT DISTINCT ON (ad.id)
    ad.id,
    core.infer_uf_from_state_name(
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
SET uf = i.uf::core.uf_code, updated_at = now()
FROM inferred i
WHERE a.id = i.id
  AND i.uf IS NOT NULL
  AND i.uf ~ '^(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)$';

-- 3. Fix por raw_text = 7-dígitos IBGE code
UPDATE core.address a
SET
  uf = m.uf::core.uf_code,
  municipality_code = a.raw_text::core.ibge_municipality_code,
  updated_at = now()
FROM core.municipality m
WHERE (a.uf IS NULL OR a.uf = '')
  AND a.raw_text ~ '^[0-9]{7}$'
  AND m.ibge_code = a.raw_text;

-- 4. Fix por source_url: último -UF/ válido no slug
WITH inferred AS (
  SELECT DISTINCT ON (ad.id)
    ad.id,
    COALESCE(
      r3.uf,
      core.infer_uf_from_text(al.source_url)
    ) AS uf
  FROM core.address ad
  JOIN core.spatial_unit su ON su.address_id = ad.id
  JOIN core.lot_unit_link lu ON lu.spatial_unit_id = su.id
  JOIN core.auction_lot al ON al.id = lu.lot_id
  LEFT JOIN LATERAL core.try_extract_city_uf(al.source_url) r3 ON TRUE
  WHERE ad.uf IS NULL OR ad.uf = ''
  ORDER BY ad.id, al.created_at DESC
)
UPDATE core.address a
SET uf = i.uf::core.uf_code, updated_at = now()
FROM inferred i
WHERE a.id = i.id
  AND i.uf IS NOT NULL
  AND i.uf ~ '^(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)$';

COMMIT;

-- Diagnóstico final:
SELECT
  count(*) FILTER (WHERE uf IS NULL OR uf = '') AS still_no_uf,
  count(*) FILTER (WHERE uf IS NOT NULL AND uf <> '') AS has_uf,
  count(*) AS total
FROM core.address;
