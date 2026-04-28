-- =============================================================================
-- raw_schema.sql
-- Repositório de Leilões de Imóveis — schema "raw"
-- Versão 0.1.0 — 26 abr 2026
--
-- Schema "raw" é a camada de aterrissagem dos scrapers. Append-only,
-- versionado por parser, com payloads em JSONB para flexibilidade.
-- Nada aqui tem foreign keys para "core" — raw vive sozinho. As pontes
-- são feitas pela camada de transformação (dbt) que lê de raw e escreve
-- em core.
--
-- Princípios:
--   1. APPEND-ONLY. Nunca UPDATE, nunca DELETE (exceto purga de TTL).
--      Cada visita do scraper gera linha nova. Histórico é o ativo.
--   2. SEM FK para core. Raw é independente; pode existir sem core.
--   3. PROVENIÊNCIA SEMPRE. Toda linha tem source_id, scraped_at,
--      parser_version. Bug no parser? Reprocessa daqui.
--   4. JSONB GENEROSO. Capture tudo que parecer útil, normalize depois.
--      Espaço é barato; perder informação no scrape é caro.
--   5. R2 PARA HTML. O HTML bruto vai para Cloudflare R2 (chave em
--      raw_html_r2_key). Aqui guardamos só o ponteiro e metadados.
--
-- Pré-requisitos:
--   PostgreSQL >= 14, schema core já criado (apenas para reusar tipos
--   como sha256_hex; raw NÃO tem FK para core).
--   Extensões: pgcrypto (para gen_random_uuid).
--
-- Convenções:
--   - PKs: uuid via gen_random_uuid()
--   - Datas: SEMPRE timestamptz em UTC
--   - JSON: jsonb (não json) para indexação e operadores
-- =============================================================================


-- A. SETUP =====================================================================

CREATE SCHEMA IF NOT EXISTS raw;
SET search_path TO raw, extensions, public;

COMMENT ON SCHEMA raw IS
  'Camada de aterrissagem dos scrapers. Append-only. Sem FKs para core.';


-- B. ENUMs LOCAIS ==============================================================

CREATE TYPE raw.fetch_status AS ENUM (
  'success',           -- 200, conteúdo válido recebido
  'http_error',        -- 4xx, 5xx
  'timeout',           -- timeout de rede
  'blocked',           -- 403/captcha/rate limit
  'parse_error',       -- recebeu HTML mas parser falhou
  'redirect_loop',
  'dns_error',
  'unknown'
);

CREATE TYPE raw.parse_status AS ENUM (
  'pending',           -- snapshot capturado, aguardando parse
  'success',           -- parser extraiu todos os campos esperados
  'partial',           -- parser extraiu alguns campos, outros faltaram
  'failed',            -- parser não conseguiu extrair nada útil
  'skipped'            -- decisão deliberada de não parsear (ex: 404)
);

CREATE TYPE raw.entity_kind AS ENUM (
  'auction_listing',   -- página de listagem (lista de lotes)
  'auction_lot',       -- página de detalhe de lote
  'auction_event',     -- página de evento de leilão (data/leiloeiro)
  'document_pdf',      -- edital, laudo (binário, hash apenas)
  'image',             -- foto (binário, hash apenas)
  'sitemap',           -- sitemap XML
  'search_result',     -- página de busca/filtro
  'other'
);


-- C. TABELAS PRINCIPAIS ========================================================

