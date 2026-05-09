-- =============================================================================
-- public_v1_refresh.sql
-- Agendamento do REFRESH MATERIALIZED VIEW de busca.
-- Versão 0.1.0 — 2026-05-09
--
-- Pré-requisito: extensão pg_cron habilitada.
-- No Supabase: Database → Extensions → ativar `pg_cron` (uma vez).
--
-- Aplicar:
--   psql "$SUPABASE_DB_URL" -f sql/public_v1_refresh.sql
--
-- Conferir:
--   SELECT * FROM cron.job;
--   SELECT * FROM cron.job_run_details ORDER BY start_time DESC LIMIT 5;
-- =============================================================================

-- A função CONCURRENTLY exige índice único (já criado em
-- public_v1.lot_search_pk) e não bloqueia leituras durante o refresh.
-- 5 minutos é arbitrário — pode subir para 1 minuto se ingestão for
-- contínua, ou cair para 30 minutos se cron diário do scraper for
-- suficiente.

-- Remove agendamento prévio se existir, antes de re-agendar.
SELECT cron.unschedule(jobid)
  FROM cron.job
 WHERE jobname = 'refresh-public-v1-lot-search';

SELECT cron.schedule(
  'refresh-public-v1-lot-search',
  '*/5 * * * *',
  $$REFRESH MATERIALIZED VIEW CONCURRENTLY public_v1.lot_search;$$
);
