-- =============================================================================
-- core_schema.sql
-- Repositório de Leilões de Imóveis — schema "core"
-- Versão 0.1.0 — 26 abr 2026
--
-- Schema "core" é a fonte da verdade do projeto. Modelo limpo, normalizado,
-- com foreign keys estritas. Ancorado em LADM (ISO 19152) com extensão própria
-- para o domínio de leilões e implementação de Privacy by Design conforme LGPD.
--
-- Outras camadas:
--   raw         — dumps brutos dos scrapers (não definido aqui)
--   public_v1   — views derivadas, contrato público (não definido aqui)
--
-- Pré-requisitos:
--   PostgreSQL >= 14
--   Extensões: postgis, pgcrypto, pg_trgm, btree_gist
--
-- Convenções:
--   - PKs: uuid via gen_random_uuid(). Trocável por ULID/UUIDv7 (ADR-001).
--   - Datas: SEMPRE timestamptz em UTC. Conversão para America/Sao_Paulo
--     é responsabilidade da camada de apresentação.
--   - Dinheiro: numeric(15, 2), domínio core.brl. Sempre BRL.
--   - Áreas: numeric(10, 2) em m², domínio core.area_m2.
--   - Geometrias: SRID 4326 (WGS84).
--   - ENUM para vocabulários pequenos e estáveis.
--   - Tabela de domínio para vocabulários que crescem (ex.: amenities).
-- =============================================================================


-- A. SETUP =====================================================================

CREATE SCHEMA IF NOT EXISTS core;

-- No Supabase, extensões ficam no schema "extensions" (não em "public").
-- Incluímos "extensions" no search_path para que tipos como geometry e
-- funções como gen_random_uuid()/hmac() sejam encontrados sem qualificação.
-- Mesmo assim, qualificamos explicitamente nas definições críticas
-- (extensions.geometry, extensions.hmac) para robustez.
SET search_path TO core, extensions, public;

-- Extensões: idempotente, não falha se já estiverem habilitadas via Dashboard.
-- Se algum CREATE EXTENSION falhar por permissão na sua instalação,
-- habilite manualmente via Database → Extensions no Dashboard do Supabase.
CREATE EXTENSION IF NOT EXISTS postgis     SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto    SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pg_trgm     SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS btree_gist  SCHEMA extensions;

COMMENT ON SCHEMA core IS
  'Source of truth do repositório. Acesso restrito. Apps externas leem via public_v1.';


-- B. DOMÍNIOS, ENUMS E FUNÇÕES AUXILIARES =====================================

-- B.1 Domínios para validação no nível do banco

CREATE DOMAIN core.uf_code AS char(2)
  CHECK (VALUE ~ '^(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)$');

CREATE DOMAIN core.ibge_municipality_code AS char(7)
  CHECK (VALUE ~ '^[0-9]{7}$');

-- Número CNJ unificado: NNNNNNN-DD.AAAA.J.TR.OOOO
CREATE DOMAIN core.cnj_process_number AS varchar(25)
  CHECK (VALUE ~ '^[0-9]{7}-[0-9]{2}\.[0-9]{4}\.[0-9]\.[0-9]{2}\.[0-9]{4}$');

CREATE DOMAIN core.cnpj AS char(14)
  CHECK (VALUE ~ '^[0-9]{14}$');

-- HMAC-SHA256 hex (64 chars). NUNCA armazenamos CPF claro.
CREATE DOMAIN core.cpf_hash AS char(64)
  CHECK (VALUE ~ '^[0-9a-f]{64}$');

CREATE DOMAIN core.sha256_hex AS char(64)
  CHECK (VALUE ~ '^[0-9a-f]{64}$');

CREATE DOMAIN core.cep AS char(8)
  CHECK (VALUE ~ '^[0-9]{8}$');

CREATE DOMAIN core.cep5 AS char(5)
  CHECK (VALUE ~ '^[0-9]{5}$');

CREATE DOMAIN core.brl AS numeric(15, 2);

CREATE DOMAIN core.area_m2 AS numeric(10, 2)
  CHECK (VALUE >= 0);

CREATE DOMAIN core.confidence AS numeric(3, 2)
  CHECK (VALUE BETWEEN 0 AND 1);


-- B.2 ENUMs (vocabulários controlados pequenos e estáveis)

CREATE TYPE core.party_kind AS ENUM (
  'pessoa_fisica',
  'pessoa_juridica',
  'espolio',
  'massa_falida',
  'ente_publico',
  'condominio',
  'consorcio',
  'fundo_investimento',
  'desconhecida'
);

CREATE TYPE core.party_role AS ENUM (
  'executado',
  'exequente',
  'fiduciante',
  'fiduciario',
  'devedor',
  'credor',
  'arrematante',
  'leiloeiro',
  'comitente',
  'tribunal',
  'proprietario',
  'usufrutuario',
  'fiador',
  'outro'
);

CREATE TYPE core.auction_modality AS ENUM (
  'judicial_cpc',
  'extrajudicial_lei_9514',
  'extrajudicial_outro',
  'administrativo_receita',
  'administrativo_inss',
  'administrativo_municipal',
  'falencia',
  'recuperacao_judicial',
  'inventario',
  'concessao_uso',
  'leilao_publico',
  'outro'
);

