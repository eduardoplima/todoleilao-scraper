-- =============================================================================
-- dedup_keys.sql — pré-computa chaves de dedup em core.auction_lot
-- Versão 0.1.0 — 2026-05-18
--
-- Contexto: a query do _link_canonical em pipelines_supabase.py (1× por lot
-- UPSERT) consumia 19.8% do Disk IO do Supabase porque materializava todos
-- os 35k lots da tabela + extraía regexp_match da `description` toda vez,
-- antes de filtrar por addr_key/reg_key.
--
-- Solução: pré-calcular `address_key` e `registry_key` em colunas indexadas
-- de `core.auction_lot`. Lookup vira indexed B-tree em vez de seq scan.
-- Esperado: 549ms → 3-10ms por dedup query.
--
-- Aplicar:
--   psql "$SUPABASE_DB_URL" -f sql/dedup_keys.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1) Colunas + índices partial
-- ---------------------------------------------------------------------------

ALTER TABLE core.auction_lot
  ADD COLUMN IF NOT EXISTS address_key  text,
  ADD COLUMN IF NOT EXISTS registry_key text;

COMMENT ON COLUMN core.auction_lot.address_key IS
  'Chave determinística para dedup inter-fontes: '
  'unaccent_lite(cep || ''|'' || street_name || ''|'' || number). '
  'Computada em Python (pipelines_supabase._address_key) e gravada no '
  'UPSERT. NULL quando o lot não tem endereço suficiente.';

COMMENT ON COLUMN core.auction_lot.registry_key IS
  'Número de matrícula CRI extraído da description via regex. '
  'NULL quando description não contém matrícula. Bate exatamente com o '
  'Python pipelines_supabase._registry_key().';

CREATE INDEX IF NOT EXISTS idx_auction_lot_address_key
  ON core.auction_lot (address_key)
  WHERE address_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_auction_lot_registry_key
  ON core.auction_lot (registry_key)
  WHERE registry_key IS NOT NULL;


-- ---------------------------------------------------------------------------
-- 2) Backfill — usa exatamente a mesma expressão do _link_canonical original
-- ---------------------------------------------------------------------------

WITH lot_addr AS (
  SELECT
    al.id AS lot_id,
    -- Mesma expressão da query antiga de _link_canonical
    core.unaccent_lite(
      coalesce(ad.cep::text, '')   || '|' ||
      coalesce(ad.street_name, '') || '|' ||
      coalesce(ad.number, '')
    ) AS addr_key_raw,
    -- Mesma regex
    (regexp_match(al.description,
      'matr[ií]cula?[^0-9]{0,20}(?:n[ºo°.]?\s*)?(\d{1,3}(?:\.\d{3})*|\d{3,8})',
      'i'))[1] AS reg_key_raw
  FROM core.auction_lot al
  LEFT JOIN core.lot_unit_link lu ON lu.lot_id = al.id
  LEFT JOIN core.spatial_unit  su ON su.id    = lu.spatial_unit_id
  LEFT JOIN core.address       ad ON ad.id    = su.address_id
)
UPDATE core.auction_lot al
SET
  address_key  = NULLIF(la.addr_key_raw, '||'),
  registry_key = NULLIF(replace(la.reg_key_raw, '.', ''), '')
FROM lot_addr la
WHERE la.lot_id = al.id
  AND (al.address_key  IS DISTINCT FROM NULLIF(la.addr_key_raw, '||')
    OR al.registry_key IS DISTINCT FROM NULLIF(replace(la.reg_key_raw, '.', ''), ''));


-- ---------------------------------------------------------------------------
-- 3) Sanity
-- ---------------------------------------------------------------------------

DO $$
DECLARE
  total bigint;
  with_addr bigint;
  with_reg bigint;
BEGIN
  SELECT
    count(*),
    count(*) FILTER (WHERE address_key  IS NOT NULL),
    count(*) FILTER (WHERE registry_key IS NOT NULL)
  INTO total, with_addr, with_reg
  FROM core.auction_lot;
  RAISE NOTICE 'auction_lot: total=%, with_address_key=% (%.1f%%), with_registry_key=% (%.1f%%)',
    total, with_addr, 100.0 * with_addr / total, with_reg, 100.0 * with_reg / total;
END $$;
