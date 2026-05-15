-- spider_run_health.sql
--
-- View + log diário pra detectar spider degradado (0 lots em 24h+).
--
-- Aplicação:
--   psql "$SUPABASE_DB_URL" -f sql/spider_run_health.sql
--
-- Uso operacional:
--   -- Lista spiders ativos com 0 lots nas últimas 24h
--   SELECT * FROM core.spider_run_health WHERE last_24h_count = 0;
--
--   -- Tendência semanal por spider
--   SELECT short_name, day, lots
--     FROM core.spider_health_log
--    WHERE day > current_date - 14
--    ORDER BY short_name, day DESC;

-- ---------------------------------------------------------------------------
-- 1) View core.spider_run_health (snapshot atual)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW core.spider_run_health AS
SELECT
    s.short_name,
    s.id AS source_id,
    count(al.id) AS total_lots,
    count(al.id) FILTER (WHERE al.current_status = 'aberto') AS open_lots,
    count(al.id) FILTER (WHERE al.created_at > now() - interval '24 hours') AS last_24h_count,
    count(al.id) FILTER (WHERE al.created_at > now() - interval '7 days') AS last_7d_count,
    max(al.created_at) AS last_lot_at,
    max(al.last_seen_at) AS last_seen_at
FROM core.source s
LEFT JOIN core.auction_lot al ON al.source_id = s.id
GROUP BY s.id, s.short_name;

COMMENT ON VIEW core.spider_run_health IS
  'Snapshot de saúde por spider. last_24h_count = 0 num spider com total > 100 sinaliza degradação.';

GRANT SELECT ON core.spider_run_health TO anon, authenticated, service_role;

-- ---------------------------------------------------------------------------
-- 2) Log diário (série temporal)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS core.spider_health_log (
    day date NOT NULL,
    source_id uuid NOT NULL REFERENCES core.source(id) ON DELETE CASCADE,
    short_name text NOT NULL,
    lots integer NOT NULL,
    open_lots integer NOT NULL,
    last_lot_at timestamp with time zone,
    PRIMARY KEY (day, source_id)
);

COMMENT ON TABLE core.spider_health_log IS
  'Snapshot diário (pg_cron 12:00 UTC) da spider_run_health. Série temporal pra detectar regressão.';

-- ---------------------------------------------------------------------------
-- 3) Função de captura diária
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.capture_spider_health()
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_count integer := 0;
BEGIN
    INSERT INTO core.spider_health_log (day, source_id, short_name, lots, open_lots, last_lot_at)
    SELECT
        current_date AS day,
        s.id AS source_id,
        s.short_name,
        count(al.id) FILTER (WHERE al.created_at > now() - interval '24 hours') AS lots,
        count(al.id) FILTER (WHERE al.current_status = 'aberto') AS open_lots,
        max(al.created_at) AS last_lot_at
    FROM core.source s
    LEFT JOIN core.auction_lot al ON al.source_id = s.id
    GROUP BY s.id, s.short_name
    ON CONFLICT (day, source_id) DO UPDATE
       SET lots = EXCLUDED.lots,
           open_lots = EXCLUDED.open_lots,
           last_lot_at = EXCLUDED.last_lot_at;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

-- ---------------------------------------------------------------------------
-- 4) Agendamento pg_cron — 12:00 UTC diário
-- ---------------------------------------------------------------------------

SELECT cron.unschedule(jobid)
  FROM cron.job
 WHERE jobname = 'capture-spider-health';

SELECT cron.schedule(
  'capture-spider-health',
  '0 12 * * *',
  $$SELECT core.capture_spider_health();$$
);
