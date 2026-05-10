-- =============================================================================
-- dedup_auction_spatial.sql
-- One-shot SQL pra limpar inflação histórica em core.auction (1.6×) e
-- core.spatial_unit (1.6×). Bug colateral do pipeline: cada UPSERT do lot
-- criava nova auction/spatial_unit em vez de reusar.
--
-- Mesmo padrão que já corrigi pra core.bid (commit 7cdd19d).
--
-- Aplicar:
--   psql "$SUPABASE_DB_URL" -f sql/dedup_auction_spatial.sql
--
-- Idempotente — re-execução é no-op se nada está duplicado.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- A. Dedup core.auction por (source_id, source_auction_code)
-- -----------------------------------------------------------------------------
-- Estratégia: mantém o `created_at` mais antigo de cada grupo, re-aponta
-- auction_lot.auction_id pra ele, deleta os duplicados.

CREATE TEMP TABLE _auction_keep ON COMMIT DROP AS
SELECT DISTINCT ON (source_id, source_auction_code)
  id AS keep_id, source_id, source_auction_code
FROM core.auction
ORDER BY source_id, source_auction_code, created_at;

UPDATE core.auction_lot al
SET auction_id = k.keep_id
FROM core.auction au
JOIN _auction_keep k
  ON k.source_id = au.source_id AND k.source_auction_code = au.source_auction_code
WHERE al.auction_id = au.id
  AND al.auction_id <> k.keep_id;

-- Tabelas que referenciam auction (ON DELETE CASCADE → não há órfão a tratar):
--   core.auction_lot       (CASCADE, mas re-apontamos acima)
--   core.process_reference (CASCADE)
--   core.legal_note        (CASCADE)
--   core.document          (CASCADE)
-- Re-apontar process_reference pra manter histórico:
UPDATE core.process_reference pr
SET auction_id = k.keep_id
FROM core.auction au
JOIN _auction_keep k
  ON k.source_id = au.source_id AND k.source_auction_code = au.source_auction_code
WHERE pr.auction_id = au.id
  AND pr.auction_id <> k.keep_id;

-- Deleta as auctions duplicadas (cascade limpa qualquer FK órfã restante).
DELETE FROM core.auction au
WHERE EXISTS (
  SELECT 1 FROM _auction_keep k
  WHERE k.source_id = au.source_id
    AND k.source_auction_code = au.source_auction_code
    AND k.keep_id <> au.id
);

-- -----------------------------------------------------------------------------
-- B. UNIQUE constraint em core.auction
-- -----------------------------------------------------------------------------
-- Pré-requisito: passos anteriores deixaram o conjunto consistente.
-- O índice auction_source_code_idx (não-único) é redundante depois disso;
-- DROP é safe porque o UNIQUE também serve como índice de busca.

ALTER TABLE core.auction
  DROP CONSTRAINT IF EXISTS auction_source_code_unique;
ALTER TABLE core.auction
  ADD CONSTRAINT auction_source_code_unique
  UNIQUE (source_id, source_auction_code);

DROP INDEX IF EXISTS core.auction_source_code_idx;

-- -----------------------------------------------------------------------------
-- C. Dedup core.spatial_unit por lot
-- -----------------------------------------------------------------------------
-- Estratégia: pra cada lot_id em lot_unit_link, manter a spatial_unit
-- com `created_at` mais antigo. Re-aponta nada (lot_unit_link já é a
-- ponte; basta deletar os links extras), depois cascada solta os
-- spatial_units / ba_units órfãos.

CREATE TEMP TABLE _su_keep ON COMMIT DROP AS
SELECT DISTINCT ON (lu.lot_id)
  lu.lot_id, su.id AS keep_su_id
FROM core.lot_unit_link lu
JOIN core.spatial_unit su ON su.id = lu.spatial_unit_id
ORDER BY lu.lot_id, su.created_at;

DELETE FROM core.lot_unit_link lu
USING _su_keep k
WHERE lu.lot_id = k.lot_id
  AND lu.spatial_unit_id <> k.keep_su_id;

-- Encumbrances apontam pra ba_unit que apontam pra spatial_unit. Pra
-- ba_units órfãos, encumbrances acompanham (CASCADE em encumbrance).
DELETE FROM core.ba_unit b
WHERE NOT EXISTS (
  SELECT 1 FROM core.lot_unit_link WHERE spatial_unit_id = b.spatial_unit_id
);

-- spatial_units órfãos (sem lot_unit_link).
DELETE FROM core.spatial_unit su
WHERE NOT EXISTS (
  SELECT 1 FROM core.lot_unit_link WHERE spatial_unit_id = su.id
);

COMMIT;

-- -----------------------------------------------------------------------------
-- D. Métricas pós-dedup (chamar manualmente após COMMIT)
-- -----------------------------------------------------------------------------
-- SELECT 'auction' AS t, count(*) FROM core.auction
-- UNION ALL SELECT 'spatial_unit', count(*) FROM core.spatial_unit
-- UNION ALL SELECT 'ba_unit', count(*) FROM core.ba_unit
-- UNION ALL SELECT 'lot_unit_link', count(*) FROM core.lot_unit_link
-- UNION ALL SELECT 'auction_lot', count(*) FROM core.auction_lot;
