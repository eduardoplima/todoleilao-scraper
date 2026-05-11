-- core.lot_canonical_link — dedup inter-fontes.
--
-- Mantém vínculo de "mesma propriedade" entre 2 lots (uma do leiloeiro e
-- outro do banco portal). A regra é:
--   canonical = lote do leiloeiro (URL direto pro detalhe do lote)
--   secondary = lote do banco (frequentemente SPA sem URL persistente)
--
-- A view `public_v1.lot_search` filtra secondary out; `public_v1.lot_detail`
-- expõe `alternate_sources jsonb` com os secondaries do canonical.
--
-- A inserção é feita pelo pipeline (`pipelines_supabase._link_canonical`)
-- ao detectar 2 lots com mesma chave (endereço normalizado + matrícula CRI
-- quando ambos disponíveis).

CREATE TABLE IF NOT EXISTS core.lot_canonical_link (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_lot_id    uuid NOT NULL REFERENCES core.auction_lot (id) ON DELETE CASCADE,
  secondary_lot_id    uuid NOT NULL REFERENCES core.auction_lot (id) ON DELETE CASCADE,
  -- Tipo de match: 'address+registry' (alto sinal), 'process+address',
  -- 'process' (judicial), 'address' (fallback baixa confidence).
  match_kind          text NOT NULL,
  confidence          smallint NOT NULL CHECK (confidence BETWEEN 0 AND 100),
  created_at          timestamptz NOT NULL DEFAULT now(),
  -- 1 secondary só pode apontar pra 1 canonical (evita ciclos).
  CONSTRAINT lot_canonical_link_secondary_unique UNIQUE (secondary_lot_id),
  -- Não permitir auto-loops.
  CONSTRAINT lot_canonical_link_no_self CHECK (canonical_lot_id <> secondary_lot_id)
);

CREATE INDEX IF NOT EXISTS lot_canonical_link_canonical_idx
  ON core.lot_canonical_link (canonical_lot_id);

COMMENT ON TABLE core.lot_canonical_link IS
  'Dedup inter-fontes: associa lots do banco (secondary) ao lot oficial do leiloeiro (canonical) quando matched por (address + registry) ou (process + address). View public_v1.lot_search filtra secondaries.';