CREATE TYPE core.auction_origin AS ENUM (
  'execucao_civel',
  'execucao_fiscal',
  'execucao_trabalhista',
  'execucao_extrajudicial_titulo',
  'busca_apreensao',
  'alienacao_fiduciaria_inadimplida',
  'falencia',
  'inventario_arrolamento',
  'desapropriacao',
  'divida_ativa_municipal',
  'outro',
  'desconhecida'
);

CREATE TYPE core.lot_status AS ENUM (
  'futuro',
  'aberto',
  'suspenso',
  'arrematado',
  'deserto',
  'adjudicado',
  'remido',
  'cancelado',
  'desconhecido'
);

CREATE TYPE core.round_status AS ENUM (
  'futura',
  'aberta',
  'encerrada_arrematada',
  'encerrada_deserta',
  'suspensa',
  'cancelada'
);

CREATE TYPE core.unit_kind AS ENUM (
  'apartamento',
  'casa',
  'sobrado',
  'kitnet_studio',
  'flat',
  'sala_comercial',
  'loja',
  'galpao',
  'predio_inteiro',
  'terreno_urbano',
  'terreno_rural',
  'sitio',
  'fazenda',
  'chacara',
  'vaga_garagem',
  'box',
  'cota_imovel',
  'outro',
  'desconhecida'
);

CREATE TYPE core.occupancy_status AS ENUM (
  'desocupado',
  'ocupado_pelo_executado',
  'ocupado_por_terceiro',
  'ocupado_com_locacao',
  'ocupacao_irregular',
  'indeterminado'
);

CREATE TYPE core.encumbrance_kind AS ENUM (
  'hipoteca',
  'penhora',
  'penhora_fiscal',
  'usufruto',
  'alienacao_fiduciaria',
  'indisponibilidade',
  'iptu_em_aberto',
  'condominio_em_aberto',
  'arresto',
  'sequestro',
  'enfiteuse',
  'servidao',
  'outro'
);

CREATE TYPE core.encumbrance_status AS ENUM (
  'declarado',
  'pendente',
  'quitado_pelo_arrematante',
  'sub_rogado_no_lance',
  'cancelado',
  'desconhecido'
);

CREATE TYPE core.document_kind AS ENUM (
  'edital',
  'edital_complementar',
  'laudo_avaliacao',
  'matricula',
  'certidao_onus',
  'certidao_iptu',
  'certidao_condominio',
  'auto_arrematacao',
  'termo_direito_preferencia',
  'ficha_lote',
  'planta_imovel',
  'outro'
);

CREATE TYPE core.payment_kind AS ENUM (
  'a_vista',
  'parcelado',
  'carta_credito',
  'fgts',
  'financiamento_proprio',
  'consorcio',
  'permuta',
  'outro'
);

CREATE TYPE core.bid_status AS ENUM (
  'registrado',
  'cancelado',
  'vencedor',
  'condicional'
);


-- B.3 Funções auxiliares

-- Hash de CPF com pepper injetado por sessão.
-- O pepper NÃO é configurado no banco (Supabase bloqueia ALTER DATABASE para
-- roles não-superuser). Em vez disso, cada transação do scraper injeta:
--
--   BEGIN;
--   SET LOCAL app.cpf_pepper = '<segredo>';
--   SELECT core.hash_cpf('123.456.789-09');
--   COMMIT;
--
-- O pepper vive em variável de ambiente do scraper (CPF_PEPPER) e nunca
-- é persistido em banco, em log ou em código versionado.
--
-- Marcada STABLE (não IMMUTABLE) porque lê current_setting(). IMMUTABLE
-- permitiria que o planner cacheasse o resultado entre transações, o que
-- é incorreto quando o pepper varia por sessão.
CREATE OR REPLACE FUNCTION core.hash_cpf(cpf_clear text)
RETURNS core.cpf_hash
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  pepper text;
  digits text;
BEGIN
  digits := regexp_replace(cpf_clear, '[^0-9]', '', 'g');
  IF length(digits) <> 11 THEN
    RAISE EXCEPTION 'CPF inválido: deve ter 11 dígitos numéricos (recebeu %)', length(digits);
  END IF;
  pepper := current_setting('app.cpf_pepper', true);
  IF pepper IS NULL OR length(pepper) < 32 THEN
    RAISE EXCEPTION 'app.cpf_pepper não configurado ou < 32 chars na sessão. '
      'Faça SET LOCAL app.cpf_pepper antes de chamar hash_cpf.';
  END IF;
  RETURN encode(extensions.hmac(digits, pepper, 'sha256'), 'hex');
END;
$$;

COMMENT ON FUNCTION core.hash_cpf IS
  'HMAC-SHA256 hex(64) de um CPF. Pepper injetado por sessão via '
  'SET LOCAL app.cpf_pepper. CPF claro NUNCA persistido. '
  'Permite cruzar a mesma pessoa entre leilões.';

-- Gera label redigida "J. S., São Paulo/SP" a partir de nome + cidade + UF
CREATE OR REPLACE FUNCTION core.compute_redacted_label(
  full_name text,
  city text,
  uf core.uf_code
) RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT
    COALESCE(
      (
        SELECT string_agg(left(part, 1) || '.', ' ')
        FROM unnest(string_to_array(trim(full_name), ' ')) AS part
        WHERE length(part) > 2  -- ignora partículas: de, da, do, dos, das
      ),
      '[anônimo]'
    )
    || ', ' || COALESCE(city, '?')
    || '/' || COALESCE(uf::text, '??');
