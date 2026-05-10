-- =============================================================================
-- address_normalization.sql
-- Normaliza core.address.raw_text → (street, number, district, city, uf, cep)
-- e resolve city → core.municipality.ibge_code (match exato + fuzzy pg_trgm).
-- Versão 0.1.0 — 2026-05-10
--
-- Aplicar:
--   psql "$SUPABASE_DB_URL" -f sql/address_normalization.sql
--
-- Backfill:
--   SELECT core.normalize_pending_addresses(5000);
--
-- Diagnóstico:
--   SELECT * FROM core.address_normalization_failures LIMIT 50;
--
-- Pré-requisitos: extensão pg_trgm (já habilitada em todoleilao_ddl.sql).
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- A. Helpers
-- -----------------------------------------------------------------------------

-- Sem extensão `unaccent` no Supabase atual: translate manual dos acentos
-- mais comuns em PT-BR. Cobre nomes de municípios IBGE (testado em amostra).
CREATE OR REPLACE FUNCTION core.unaccent_lite(s text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS $$
  SELECT lower(translate(
    s,
    'áàâãäéèêëíìîïóòôõöúùûüçñÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ',
    'aaaaaeeeeiiiiooooouuuucnaaaaaeeeeiiiiooooouuuucn'
  ));
$$;

-- -----------------------------------------------------------------------------
-- B. Parser de blob de endereço
-- -----------------------------------------------------------------------------
-- Reconhece o template SOLEON (validado em amostra de 30 endereços reais):
--   "Endereço: <street>[, <number>][- <bairro>] Cidade: <city> / <UF> [- CEP: <NNNNN-NNN>]"
-- Variações cobertas:
--   - Com ou sem prefixo "Endereço:" / "Logradouro:" / "End.:".
--   - Sem street (só "Endereço: Cidade: X / UF").
--   - Sem CEP / sem bairro / sem número.

CREATE OR REPLACE FUNCTION core.parse_address_blob(blob text)
RETURNS TABLE (
  parsed_street    text,
  parsed_number    text,
  parsed_district  text,
  parsed_city      text,
  parsed_uf        text,
  parsed_cep       text
) LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
  s       text;
  m       text[];
  rest    text;
  parts   text[];
  pn      text[];
BEGIN
  IF blob IS NULL OR length(trim(blob)) = 0 THEN
    RETURN NEXT;
    RETURN;
  END IF;

  s := regexp_replace(blob, '^\s*(Endereço|Endereco|End\.|Logradouro)\s*:\s*', '', 'i');
  s := regexp_replace(s, '\s+', ' ', 'g');
  s := trim(s);

  -- Padrão principal: "rest Cidade: X / UF [- CEP: NNNNN-NNN]"
  -- O grupo "rest" captura "<street>[, <number>][- <bairro>]".
  m := regexp_match(
    s,
    '^(.*?)(?:\s+-\s+([^-]+?))?\s*Cidade\s*:\s*([^/]+?)\s*/\s*([A-Za-z]{2})\s*(?:-\s*CEP\s*:\s*(\d{5}-?\d{3}))?\s*$',
    'i'
  );

  IF m IS NULL THEN
    -- Sem cidade: devolve só o street se houver
    parsed_street := nullif(s, '');
    RETURN NEXT;
    RETURN;
  END IF;

  rest             := nullif(trim(coalesce(m[1], '')), '');
  parsed_district  := nullif(trim(coalesce(m[2], '')), '');
  parsed_city      := nullif(trim(m[3]), '');
  parsed_uf        := upper(nullif(trim(m[4]), ''));
  -- core.cep é character(8) — sem hífen.
  parsed_cep       := nullif(regexp_replace(coalesce(m[5], ''), '\D', '', 'g'), '');
  IF parsed_cep IS NOT NULL AND length(parsed_cep) <> 8 THEN
    parsed_cep := NULL;
  END IF;

  -- Decompor rest em "street[, number]"
  IF rest IS NOT NULL THEN
    pn := regexp_match(rest, '^(.+?),\s*([0-9SsNn][0-9SsNn/.-]*)\s*$');
    IF pn IS NOT NULL THEN
      parsed_street := nullif(trim(pn[1]), '');
      parsed_number := nullif(trim(pn[2]), '');
    ELSE
      parsed_street := rest;
    END IF;
  END IF;

  RETURN NEXT;
END;
$$;

-- -----------------------------------------------------------------------------
-- C. Match de município (exact + fuzzy pg_trgm)
-- -----------------------------------------------------------------------------
-- Estratégia em 2 passes:
--   1. Match exato sobre nome normalizado (lowercase, sem acentos).
--   2. Trigram similarity ≥ 0.6 dentro da mesma UF.

CREATE OR REPLACE FUNCTION core.match_municipality(p_uf text, p_name text)
RETURNS core.ibge_municipality_code
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
  v_norm  text;
  v_code  core.ibge_municipality_code;
BEGIN
  IF p_uf IS NULL OR p_name IS NULL THEN RETURN NULL; END IF;
  v_norm := core.unaccent_lite(p_name);

  -- Pass 1: exato
  SELECT ibge_code INTO v_code
  FROM core.municipality
  WHERE uf = upper(p_uf)
    AND core.unaccent_lite(name) = v_norm
  LIMIT 1;
  IF v_code IS NOT NULL THEN RETURN v_code; END IF;

  -- Pass 2: trigram (mesma UF, similarity ≥ 0.6)
  SELECT ibge_code INTO v_code
  FROM core.municipality
  WHERE uf = upper(p_uf)
    AND similarity(core.unaccent_lite(name), v_norm) >= 0.6
  ORDER BY similarity(core.unaccent_lite(name), v_norm) DESC
  LIMIT 1;
  IF v_code IS NOT NULL THEN RETURN v_code; END IF;

  -- Fallback DF: o único município IBGE do Distrito Federal é Brasília
  -- (5300108). Nomes como "Samambaia", "Gama", "Ceilândia", "São Sebastião"
  -- são Regiões Administrativas, não municípios. Mapeamos todos para Brasília.
  IF upper(p_uf) = 'DF' THEN
    RETURN '5300108';
  END IF;

  RETURN NULL;
END;
$$;

-- -----------------------------------------------------------------------------
-- D. Normaliza um endereço individual
-- -----------------------------------------------------------------------------
-- Idempotente: pula endereços já com municipality_code preenchido.
-- Atualiza street_name / number / district / cep / uf / municipality_code / geom
-- (geom recebe centroide do município como fallback quando NULL).

CREATE OR REPLACE FUNCTION core.normalize_address(p_address_id uuid)
RETURNS boolean
LANGUAGE plpgsql AS $$
DECLARE
  v_addr   record;
  v_blob   text;
  v_p      record;
  v_code   core.ibge_municipality_code;
BEGIN
  SELECT * INTO v_addr FROM core.address WHERE id = p_address_id;
  IF NOT FOUND OR v_addr.municipality_code IS NOT NULL THEN
    RETURN false;
  END IF;

  -- Prefere raw_text; senão concatena outros campos.
  v_blob := coalesce(
    nullif(v_addr.raw_text, ''),
    concat_ws(' ',
      nullif(v_addr.street_name, ''),
      nullif(v_addr.number, ''),
      nullif(v_addr.district, ''),
      nullif(v_addr.complement, '')
    )
  );

  SELECT * INTO v_p FROM core.parse_address_blob(v_blob);

  IF v_p.parsed_uf IS NOT NULL AND v_p.parsed_city IS NOT NULL THEN
    v_code := core.match_municipality(v_p.parsed_uf, v_p.parsed_city);
  END IF;

  UPDATE core.address SET
    street_name       = COALESCE(v_p.parsed_street,    street_name),
    number            = COALESCE(v_p.parsed_number,    number),
    district          = COALESCE(v_p.parsed_district,  district),
    cep               = COALESCE(v_p.parsed_cep,       cep),
    uf                = COALESCE(v_p.parsed_uf,        uf),
    municipality_code = COALESCE(v_code,               municipality_code),
    geom = COALESCE(
      geom,
      (SELECT centroid FROM core.municipality WHERE ibge_code = v_code)
    ),
    geocoding_source  = COALESCE(geocoding_source,
      CASE WHEN v_code IS NOT NULL THEN 'municipality_centroid' END
    ),
    updated_at        = now()
  WHERE id = p_address_id;

  RETURN v_code IS NOT NULL;
END;
$$;

-- -----------------------------------------------------------------------------
-- E. Batch
-- -----------------------------------------------------------------------------

-- Batch iterativo. Para evitar loops onde os mesmos N pendentes nunca
-- resolvem (ex.: blob impossível), usa coluna `updated_at` como
-- "marca de tentativa": só processa endereços com updated_at < cutoff.
CREATE OR REPLACE FUNCTION core.normalize_pending_addresses(p_limit int DEFAULT 5000)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_id        uuid;
  v_processed int := 0;
  v_resolved  int := 0;
  v_cutoff    timestamptz := now() - interval '1 hour';
BEGIN
  FOR v_id IN
    SELECT id FROM core.address
    WHERE municipality_code IS NULL
      AND (updated_at IS NULL OR updated_at < v_cutoff)
    ORDER BY created_at
    LIMIT p_limit
  LOOP
    IF core.normalize_address(v_id) THEN
      v_resolved := v_resolved + 1;
    ELSE
      -- Marca tentativa pra não re-iterar antes do cutoff
      UPDATE core.address SET updated_at = now() WHERE id = v_id;
    END IF;
    v_processed := v_processed + 1;
  END LOOP;
  RETURN jsonb_build_object(
    'processed', v_processed,
    'resolved',  v_resolved,
    'pending',   (SELECT count(*) FROM core.address WHERE municipality_code IS NULL)
  );
END;
$$;

-- -----------------------------------------------------------------------------
-- F. Trigger: normaliza automaticamente novos addresses
-- -----------------------------------------------------------------------------
-- Roda em AFTER INSERT/UPDATE OF raw_text, fora da transação principal pra
-- não bloquear o pipeline (chamada via PERFORM, ignora retorno).

CREATE OR REPLACE FUNCTION core.normalize_address_trg() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.municipality_code IS NULL AND coalesce(NEW.raw_text, '') <> '' THEN
    PERFORM core.normalize_address(NEW.id);
  END IF;
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS address_normalize_trg ON core.address;
CREATE TRIGGER address_normalize_trg
AFTER INSERT OR UPDATE OF raw_text ON core.address
FOR EACH ROW EXECUTE FUNCTION core.normalize_address_trg();

-- -----------------------------------------------------------------------------
-- G. View de falhas (revisão manual)
-- -----------------------------------------------------------------------------

CREATE OR REPLACE VIEW core.address_normalization_failures AS
SELECT
  a.id,
  a.uf,
  a.street_name,
  a.district,
  a.complement,
  a.raw_text,
  a.created_at
FROM core.address a
WHERE a.municipality_code IS NULL
  AND coalesce(a.raw_text, a.street_name, a.district, a.complement) IS NOT NULL
ORDER BY a.created_at DESC;

COMMIT;

-- -----------------------------------------------------------------------------
-- H. Cron diário (defesa em profundidade — trigger já cobre o fluxo síncrono)
-- -----------------------------------------------------------------------------

SELECT cron.unschedule(jobid) FROM cron.job
WHERE jobname = 'normalize-pending-addresses';

SELECT cron.schedule(
  'normalize-pending-addresses',
  '*/15 * * * *',
  $$SELECT core.normalize_pending_addresses(5000);$$
);
