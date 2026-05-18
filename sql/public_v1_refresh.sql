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
--
-- Decisão 2026-05-18: lots de leilão raramente mudam (item já existente é
-- updated incrementalmente; novos só entram durante cron de spiders). Cron
-- 5min era desperdício de Disk IO (~80 min/dia só de refresh, 26.7% do IO
-- budget). Trocamos por:
--   1. 1 refresh/dia às 06:00 UTC (rede de segurança).
--   2. Refresh on-demand no FIM de cada batch script (vide
--      scripts/run_batch_*.sh) — aciona a partir da Fly machine após
--      raspar; garante latência <30min entre crawl e dado no front.

-- Remove agendamento prévio se existir, antes de re-agendar.
SELECT cron.unschedule(jobid)
  FROM cron.job
 WHERE jobname IN (
   'refresh-public-v1-lot-search',
   'refresh-public-v1-stats',
   'refresh-public-v1-daily'
 );

SELECT cron.schedule(
  'refresh-public-v1-daily',
  '0 6 * * *',
  $$
    REFRESH MATERIALIZED VIEW CONCURRENTLY public_v1.lot_search;
    REFRESH MATERIALIZED VIEW CONCURRENTLY public_v1.uf_stats;
    REFRESH MATERIALIZED VIEW CONCURRENTLY public_v1.municipality_stats;
  $$
);