$$;

-- Trigger para manter updated_at
CREATE OR REPLACE FUNCTION core.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;


-- C. PROVENIÊNCIA ==============================================================
-- Definida cedo porque outras tabelas referenciam.

-- C.1 Source: cada portal/agregador/site é uma source distinta.
CREATE TABLE core.source (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  short_name      text NOT NULL UNIQUE,         -- "zuk", "megaleiloes", "tjsp_esaj"
  display_name    text NOT NULL,                 -- "Portal Zuk"
  base_url        text NOT NULL,
  source_kind     text NOT NULL CHECK (source_kind IN (
                    'aggregator',     -- Zuk, Megaleilões, Sodré Santoro
                    'auctioneer',     -- site de leiloeiro individual
                    'court',          -- e-SAJ, PJe, etc.
                    'bank',           -- Caixa, BB, Santander
                    'government',     -- Receita, INSS, SPU
                    'enrichment'      -- IBGE, BCB, CNJ DataJud
                  )),
  active          boolean NOT NULL DEFAULT true,
  notes           text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER source_updated_at
  BEFORE UPDATE ON core.source
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- C.2 ScrapeEvent: cada visita do scraper a uma URL específica
CREATE TABLE core.scrape_event (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id         uuid NOT NULL REFERENCES core.source (id),
  url               text NOT NULL,
  scraped_at        timestamptz NOT NULL DEFAULT now(),
  parser_version    text NOT NULL,                -- semver/hash do parser
  http_status       smallint,
  raw_html_r2_key   text,                          -- caminho no R2
  raw_html_sha256   core.sha256_hex,
  parse_status      text CHECK (parse_status IN (
                      'pending', 'success', 'partial', 'failed'
                    )),
  parse_error       text,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX scrape_event_source_idx     ON core.scrape_event (source_id);
CREATE INDEX scrape_event_url_idx        ON core.scrape_event (url);
CREATE INDEX scrape_event_scraped_at_idx ON core.scrape_event (scraped_at DESC);


-- D. TABELAS DE REFERÊNCIA =====================================================

-- D.1 Municípios (carregados do IBGE)
CREATE TABLE core.municipality (
  ibge_code         core.ibge_municipality_code PRIMARY KEY,
  name              text NOT NULL,
  uf                core.uf_code NOT NULL,
  microregion_code  varchar(5),
  mesoregion_code   varchar(4),
  region_code       char(1),                       -- 1=N, 2=NE, 3=SE, 4=S, 5=CO
  geom              extensions.geometry(MultiPolygon, 4326),
  centroid          extensions.geometry(Point, 4326),
  area_km2          numeric(12, 2),
  population_last   integer,
  population_year   smallint,
  source_version    text,                          -- versão do snapshot IBGE
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX municipality_geom_gix      ON core.municipality USING GIST (geom);
CREATE INDEX municipality_centroid_gix  ON core.municipality USING GIST (centroid);
CREATE INDEX municipality_uf_idx        ON core.municipality (uf);
CREATE INDEX municipality_name_trgm_idx ON core.municipality USING GIN (name gin_trgm_ops);

CREATE TRIGGER municipality_updated_at
  BEFORE UPDATE ON core.municipality
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- D.2 Cartórios de Registro de Imóveis (CNS)
CREATE TABLE core.cri_office (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cns_code          varchar(7) UNIQUE,
  display_name      text NOT NULL,                 -- "11º CRI de São Paulo"
  ordinal           smallint,                       -- 11
  municipality_code core.ibge_municipality_code REFERENCES core.municipality (ibge_code),
  address           text,
  cnpj              core.cnpj,
  active            boolean NOT NULL DEFAULT true,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cri_office_municipality_idx ON core.cri_office (municipality_code);

CREATE TRIGGER cri_office_updated_at
  BEFORE UPDATE ON core.cri_office
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- D.3 Tribunais e Varas (mapeados do CNJ DataJud)
CREATE TABLE core.court (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cnj_segment       smallint NOT NULL,             -- 8=Estadual, 5=Trabalho, 4=Federal
  cnj_tribunal      smallint NOT NULL,             -- 26=TJSP, 13=TJMG
  cnj_origin        smallint,                       -- foro/comarca
  short_name        text NOT NULL,                  -- "TJSP - Foro Central Cível"
  full_name         text,
  uf                core.uf_code,
  municipality_code core.ibge_municipality_code REFERENCES core.municipality (ibge_code),
  court_url         text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cnj_segment, cnj_tribunal, cnj_origin)
);

CREATE TRIGGER court_updated_at
  BEFORE UPDATE ON core.court
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- D.4 Leiloeiros
CREATE TABLE core.auctioneer (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  full_name         text NOT NULL,
  jucesp_number     varchar(10),                   -- "744" — número da matrícula
  juc_uf            core.uf_code,
  identity_id       uuid,                           -- FK adicionada após party_identity
  cnpj              core.cnpj,
  active            boolean NOT NULL DEFAULT true,
  contact_email     text,
  contact_phone     text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auctioneer_juc_idx ON core.auctioneer (juc_uf, jucesp_number);

CREATE TRIGGER auctioneer_updated_at
  BEFORE UPDATE ON core.auctioneer
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- D.5 Tipos de amenidade (vocabulário extensível)
CREATE TABLE core.amenity_type (
  code              text PRIMARY KEY,              -- "piscina", "varanda", "dep_empregados"
  display_name      text NOT NULL,
  category          text,                          -- "lazer", "estrutura", "segurança"
  description       text,
  created_at        timestamptz NOT NULL DEFAULT now()
);

INSERT INTO core.amenity_type (code, display_name, category) VALUES
  ('piscina',          'Piscina',              'lazer'),
  ('varanda',          'Varanda',              'estrutura'),
  ('dep_empregados',   'Dep. Empregados',      'estrutura'),
  ('churrasqueira',    'Churrasqueira',        'lazer'),
  ('elevador',         'Elevador',             'estrutura'),
  ('portaria_24h',     'Portaria 24h',         'seguranca'),
  ('academia',         'Academia',             'lazer'),
  ('playground',       'Playground',           'lazer'),
  ('salao_festas',     'Salão de Festas',      'lazer'),
  ('quadra',           'Quadra',               'lazer'),
  ('jardim',           'Jardim',               'estrutura'),
  ('mobiliado',        'Mobiliado',            'estrutura'),
  ('ar_condicionado',  'Ar Condicionado',      'estrutura'),
  ('aquecimento',      'Aquecimento',          'estrutura')
ON CONFLICT DO NOTHING;


-- E. PACOTE PARTY (LADM Party + Privacy by Design) =============================

-- E.1 Identidade real (PII isolada). Acesso restrito a role pii_reader.
CREATE TABLE core.party_identity (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cpf_hash              core.cpf_hash UNIQUE,      -- HMAC com pepper
  cnpj                  core.cnpj UNIQUE,
  full_name             text,                       -- TTL via job; sai NULL após 90d
  full_name_purge_at    timestamptz,
  redacted_label        text NOT NULL,              -- "J.S., São Paulo/SP"
  public_token          uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  deletion_requested_at timestamptz,                -- art. 18 LGPD
  source_id             uuid REFERENCES core.source (id),
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CHECK (cpf_hash IS NOT NULL OR cnpj IS NOT NULL OR full_name IS NOT NULL)
);
CREATE INDEX party_identity_cpf_hash_idx ON core.party_identity (cpf_hash) WHERE cpf_hash IS NOT NULL;
CREATE INDEX party_identity_cnpj_idx     ON core.party_identity (cnpj)     WHERE cnpj IS NOT NULL;
CREATE INDEX party_identity_purge_idx    ON core.party_identity (full_name_purge_at)
  WHERE full_name IS NOT NULL;

COMMENT ON TABLE core.party_identity IS
  'PII isolada. NUNCA exposta em public_v1. Apenas redacted_label e public_token saem.';

CREATE TRIGGER party_identity_updated_at
  BEFORE UPDATE ON core.party_identity
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- FK retroativa de auctioneer.identity_id
ALTER TABLE core.auctioneer
  ADD CONSTRAINT auctioneer_identity_fk
  FOREIGN KEY (identity_id) REFERENCES core.party_identity (id);

-- E.2 Party (entidade comum)
CREATE TABLE core.party (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind                core.party_kind NOT NULL,
  identity_id         uuid REFERENCES core.party_identity (id),
  display_name        text,                          -- razão social (PJ) ou redacted (PF)
  is_public_official  boolean NOT NULL DEFAULT false,
  notes               text,
  source_id           uuid REFERENCES core.source (id),
  scraped_at          timestamptz,
  parser_version      text,
  confidence_score    core.confidence,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  -- PF SEMPRE deve ter identity_id; demais kinds podem ou não ter.
  CHECK (
    (kind = 'pessoa_fisica' AND identity_id IS NOT NULL) OR
    (kind <> 'pessoa_fisica')
  )
);
CREATE INDEX party_kind_idx          ON core.party (kind);
CREATE INDEX party_identity_id_idx   ON core.party (identity_id);
CREATE INDEX party_display_trgm_idx  ON core.party USING GIN (display_name gin_trgm_ops);

CREATE TRIGGER party_updated_at
  BEFORE UPDATE ON core.party
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();


-- F. PACOTE SPATIAL (LADM Spatial Unit) =======================================

-- F.1 Endereço estruturado (separado para reuso e parsing iterativo)
CREATE TABLE core.address (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  street_type         text,                          -- "Avenida", "Rua", "Rodovia"
  street_name         text,                          -- "Washington Luís"
  number              text,                          -- pode ter "S/N", "Km 47"
  complement          text,                          -- "Apto 162, Bloco A, Edif. Acácia"
  district            text,                          -- "Santo Amaro"
  municipality_code   core.ibge_municipality_code REFERENCES core.municipality (ibge_code),
  uf                  core.uf_code,
  cep                 core.cep,
  cep5_only           core.cep5,                     -- versão truncada (após 90d)
  geom                extensions.geometry(Point, 4326),
  geocoding_source    text,                          -- "nominatim", "google", "manual"
  geocoding_confidence core.confidence,
  raw_text            text,                          -- string original do edital
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX address_geom_gix          ON core.address USING GIST (geom);
CREATE INDEX address_municipality_idx  ON core.address (municipality_code);
CREATE INDEX address_cep_idx           ON core.address (cep);

CREATE TRIGGER address_updated_at
  BEFORE UPDATE ON core.address
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- F.2 Spatial Unit (o imóvel físico)
CREATE TABLE core.spatial_unit (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind                core.unit_kind NOT NULL DEFAULT 'desconhecida',
  -- Identificadores legais
  cri_office_id       uuid REFERENCES core.cri_office (id),
  registry_number     text,                          -- número da matrícula
  municipal_inscription text,                         -- inscrição imobiliária
  ccir_number         text,                          -- INCRA, p/ rurais
  car_number          text,                          -- Cadastro Ambiental Rural
  -- Localização
  address_id          uuid REFERENCES core.address (id),
  -- Características
  total_area          core.area_m2,                  -- área total
  private_area        core.area_m2,                  -- área privativa
  useful_area         core.area_m2,                  -- área útil
  land_area           core.area_m2,                  -- área do terreno (rurais/casas)
  built_area          core.area_m2,                  -- área construída
  bedrooms            smallint CHECK (bedrooms >= 0),
  bathrooms           smallint CHECK (bathrooms >= 0),
  parking_spots       smallint CHECK (parking_spots >= 0),
  floor_number        smallint,                       -- andar (NULL para casas/terrenos)
  building_name       text,                           -- "Edifício Acácia"
  block_name          text,                           -- "Bloco A"
  condominium_name    text,                           -- "Reserva Casa Grande"
  unit_number         text,                           -- "162"
  year_built          smallint,
  -- Avaliação de referência (laudo)
  appraisal_value     core.brl,
  appraisal_date      date,
  appraisal_source    text,
  -- Proveniência
  source_id           uuid REFERENCES core.source (id),
  scraped_at          timestamptz,
  parser_version      text,
  confidence_score    core.confidence,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cri_office_id, registry_number)            -- chave canônica nacional
);
CREATE INDEX spatial_unit_kind_idx        ON core.spatial_unit (kind);
CREATE INDEX spatial_unit_address_idx     ON core.spatial_unit (address_id);
CREATE INDEX spatial_unit_municipal_idx   ON core.spatial_unit (municipal_inscription)
  WHERE municipal_inscription IS NOT NULL;

CREATE TRIGGER spatial_unit_updated_at
  BEFORE UPDATE ON core.spatial_unit
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- F.3 Amenidades por unidade (M:N)
CREATE TABLE core.unit_amenity (
  spatial_unit_id     uuid NOT NULL REFERENCES core.spatial_unit (id) ON DELETE CASCADE,
  amenity_code        text NOT NULL REFERENCES core.amenity_type (code),
  source_id           uuid REFERENCES core.source (id),
  created_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (spatial_unit_id, amenity_code)
);


-- G. PACOTE ADMINISTRATIVE (LADM RRR — Rights, Restrictions, Responsibilities) =

-- G.1 BAUnit (Basic Administrative Unit)
-- Liga uma SpatialUnit a um conjunto de direitos. Em geral 1:1 mas pode ser 1:N.
CREATE TABLE core.ba_unit (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  spatial_unit_id     uuid NOT NULL REFERENCES core.spatial_unit (id),
  holder_party_id     uuid REFERENCES core.party (id),     -- proprietário
  ownership_share     numeric(5, 4) CHECK (ownership_share BETWEEN 0 AND 1),
  occupancy           core.occupancy_status NOT NULL DEFAULT 'indeterminado',
  occupancy_notes     text,
  source_id           uuid REFERENCES core.source (id),
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ba_unit_spatial_idx ON core.ba_unit (spatial_unit_id);
CREATE INDEX ba_unit_holder_idx  ON core.ba_unit (holder_party_id);

CREATE TRIGGER ba_unit_updated_at
  BEFORE UPDATE ON core.ba_unit
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- G.2 Encumbrance (ônus declarados no edital ou na matrícula)
CREATE TABLE core.encumbrance (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ba_unit_id          uuid NOT NULL REFERENCES core.ba_unit (id) ON DELETE CASCADE,
  kind                core.encumbrance_kind NOT NULL,
  status              core.encumbrance_status NOT NULL DEFAULT 'declarado',
  amount              core.brl,                      -- valor do ônus quando declarado
  reference_date      date,                           -- data de referência do valor
  creditor_party_id   uuid REFERENCES core.party (id),
  description         text,                           -- texto livre do edital
  source_id           uuid REFERENCES core.source (id),
  source_document_id  uuid,                           -- FK adicionada após document
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX encumbrance_ba_unit_idx  ON core.encumbrance (ba_unit_id);
CREATE INDEX encumbrance_kind_idx     ON core.encumbrance (kind);
CREATE INDEX encumbrance_creditor_idx ON core.encumbrance (creditor_party_id);

CREATE TRIGGER encumbrance_updated_at
  BEFORE UPDATE ON core.encumbrance
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();


-- H. PACOTE AUCTION (extensão própria) =========================================

-- H.1 Auction (evento de leilão)
CREATE TABLE core.auction (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  modality              core.auction_modality NOT NULL,
  origin                core.auction_origin NOT NULL DEFAULT 'desconhecida',
  -- Vínculo judicial (quando aplicável)
  process_number        core.cnj_process_number,
  court_id              uuid REFERENCES core.court (id),
  -- Atores
  seller_party_id       uuid REFERENCES core.party (id),  -- comitente
  auctioneer_id         uuid REFERENCES core.auctioneer (id),
  -- Identificação no source
  source_id             uuid REFERENCES core.source (id),
  source_auction_code   text,                              -- ID do leilão no portal
  source_url            text,
  -- Metadados temporais
  first_round_at        timestamptz,                       -- data 1ª praça (cache)
  last_round_at         timestamptz,                       -- data última praça (cache)
  -- Proveniência
  scraped_at            timestamptz,
  last_seen_at          timestamptz,
  parser_version        text,
  confidence_score      core.confidence,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auction_process_idx   ON core.auction (process_number);
CREATE INDEX auction_court_idx     ON core.auction (court_id);
CREATE INDEX auction_modality_idx  ON core.auction (modality);
CREATE INDEX auction_source_code_idx ON core.auction (source_id, source_auction_code);

CREATE TRIGGER auction_updated_at
  BEFORE UPDATE ON core.auction
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- H.2 AuctionLot (lote individual)
CREATE TABLE core.auction_lot (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  auction_id            uuid NOT NULL REFERENCES core.auction (id) ON DELETE CASCADE,
  lot_number            text,                              -- número do lote dentro do leilão
  -- Identificação no source
  source_id             uuid REFERENCES core.source (id),
  source_lot_code       text,                              -- "35808-223092"
  source_internal_code  text,                              -- "Z-35853-003"
  source_url            text,
  -- Status atual (denormalizado para queries rápidas; verdade está em auction_round)
  current_status        core.lot_status NOT NULL DEFAULT 'futuro',
  appraisal_value       core.brl,                          -- valor de avaliação do laudo
  -- Resultado final (preenchido quando arrematado)
  winning_bid_id        uuid,                               -- FK adicionada após bid
  arrematante_party_id  uuid REFERENCES core.party (id),
  final_price           core.brl,
  final_at              timestamptz,
  -- Direito de preferência
  preference_applies    boolean NOT NULL DEFAULT false,
  -- Comissão do leiloeiro
  commission_pct        numeric(5, 2) CHECK (commission_pct BETWEEN 0 AND 100),
  -- Modalidades de pagamento (conjuntos modelados em payment_option)
  -- Proveniência
  scraped_at            timestamptz,
  last_seen_at          timestamptz,
  parser_version        text,
  confidence_score      core.confidence,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_id, source_lot_code)                      -- chave externa estável
);
CREATE INDEX auction_lot_auction_idx ON core.auction_lot (auction_id);
CREATE INDEX auction_lot_status_idx  ON core.auction_lot (current_status);

CREATE TRIGGER auction_lot_updated_at
  BEFORE UPDATE ON core.auction_lot
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- H.3 AuctionRound (praças: 1ª, 2ª, 3ª)
CREATE TABLE core.auction_round (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lot_id              uuid NOT NULL REFERENCES core.auction_lot (id) ON DELETE CASCADE,
  round_number        smallint NOT NULL CHECK (round_number BETWEEN 1 AND 9),
  scheduled_at        timestamptz NOT NULL,
  ends_at             timestamptz,
  minimum_bid         core.brl NOT NULL,                   -- lance mínimo da praça
  bid_increment       core.brl,
  status              core.round_status NOT NULL DEFAULT 'futura',
  notes               text,
  scraped_at          timestamptz,
  parser_version      text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (lot_id, round_number)
);
CREATE INDEX auction_round_lot_idx       ON core.auction_round (lot_id);
CREATE INDEX auction_round_scheduled_idx ON core.auction_round (scheduled_at);

CREATE TRIGGER auction_round_updated_at
  BEFORE UPDATE ON core.auction_round
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- H.4 LotUnitLink (M:N entre lotes e unidades; um lote pode ter vários imóveis)
CREATE TABLE core.lot_unit_link (
  lot_id              uuid NOT NULL REFERENCES core.auction_lot (id) ON DELETE CASCADE,
  spatial_unit_id     uuid NOT NULL REFERENCES core.spatial_unit (id),
  share_pct           numeric(5, 2) CHECK (share_pct BETWEEN 0 AND 100), -- p/ frações ideais
  created_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (lot_id, spatial_unit_id)
);
CREATE INDEX lot_unit_link_unit_idx ON core.lot_unit_link (spatial_unit_id);

-- H.5 Bid (lance)
CREATE TABLE core.bid (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  round_id            uuid NOT NULL REFERENCES core.auction_round (id) ON DELETE CASCADE,
  lot_id              uuid NOT NULL REFERENCES core.auction_lot (id) ON DELETE CASCADE,
  bidder_party_id     uuid REFERENCES core.party (id),
  amount              core.brl NOT NULL,
  placed_at           timestamptz NOT NULL,
  status              core.bid_status NOT NULL DEFAULT 'registrado',
  is_conditional      boolean NOT NULL DEFAULT false,
  installments        smallint,                           -- p/ propostas parceladas
  notes               text,
  source_id           uuid REFERENCES core.source (id),
  scraped_at          timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX bid_round_idx     ON core.bid (round_id);
CREATE INDEX bid_lot_idx       ON core.bid (lot_id);
CREATE INDEX bid_bidder_idx    ON core.bid (bidder_party_id);
CREATE INDEX bid_placed_at_idx ON core.bid (placed_at DESC);

-- FK retroativa em auction_lot
ALTER TABLE core.auction_lot
  ADD CONSTRAINT auction_lot_winning_bid_fk
  FOREIGN KEY (winning_bid_id) REFERENCES core.bid (id);

-- H.6 PaymentOption (formas de pagamento aceitas pelo comitente)
CREATE TABLE core.payment_option (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lot_id              uuid NOT NULL REFERENCES core.auction_lot (id) ON DELETE CASCADE,
  kind                core.payment_kind NOT NULL,
  max_installments    smallint,                            -- 30
  min_down_payment_pct numeric(5, 2) CHECK (min_down_payment_pct BETWEEN 0 AND 100),
  min_down_payment_brl core.brl,
  index_label         text,                                -- "INPC + 1%", "Selic"
  notes               text,
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX payment_option_lot_idx ON core.payment_option (lot_id);

-- H.7 LegalNote (Tema STJ, Provimento CNJ etc.)
CREATE TABLE core.legal_note (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lot_id              uuid REFERENCES core.auction_lot (id) ON DELETE CASCADE,
  auction_id          uuid REFERENCES core.auction (id) ON DELETE CASCADE,
  note_code           text NOT NULL,                       -- "STJ_TEMA_1134", "CNJ_PROV_188"
  source_url          text,
  summary             text,
  raw_text            text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  CHECK (lot_id IS NOT NULL OR auction_id IS NOT NULL)
);
CREATE INDEX legal_note_code_idx ON core.legal_note (note_code);
CREATE INDEX legal_note_lot_idx  ON core.legal_note (lot_id);

-- H.8 ProcessReference (vínculos a processos judiciais auxiliares)
CREATE TABLE core.process_reference (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  auction_id          uuid NOT NULL REFERENCES core.auction (id) ON DELETE CASCADE,
  process_number      core.cnj_process_number NOT NULL,
  role                text,                                -- "principal", "apenso"
  url                 text,
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX process_ref_auction_idx ON core.process_reference (auction_id);
CREATE INDEX process_ref_process_idx ON core.process_reference (process_number);


-- I. DOCUMENTOS E MÍDIA ========================================================

-- I.1 Document (edital, laudo, matrícula, certidão)
CREATE TABLE core.document (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind                core.document_kind NOT NULL,
  -- Anexação flexível: pode pertencer a um lote, a um leilão, ou a uma unidade
  lot_id              uuid REFERENCES core.auction_lot (id) ON DELETE CASCADE,
  auction_id          uuid REFERENCES core.auction (id) ON DELETE CASCADE,
  spatial_unit_id     uuid REFERENCES core.spatial_unit (id) ON DELETE CASCADE,
  -- Conteúdo
  source_url          text,
  r2_key              text,                                -- caminho no Cloudflare R2
  sha256              core.sha256_hex,
  mime_type           text,
  file_size_bytes     bigint,
  title               text,
  document_date       date,
  -- Proveniência
  source_id           uuid REFERENCES core.source (id),
  scraped_at          timestamptz,
  parser_version      text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CHECK (
    lot_id IS NOT NULL OR auction_id IS NOT NULL OR spatial_unit_id IS NOT NULL
  )
);
CREATE INDEX document_kind_idx     ON core.document (kind);
CREATE INDEX document_lot_idx      ON core.document (lot_id);
CREATE INDEX document_auction_idx  ON core.document (auction_id);
CREATE INDEX document_unit_idx     ON core.document (spatial_unit_id);
CREATE INDEX document_sha256_idx   ON core.document (sha256);

CREATE TRIGGER document_updated_at
  BEFORE UPDATE ON core.document
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();

-- FK retroativa em encumbrance
ALTER TABLE core.encumbrance
  ADD CONSTRAINT encumbrance_source_document_fk
  FOREIGN KEY (source_document_id) REFERENCES core.document (id);

-- I.2 Image (foto do imóvel)
CREATE TABLE core.image (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  spatial_unit_id     uuid REFERENCES core.spatial_unit (id) ON DELETE CASCADE,
  lot_id              uuid REFERENCES core.auction_lot (id) ON DELETE CASCADE,
  display_order       smallint NOT NULL DEFAULT 0,
  source_url          text NOT NULL,
  r2_original_key     text,                                -- original (descartado após encerramento)
  r2_thumb_key        text,                                -- thumbnail WebP 800px (permanente)
  sha256              core.sha256_hex,
  width_px            integer,
  height_px           integer,
  caption             text,
  source_id           uuid REFERENCES core.source (id),
  scraped_at          timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CHECK (spatial_unit_id IS NOT NULL OR lot_id IS NOT NULL)
);
CREATE INDEX image_unit_idx  ON core.image (spatial_unit_id);
CREATE INDEX image_lot_idx   ON core.image (lot_id);
CREATE INDEX image_order_idx ON core.image (lot_id, display_order);

CREATE TRIGGER image_updated_at
  BEFORE UPDATE ON core.image
  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();


-- J. PARTY ROLES E ENRIQUECIMENTO EXTERNO =====================================

-- J.1 PartyRoleInAuction (papel de uma party num leilão específico)
-- Permite a mesma pessoa ser executada em um leilão e arrematante em outro.
CREATE TABLE core.party_role_in_auction (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  party_id            uuid NOT NULL REFERENCES core.party (id),
  auction_id          uuid REFERENCES core.auction (id) ON DELETE CASCADE,
  lot_id              uuid REFERENCES core.auction_lot (id) ON DELETE CASCADE,
  role                core.party_role NOT NULL,
  notes               text,
  source_id           uuid REFERENCES core.source (id),
  created_at          timestamptz NOT NULL DEFAULT now(),
  CHECK (auction_id IS NOT NULL OR lot_id IS NOT NULL)
);
CREATE INDEX party_role_party_idx   ON core.party_role_in_auction (party_id);
CREATE INDEX party_role_auction_idx ON core.party_role_in_auction (auction_id);
CREATE INDEX party_role_lot_idx     ON core.party_role_in_auction (lot_id);
CREATE INDEX party_role_kind_idx    ON core.party_role_in_auction (role);

-- J.2 ExternalSourceSnapshot (snapshots versionados de IBGE, BCB, CNJ, CNPJ etc.)
CREATE TABLE core.external_source_snapshot (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_kind         text NOT NULL,                       -- "ibge_sidra", "bcb_sgs"
  series_code         text NOT NULL,                       -- "ipca", "selic", "censo_2022"
  reference_period    text,                                -- "2022", "2026-Q1"
  fetched_at          timestamptz NOT NULL DEFAULT now(),
  payload             jsonb NOT NULL,
  payload_sha256      core.sha256_hex NOT NULL,
  notes               text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_kind, series_code, reference_period, payload_sha256)
);
CREATE INDEX ext_source_kind_series_idx
  ON core.external_source_snapshot (source_kind, series_code, reference_period);

-- J.3 DatasetRelease (registro dos releases acadêmicos publicados)
CREATE TABLE core.dataset_release (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version             text NOT NULL UNIQUE,                -- semver: "1.0.0"
  title               text NOT NULL,
  doi                 text UNIQUE,                          -- DOI versionado do release
  concept_doi         text,                                 -- DOI conceito (latest)
  zenodo_record_id    text,
  released_at         timestamptz NOT NULL,
  data_window_start   timestamptz NOT NULL,
  data_window_end     timestamptz NOT NULL,
  k_anonymity_min     smallint NOT NULL CHECK (k_anonymity_min >= 1),
  external_sources    jsonb,                                -- { "ibge": "v2024", "bcb": "..." }
  changelog           text,
  paper_doi           text,
  created_at          timestamptz NOT NULL DEFAULT now()
);


-- K. COMENTÁRIOS DOCUMENTAIS ==================================================

COMMENT ON TABLE core.party             IS 'Pessoa, organização ou outra entidade. PF tem identity_id obrigatório.';
COMMENT ON TABLE core.party_identity    IS 'PII isolada. NUNCA exposta em public_v1.';
COMMENT ON TABLE core.spatial_unit      IS 'Imóvel físico. Chave canônica: (cri_office_id, registry_number).';
COMMENT ON TABLE core.ba_unit           IS 'Basic Administrative Unit (LADM). Liga unit a direitos e ocupação.';
COMMENT ON TABLE core.encumbrance       IS 'Ônus declarados (hipoteca, penhora, IPTU, condomínio).';
COMMENT ON TABLE core.auction           IS 'Evento de leilão. Pode ter 1+ lotes.';
COMMENT ON TABLE core.auction_lot       IS 'Lote individual. Tem 1+ rounds e referencia 1+ spatial_units.';
COMMENT ON TABLE core.auction_round     IS 'Praça (1ª, 2ª, 3ª). Cada uma com data, valor mínimo e status.';
COMMENT ON TABLE core.bid               IS 'Lance. Vinculado a um round específico.';
COMMENT ON TABLE core.legal_note        IS 'Nota jurídica relevante: tese do STJ, provimento CNJ, súmula etc.';
COMMENT ON TABLE core.document          IS 'Edital, laudo, matrícula, certidões.';
COMMENT ON TABLE core.image             IS 'Fotos. Original em R2 (TTL); thumb permanente.';
COMMENT ON TABLE core.source            IS 'Cada portal/leiloeiro/site é uma source distinta.';
COMMENT ON TABLE core.scrape_event      IS 'Cada visita do scraper. Liga registros a HTML bruto no R2.';
COMMENT ON TABLE core.external_source_snapshot IS 'Snapshots versionados de IBGE/BCB/CNJ. Auditável para releases.';
COMMENT ON TABLE core.dataset_release   IS 'Releases acadêmicos publicados, com DOI.';


-- L. ROLES E PERMISSÕES (esqueleto) ===========================================
-- Concretamente atribuídos no Supabase via Dashboard ou em arquivo separado.
-- Aqui só registramos a intenção.
--
--   web_anon          → pode SELECT em public_v1.*  (apenas)
--   ingest_writer     → pode INSERT em raw.* e UPDATE em core.* (sem PII)
--   pii_reader        → pode SELECT em core.party_identity
--   admin             → tudo
--
-- =============================================================================
-- FIM
-- =============================================================================