-- C.1 fetch_event: cada requisição HTTP feita pelo scraper.
-- Mais granular que o scrape_event de core: aqui registramos TODA tentativa,
-- inclusive falhas. core.scrape_event só recebe os sucessos materializados.
CREATE TABLE raw.fetch_event (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_short_name   text NOT NULL,                  -- "zuk", "megaleiloes" (referência fraca)
  url                 text NOT NULL,
  url_hash            char(64) NOT NULL,              -- sha256 da URL canonicalizada (dedup)
  entity_kind         raw.entity_kind NOT NULL,
  fetched_at          timestamptz NOT NULL DEFAULT now(),
  -- HTTP
  http_status         smallint,
  http_method         text NOT NULL DEFAULT 'GET',
  request_headers     jsonb,                          -- headers enviados (User-Agent etc.)
  response_headers    jsonb,                          -- headers recebidos (úteis: ETag, Last-Modified)
  response_size_bytes bigint,
  duration_ms         integer,
  -- Conteúdo (ponteiro para R2, não o blob)
  raw_content_r2_key  text,                           -- "raw/zuk/2026/04/27/abc123.html.gz"
  raw_content_sha256  char(64),                       -- sha256 do conteúdo bruto
  content_encoding    text,                           -- "gzip", "br", "identity"
  content_type        text,                           -- "text/html", "application/pdf"
  -- Status
  fetch_status        raw.fetch_status NOT NULL,
  error_message       text,
  -- Scraper que rodou
  scraper_name        text NOT NULL,                  -- "zuk_lot_scraper"
  scraper_version     text NOT NULL,                  -- semver/git sha
  scraper_run_id      uuid,                           -- agrupa fetches de uma mesma execução
  -- Auditoria
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX fetch_event_source_idx       ON raw.fetch_event (source_short_name);
CREATE INDEX fetch_event_url_hash_idx     ON raw.fetch_event (url_hash);
CREATE INDEX fetch_event_fetched_at_idx   ON raw.fetch_event (fetched_at DESC);
CREATE INDEX fetch_event_status_idx       ON raw.fetch_event (fetch_status)
  WHERE fetch_status <> 'success';                    -- índice parcial para análise de erros
CREATE INDEX fetch_event_entity_kind_idx  ON raw.fetch_event (entity_kind);
CREATE INDEX fetch_event_run_idx          ON raw.fetch_event (scraper_run_id)
  WHERE scraper_run_id IS NOT NULL;

COMMENT ON TABLE raw.fetch_event IS
  'Toda requisição HTTP do scraper. Append-only. Sucessos e falhas.';
COMMENT ON COLUMN raw.fetch_event.raw_content_r2_key IS
  'Caminho no Cloudflare R2. Padrão: raw/{source}/{YYYY}/{MM}/{DD}/{sha256}.{ext}.gz';

-- C.2 parsed_payload: resultado do parsing de um fetch_event.
-- Um fetch pode ter múltiplos parses (versões diferentes do parser ao longo do tempo).
CREATE TABLE raw.parsed_payload (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fetch_event_id      uuid NOT NULL REFERENCES raw.fetch_event (id) ON DELETE RESTRICT,
  parser_name         text NOT NULL,                  -- "zuk_lot_parser"
  parser_version      text NOT NULL,                  -- semver/git sha
  parsed_at           timestamptz NOT NULL DEFAULT now(),
  parse_status        raw.parse_status NOT NULL,
  payload             jsonb,                           -- TODOS os campos extraídos
  schema_version      text,                            -- versão do JSON schema esperado
  fields_extracted    smallint,                        -- contador para quality monitoring
  fields_expected     smallint,
  parse_warnings      jsonb,                           -- avisos não-fatais do parser
  parse_error         text,                            -- stack trace ou mensagem se failed
  -- Auditoria
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (fetch_event_id, parser_name, parser_version)
);
CREATE INDEX parsed_payload_fetch_idx     ON raw.parsed_payload (fetch_event_id);
CREATE INDEX parsed_payload_parser_idx    ON raw.parsed_payload (parser_name, parser_version);
CREATE INDEX parsed_payload_status_idx    ON raw.parsed_payload (parse_status);
CREATE INDEX parsed_payload_parsed_at_idx ON raw.parsed_payload (parsed_at DESC);
-- Índice GIN para queries do tipo "todas as páginas onde o parser achou um número CNJ"
CREATE INDEX parsed_payload_payload_gin   ON raw.parsed_payload USING GIN (payload jsonb_path_ops);

COMMENT ON TABLE raw.parsed_payload IS
  'Resultado do parser sobre um fetch_event. Múltiplas versões do parser podem coexistir.';

-- C.3 normalization_event: registra a tentativa de promover um parsed_payload
-- para o schema core. Útil para diagnosticar quando algo "ficou em raw" e
-- não chegou em core (lote rejeitado por validação, conflito de chaves, etc.).
CREATE TABLE raw.normalization_event (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  parsed_payload_id     uuid NOT NULL REFERENCES raw.parsed_payload (id) ON DELETE RESTRICT,
  normalizer_name       text NOT NULL,
  normalizer_version    text NOT NULL,
  attempted_at          timestamptz NOT NULL DEFAULT now(),
  outcome               text NOT NULL CHECK (outcome IN (
                          'created',          -- novo registro em core
                          'updated',          -- registro existente atualizado
                          'unchanged',        -- nenhuma mudança detectada
                          'rejected',         -- falhou validação
                          'deferred',         -- aguarda dependência
                          'error'             -- erro inesperado
                        )),
  -- IDs gerados/afetados em core (referência fraca, sem FK)
  core_lot_id           uuid,
  core_unit_id          uuid,
  core_auction_id       uuid,
  -- Diagnóstico
  rejection_reason      text,
  conflict_with_id      uuid,                          -- ID em core que causou conflito
  diff_summary          jsonb,                          -- {"campos_alterados": [...]}
  error_message         text,
  created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX norm_event_payload_idx   ON raw.normalization_event (parsed_payload_id);
CREATE INDEX norm_event_outcome_idx   ON raw.normalization_event (outcome);
CREATE INDEX norm_event_attempted_idx ON raw.normalization_event (attempted_at DESC);
CREATE INDEX norm_event_lot_idx       ON raw.normalization_event (core_lot_id)
  WHERE core_lot_id IS NOT NULL;

COMMENT ON TABLE raw.normalization_event IS
  'Tentativas de promover parsed_payload para core. Reconciliação ao vivo.';

-- C.4 external_source_fetch: snapshots de fontes externas (IBGE, BCB, CNJ, CNPJ).
-- Separado de fetch_event porque a semântica é diferente: são puxadas
-- agendadas, não orientadas a leilões.
CREATE TABLE raw.external_source_fetch (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_kind         text NOT NULL,                  -- "ibge_sidra", "bcb_sgs", "cnj_datajud"
  series_or_endpoint  text NOT NULL,                  -- "ipca", "selic_diaria", "/processos/buscar"
  reference_period    text,                           -- "2026-04", "2022", "diario"
  fetched_at          timestamptz NOT NULL DEFAULT now(),
  request_url         text NOT NULL,
  request_params      jsonb,
  http_status         smallint,
  payload             jsonb,                          -- payload já parseado (geralmente JSON nativo)
  payload_sha256      char(64),
  raw_content_r2_key  text,                           -- backup do payload bruto se grande
  fetch_status        raw.fetch_status NOT NULL,
  error_message       text,
  scraper_name        text NOT NULL,
  scraper_version     text NOT NULL,
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ext_fetch_source_idx         ON raw.external_source_fetch (source_kind, series_or_endpoint);
CREATE INDEX ext_fetch_period_idx         ON raw.external_source_fetch (reference_period);
CREATE INDEX ext_fetch_fetched_at_idx     ON raw.external_source_fetch (fetched_at DESC);
CREATE INDEX ext_fetch_payload_gin        ON raw.external_source_fetch USING GIN (payload jsonb_path_ops);

COMMENT ON TABLE raw.external_source_fetch IS
  'Snapshots de IBGE, BCB, CNJ, CNPJ aberto, etc. Auditável para releases.';

-- C.5 scraper_run: registro de uma execução completa do scraper.
-- Útil para métricas (quantos fetches, taxa de sucesso, duração total).
CREATE TABLE raw.scraper_run (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scraper_name        text NOT NULL,
  scraper_version     text NOT NULL,
  started_at          timestamptz NOT NULL DEFAULT now(),
  ended_at            timestamptz,
  trigger_kind        text NOT NULL CHECK (trigger_kind IN (
                        'manual', 'cron', 'api', 'backfill'
                      )),
  config              jsonb,                          -- parâmetros da execução
  -- Métricas (preenchidas no final)
  total_fetches       integer,
  successful_fetches  integer,
  failed_fetches      integer,
  parsed_lots         integer,
  promoted_to_core    integer,
  status              text CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
  notes               text,
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX scraper_run_started_idx ON raw.scraper_run (started_at DESC);
CREATE INDEX scraper_run_status_idx  ON raw.scraper_run (status);
CREATE INDEX scraper_run_name_idx    ON raw.scraper_run (scraper_name);


-- D. PARTICIONAMENTO (opcional, para depois) ===================================
-- Quando fetch_event passar de ~10M linhas, vale particionar por mês:
--   ALTER TABLE raw.fetch_event ... PARTITION BY RANGE (fetched_at);
-- Por ora, deixamos como tabela única — premature optimization.


-- E. PURGA E TTL ==============================================================
-- Política: fetch_event e seus payloads bem-sucedidos retêm 18 meses.
-- Após isso, conteúdo no R2 é deletado por lifecycle policy do bucket;
-- a linha aqui mantém só metadados (raw_content_r2_key passa a apontar
-- para algo que não existe mais — ok, é evidência histórica de proveniência).

-- Função utilitária para invalidar referências R2 expiradas (chamada por cron):
CREATE OR REPLACE FUNCTION raw.expire_r2_references(retention_months int DEFAULT 18)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  affected int;
BEGIN
  UPDATE raw.fetch_event
     SET raw_content_r2_key = NULL
   WHERE raw_content_r2_key IS NOT NULL
     AND fetched_at < (now() - make_interval(months => retention_months));
  GET DIAGNOSTICS affected = ROW_COUNT;
  RETURN affected;
END;
$$;

COMMENT ON FUNCTION raw.expire_r2_references IS
  'Anula raw_content_r2_key em fetches > N meses. Chamar via cron mensal.';


-- F. VIEWS DE CONVENIÊNCIA ====================================================

-- F.1 Último parse bem-sucedido por fetch_event
CREATE VIEW raw.v_latest_parse AS
  SELECT DISTINCT ON (fetch_event_id)
    fetch_event_id,
    id              AS parsed_payload_id,
    parser_name,
    parser_version,
    parsed_at,
    parse_status,
    payload
  FROM raw.parsed_payload
  WHERE parse_status IN ('success', 'partial')
  ORDER BY fetch_event_id, parsed_at DESC;

COMMENT ON VIEW raw.v_latest_parse IS
  'Último parse bem-sucedido por fetch. Útil para a transformação dbt.';

-- F.2 Métricas de saúde do scraper nas últimas 24h
CREATE VIEW raw.v_scraper_health_24h AS
  SELECT
    source_short_name,
    scraper_name,
    count(*)                                            AS total,
    count(*) FILTER (WHERE fetch_status = 'success')    AS sucessos,
    count(*) FILTER (WHERE fetch_status = 'http_error') AS http_errors,
    count(*) FILTER (WHERE fetch_status = 'blocked')    AS blocked,
    count(*) FILTER (WHERE fetch_status = 'timeout')    AS timeouts,
    round(
      100.0 * count(*) FILTER (WHERE fetch_status = 'success') / NULLIF(count(*), 0),
      2
    )                                                   AS success_rate_pct,
    avg(duration_ms) FILTER (WHERE fetch_status = 'success')::int AS avg_ms
  FROM raw.fetch_event
  WHERE fetched_at > now() - interval '24 hours'
  GROUP BY source_short_name, scraper_name
  ORDER BY total DESC;

COMMENT ON VIEW raw.v_scraper_health_24h IS
  'Painel de saúde dos scrapers nas últimas 24h.';

-- F.3 Backlog de parsing (fetches sem parse bem-sucedido)
CREATE VIEW raw.v_parse_backlog AS
  SELECT
    fe.id              AS fetch_event_id,
    fe.source_short_name,
    fe.entity_kind,
    fe.url,
    fe.fetched_at,
    fe.raw_content_r2_key,
    coalesce(
      (SELECT max(pp.parsed_at) FROM raw.parsed_payload pp WHERE pp.fetch_event_id = fe.id),
      'never'::text::timestamptz
    ) AS last_parse_attempt
  FROM raw.fetch_event fe
  WHERE fe.fetch_status = 'success'
    AND NOT EXISTS (
      SELECT 1 FROM raw.parsed_payload pp
      WHERE pp.fetch_event_id = fe.id
        AND pp.parse_status IN ('success', 'partial')
    )
  ORDER BY fe.fetched_at DESC;

COMMENT ON VIEW raw.v_parse_backlog IS
  'Fetches que precisam (re)parse: sucesso HTTP mas sem parse bem-sucedido.';


-- G. PERMISSÕES (esqueleto) ===================================================
-- Roles esperados:
--   service_role     → INSERT em fetch_event, parsed_payload, etc. (scraper)
--   pii_reader       → SELECT em raw (sem PII normalmente, mas inclui)
--   anon, authenticated → SEM ACESSO
--
-- Aplicado fora do DDL (ver bloco de blindagem):
--   REVOKE ALL ON SCHEMA raw FROM anon, authenticated, public;
--   REVOKE ALL ON ALL TABLES IN SCHEMA raw FROM anon, authenticated, public;

-- =============================================================================
-- FIM
-- =============================================================================