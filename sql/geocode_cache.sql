-- =============================================================================
-- geocode_cache.sql
-- Cache local de respostas do geocoder externo, evita re-fetch e respeita
-- a regra de uso do Nominatim ("no significant uses without caching").
-- Versão 0.1.0 — 2026-05-10
-- =============================================================================

CREATE TABLE IF NOT EXISTS core.geocode_cache (
  query_hash       text PRIMARY KEY,                  -- sha256(provider || normalized_query)
  query            text NOT NULL,                      -- query como enviada (pra debug)
  provider         text NOT NULL,                      -- 'nominatim' | 'maptiler' | ...
  found            boolean NOT NULL,                   -- false = "no result", evita re-tentar
  lat              numeric(10, 7),
  lng              numeric(10, 7),
  confidence       core.confidence,                    -- 0..1, do importance/score do provider
  raw              jsonb,                              -- resposta crua pra auditoria
  fetched_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS geocode_cache_provider_fetched_idx
  ON core.geocode_cache (provider, fetched_at DESC);

CREATE INDEX IF NOT EXISTS geocode_cache_found_idx
  ON core.geocode_cache (found) WHERE found = true;

COMMENT ON TABLE core.geocode_cache IS
  'Cache de geocoding por (provider, query). Idempotente: o worker '
  'consulta antes de chamar API externa.';
