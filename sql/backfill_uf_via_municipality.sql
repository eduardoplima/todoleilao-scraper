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

-- -----------------------------------------------------------------------------
-- 3. Função infer_uf_from_cep: infere UF pelo prefixo CEP (2 dígitos)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.infer_uf_from_cep(p_cep text)
RETURNS char(2)
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
  v_prefix char(2);
BEGIN
  IF p_cep IS NULL OR length(trim(p_cep)) < 5 THEN RETURN NULL; END IF;
  v_prefix := left(regexp_replace(p_cep, '[^0-9]', '', 'g'), 2);
  IF length(v_prefix) < 2 THEN RETURN NULL; END IF;
  RETURN CASE v_prefix
    WHEN '01' THEN 'SP' WHEN '02' THEN 'SP' WHEN '03' THEN 'SP'
    WHEN '04' THEN 'SP' WHEN '05' THEN 'SP' WHEN '06' THEN 'SP'
    WHEN '07' THEN 'SP' WHEN '08' THEN 'SP' WHEN '09' THEN 'SP'
    WHEN '10' THEN 'SP' WHEN '11' THEN 'SP' WHEN '12' THEN 'SP'
    WHEN '13' THEN 'SP' WHEN '14' THEN 'SP' WHEN '15' THEN 'SP'
    WHEN '16' THEN 'SP' WHEN '17' THEN 'SP' WHEN '18' THEN 'SP'
    WHEN '19' THEN 'SP'
    WHEN '20' THEN 'RJ' WHEN '21' THEN 'RJ' WHEN '22' THEN 'RJ'
    WHEN '23' THEN 'RJ' WHEN '24' THEN 'RJ' WHEN '25' THEN 'RJ'
    WHEN '26' THEN 'RJ' WHEN '27' THEN 'RJ' WHEN '28' THEN 'RJ'
    WHEN '29' THEN 'ES'
    WHEN '30' THEN 'MG' WHEN '31' THEN 'MG' WHEN '32' THEN 'MG'
    WHEN '33' THEN 'MG' WHEN '34' THEN 'MG' WHEN '35' THEN 'MG'
    WHEN '36' THEN 'MG' WHEN '37' THEN 'MG' WHEN '38' THEN 'MG'
    WHEN '39' THEN 'MG'
    WHEN '40' THEN 'BA' WHEN '41' THEN 'BA' WHEN '42' THEN 'BA'
    WHEN '43' THEN 'BA' WHEN '44' THEN 'BA' WHEN '45' THEN 'BA'
    WHEN '46' THEN 'BA' WHEN '47' THEN 'BA' WHEN '48' THEN 'BA'
    WHEN '49' THEN 'SE'
    WHEN '50' THEN 'PE' WHEN '51' THEN 'PE' WHEN '52' THEN 'PE'
    WHEN '53' THEN 'PE' WHEN '54' THEN 'PE' WHEN '55' THEN 'PE'
    WHEN '56' THEN 'PE'
    WHEN '57' THEN 'AL'
    WHEN '58' THEN 'PB'
    WHEN '59' THEN 'RN'
    WHEN '60' THEN 'CE' WHEN '61' THEN 'CE' WHEN '62' THEN 'CE'
    WHEN '63' THEN 'CE'
    WHEN '64' THEN 'PI'
    WHEN '65' THEN 'MA'
    WHEN '66' THEN 'PA' WHEN '67' THEN 'PA' WHEN '68' THEN 'PA'
    WHEN '69' THEN 'AM'
    WHEN '70' THEN 'DF' WHEN '71' THEN 'DF' WHEN '72' THEN 'DF'
    WHEN '73' THEN 'DF'
    WHEN '74' THEN 'GO' WHEN '75' THEN 'GO' WHEN '76' THEN 'GO'
    WHEN '77' THEN 'TO'
    WHEN '78' THEN 'MT'
    WHEN '79' THEN 'MS'
    WHEN '80' THEN 'PR' WHEN '81' THEN 'PR' WHEN '82' THEN 'PR'
    WHEN '83' THEN 'PR' WHEN '84' THEN 'PR' WHEN '85' THEN 'PR'
    WHEN '86' THEN 'PR' WHEN '87' THEN 'PR'
    WHEN '88' THEN 'SC' WHEN '89' THEN 'SC'
    WHEN '90' THEN 'RS' WHEN '91' THEN 'RS' WHEN '92' THEN 'RS'
    WHEN '93' THEN 'RS' WHEN '94' THEN 'RS' WHEN '95' THEN 'RS'
    WHEN '96' THEN 'RS' WHEN '97' THEN 'RS' WHEN '98' THEN 'RS'
    WHEN '99' THEN 'RS'
    ELSE NULL
  END;
END;
$$;

-- 4. Aplica CEP-based UF
UPDATE core.address a
SET uf = core.infer_uf_from_cep(a.cep)::core.uf_code, updated_at = now()
WHERE (a.uf IS NULL OR a.uf = '')
  AND a.cep IS NOT NULL
  AND length(trim(a.cep)) >= 5
  AND core.infer_uf_from_cep(a.cep) IS NOT NULL
  AND core.infer_uf_from_cep(a.cep) ~ '^(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)$';

-- 5. Tenta extração de CIDADE do raw_text (padrão "CIDADE - BAIRRO")
--    Match único em municipality → UF inferida.
WITH city_from_dash AS (
  SELECT DISTINCT ON (ad.id) ad.id,
    (
      SELECT uf FROM core.municipality
      WHERE core.unaccent_lite(name) = core.unaccent_lite(
        trim(split_part(ad.raw_text, '-', 1))
      )
      GROUP BY uf
      HAVING count(*) = 1
      LIMIT 1
    ) as uf
  FROM core.address ad
  WHERE (ad.uf IS NULL OR ad.uf = '')
    AND ad.raw_text ~ '^[A-Z].*-.*$'
)
UPDATE core.address a
SET uf = c.uf::core.uf_code, updated_at = now()
FROM city_from_dash c
WHERE a.id = c.id
  AND c.uf IS NOT NULL
  AND c.uf ~ '^(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)$';

COMMIT;

-- Diagnóstico:
SELECT
  count(*) FILTER (WHERE uf IS NULL OR uf = '') AS still_no_uf,
  count(*) FILTER (WHERE uf IS NOT NULL AND uf <> '') AS has_uf,
  count(*) AS total
FROM core.address;
