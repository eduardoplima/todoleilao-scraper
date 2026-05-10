-- =============================================================================
-- public_v1_ddl.sql
-- Camada pública versionada (contrato com o frontend).
-- Versão 0.1.0 — 2026-05-09
--
-- Princípios:
--   - Único schema acessível por PostgREST/web_anon/anon.
--   - Não expõe core.party_identity nem nenhum campo PII de pessoa física.
--   - View materializada `lot_search` para listagem facetada (filtros básicos).
--   - View regular `lot_detail` para a página de detalhe (sempre fresca).
--   - DISTINCT ON (lot_id) onde necessário para mitigar inflação herdada de
--     `core.spatial_unit` (cada UPSERT do pipeline cria nova spatial_unit).
--
-- Para versionar: quando algum campo for renomeado/removido, criar
-- `public_v2`, manter `public_v1` por ≥90 dias e comunicar deprecação.
-- =============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS public_v1;

-- -----------------------------------------------------------------------------
-- A. Materialized view de busca/listagem
-- -----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS public_v1.lot_search CASCADE;
CREATE MATERIALIZED VIEW public_v1.lot_search AS
WITH primary_unit AS (
  -- DISTINCT ON evita duplicação causada pela inflação de spatial_unit
  -- (bug colateral do pipeline; mantém apenas a unit mais antiga por lote).
  SELECT DISTINCT ON (lu.lot_id)
         lu.lot_id,
         su.id              AS spatial_unit_id,
         su.kind,
         su.address_id,
         su.useful_area,
         su.private_area,
         su.total_area,
         su.bedrooms,
         su.bathrooms,
         su.parking_spots
  FROM core.lot_unit_link lu
  JOIN core.spatial_unit su ON su.id = lu.spatial_unit_id
  ORDER BY lu.lot_id, su.created_at ASC
),
next_round AS (
  -- Praça mais próxima (futura ou mais recente). Cada lote tem 1..N rounds.
  SELECT DISTINCT ON (lot_id)
         lot_id,
         round_number,
         scheduled_at,
         minimum_bid,
         status
  FROM core.auction_round
  ORDER BY lot_id, scheduled_at ASC
),
primary_image AS (
  -- Thumbnail = primeira imagem por display_order/created_at.
  SELECT DISTINCT ON (lot_id)
         lot_id,
         source_url AS thumb_url
  FROM core.image
  WHERE lot_id IS NOT NULL
  ORDER BY lot_id, display_order ASC, created_at ASC
)
SELECT
  al.id                                                  AS lot_id,
  -- Sufixo curto pra desambiguar slug colidente em URLs do front
  -- (`/lote/{slug}-{lot_id_short}`). Não é único, mas com slug + 8 chars
  -- de UUID a colisão é praticamente impossível.
  LEFT(al.id::text, 8)                                   AS lot_id_short,
  al.lot_number,
  al.source_url,
  al.current_status,
  al.appraisal_value,
  COALESCE(al.scraped_at, al.created_at)                 AS scraped_at,
  -- Spatial unit
  pu.kind,
  pu.useful_area,
  pu.private_area,
  pu.total_area,
  pu.bedrooms,
  pu.bathrooms,
  pu.parking_spots,
  -- Localização
  ad.uf,
  ad.municipality_code                                   AS municipality_ibge_code,
  m.name                                                 AS municipality_name,
  ad.district,
  ad.geom,
  -- Próxima praça (round) e fallback pra venda direta (lot.minimum_bid).
  -- next_round_at fica NULL quando é venda direta sem encerramento agendado.
  nr.round_number                                        AS next_round_number,
  nr.scheduled_at                                        AS next_round_at,
  COALESCE(nr.minimum_bid, al.minimum_bid)               AS minimum_bid,
  -- Deságio (%) calculado: 100 * (1 - minimum_bid/appraisal_value)
  CASE
    WHEN al.appraisal_value IS NOT NULL
         AND al.appraisal_value > 0
         AND COALESCE(nr.minimum_bid, al.minimum_bid) IS NOT NULL
    THEN ROUND((100 * (1 - COALESCE(nr.minimum_bid, al.minimum_bid) / al.appraisal_value))::numeric, 2)
  END                                                    AS discount_pct,
  -- Mídia
  pi.thumb_url,
  -- Slug humano (kind|municipality|lot_number).
  -- Sem extensão `unaccent` no Supabase atual: faz translate manual de
  -- vogais acentuadas e cedilha mais comuns; não-alfanum vira "-".
  lower(regexp_replace(
    translate(
      coalesce(pu.kind::text, 'imovel') || '-' ||
      coalesce(m.name, 'sem-municipio') || '-' ||
      coalesce(al.lot_number, left(al.id::text, 8)),
      'áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
      'aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC'
    ),
    '[^a-zA-Z0-9]+', '-', 'g'
  ))                                                     AS slug
FROM core.auction_lot al
LEFT JOIN primary_unit pu  ON pu.lot_id = al.id
LEFT JOIN core.address ad  ON ad.id = pu.address_id
LEFT JOIN core.municipality m ON m.ibge_code = ad.municipality_code
LEFT JOIN next_round nr    ON nr.lot_id = al.id
LEFT JOIN primary_image pi ON pi.lot_id = al.id
WHERE al.current_status <> 'cancelado'
;

-- Índice único requerido por REFRESH MATERIALIZED VIEW CONCURRENTLY.
CREATE UNIQUE INDEX lot_search_pk
  ON public_v1.lot_search (lot_id);

-- Índices de filtro/ordenação típicos.
CREATE INDEX lot_search_uf_kind_status_idx
  ON public_v1.lot_search (uf, kind, current_status);

CREATE INDEX lot_search_appraisal_idx
  ON public_v1.lot_search (appraisal_value);

CREATE INDEX lot_search_next_round_idx
  ON public_v1.lot_search (next_round_at);

CREATE INDEX lot_search_geom_gix
  ON public_v1.lot_search USING GIST (geom);

CREATE INDEX lot_search_slug_idx
  ON public_v1.lot_search (slug);

CREATE INDEX lot_search_lot_id_short_idx
  ON public_v1.lot_search (lot_id_short);

-- -----------------------------------------------------------------------------
-- B. View regular de detalhe (sempre atualizada — não materializada)
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS public_v1.lot_detail CASCADE;
CREATE VIEW public_v1.lot_detail AS
SELECT
  al.id                                                AS lot_id,
  al.lot_number,
  al.source_url,
  al.current_status,
  al.appraisal_value,
  al.description,
  al.preference_applies,
  al.commission_pct,
  al.final_price,
  al.final_at,
  -- Auction (sem PII; arrematante_party_id e seller_party_id ocultos)
  au.id                                                AS auction_id,
  au.modality                                          AS auction_modality,
  au.origin                                            AS auction_origin,
  au.process_number,
  au.first_round_at,
  au.last_round_at,
  -- Auctioneer (PJ ou agente público no exercício da função — sem
  -- PII de PF; juc_uf+jucesp_number são públicos por LAI/jurisprudência)
  CASE
    WHEN auc.id IS NOT NULL THEN
      json_build_object(
        'full_name',     auc.full_name,
        'jucesp_number', auc.jucesp_number,
        'juc_uf',        auc.juc_uf,
        'cnpj',          auc.cnpj,
        'contact_email', auc.contact_email
      )
  END                                                  AS auctioneer,
  -- Tribunal (apenas para leilão judicial)
  CASE
    WHEN au.modality::text LIKE 'judicial%' AND co.id IS NOT NULL THEN
      json_build_object(
        'short_name', co.short_name,
        'full_name',  co.full_name,
        'court_url',  co.court_url,
        'uf',         co.uf
      )
  END                                                  AS court,
  -- Rounds
  (
    SELECT json_agg(
             json_build_object(
               'round_number', r.round_number,
               'scheduled_at', r.scheduled_at,
               'ends_at',      r.ends_at,
               'minimum_bid',  r.minimum_bid,
               'status',       r.status
             ) ORDER BY r.round_number
           )
    FROM core.auction_round r
    WHERE r.lot_id = al.id
  )                                                    AS rounds,
  -- Imagens (DISTINCT por source_url — pipeline atual gera duplicatas)
  (
    SELECT json_agg(row_to_json(img) ORDER BY img.display_order, img.source_url)
    FROM (
      SELECT DISTINCT ON (i.source_url)
             i.display_order, i.source_url, i.caption
      FROM core.image i
      WHERE i.lot_id = al.id
      ORDER BY i.source_url, i.display_order, i.created_at
    ) img
  )                                                    AS images,
  -- Histórico de lances (DISTINCT por (placed_at, amount) — defesa contra
  -- duplicação herdada; com pipeline corrigido o DISTINCT vira no-op).
  (
    SELECT json_agg(row_to_json(b) ORDER BY b.placed_at)
    FROM (
      SELECT DISTINCT ON (bd.placed_at, bd.amount)
             bd.placed_at, bd.amount, bd.status, bd.is_conditional,
             bd.installments
      FROM core.bid bd
      WHERE bd.lot_id = al.id
      ORDER BY bd.placed_at, bd.amount, bd.created_at
    ) b
  )                                                    AS bids,
  -- Documentos (DISTINCT por source_url)
  (
    SELECT json_agg(row_to_json(doc) ORDER BY doc.kind)
    FROM (
      SELECT DISTINCT ON (d.source_url)
             d.kind, d.source_url, d.sha256
      FROM core.document d
      WHERE d.lot_id = al.id
      ORDER BY d.source_url, d.created_at
    ) doc
  )                                                    AS documents,
  -- Opções de pagamento (1 por kind, garantido pelo pipeline)
  (
    SELECT json_agg(
             json_build_object(
               'kind',                 p.kind,
               'max_installments',     p.max_installments,
               'min_down_payment_pct', p.min_down_payment_pct,
               'min_down_payment_brl', p.min_down_payment_brl,
               'index_label',          p.index_label,
               'notes',                p.notes
             ) ORDER BY p.kind
           )
    FROM core.payment_option p
    WHERE p.lot_id = al.id
  )                                                    AS payment_options,
  -- Encumbrances (DISTINCT por (kind, status) — múltiplos ba_units por inflação)
  (
    SELECT json_agg(row_to_json(enc) ORDER BY enc.kind)
    FROM (
      SELECT DISTINCT ON (e.kind, e.status)
             e.kind, e.status, e.amount, e.description
      FROM core.encumbrance e
      JOIN core.ba_unit b        ON b.id = e.ba_unit_id
      JOIN core.lot_unit_link lu ON lu.spatial_unit_id = b.spatial_unit_id
      WHERE lu.lot_id = al.id
      ORDER BY e.kind, e.status, e.created_at
    ) enc
  )                                                    AS encumbrances,
  -- Spatial unit + occupancy (de ba_unit) + amenities (M:N).
  -- DISTINCT lu2 pra mitigar inflação herdada de spatial_unit.
  (
    SELECT row_to_json(u)
    FROM (
      SELECT su.kind, su.useful_area, su.private_area, su.total_area,
             su.land_area, su.built_area, su.bedrooms, su.bathrooms,
             su.parking_spots, su.floor_number, su.year_built,
             su.condominium_name, su.registry_number,
             -- Occupancy do ba_unit vinculado (1 ba_unit por spatial_unit;
             -- se múltiplos houver, pega o mais antigo).
             (SELECT b.occupancy FROM core.ba_unit b
                WHERE b.spatial_unit_id = su.id
                ORDER BY b.created_at LIMIT 1)             AS occupancy,
             -- Amenities como array de objetos {code, display_name, category}.
             COALESCE((
               SELECT json_agg(
                        json_build_object(
                          'code',         at.code,
                          'display_name', at.display_name,
                          'category',     at.category
                        ) ORDER BY at.code
                      )
               FROM core.unit_amenity ua
               JOIN core.amenity_type at ON at.code = ua.amenity_code
               WHERE ua.spatial_unit_id = su.id
             ), '[]'::json)                                AS amenities
      FROM core.lot_unit_link lu2
      JOIN core.spatial_unit su ON su.id = lu2.spatial_unit_id
      WHERE lu2.lot_id = al.id
      ORDER BY su.created_at
      LIMIT 1
    ) u
  )                                                    AS unit,
  -- Endereço
  (
    SELECT row_to_json(a)
    FROM (
      SELECT ad.street_type, ad.street_name, ad.number, ad.complement,
             ad.district, ad.cep, ad.uf,
             ad.municipality_code, m.name AS municipality_name,
             ad.geom
      FROM core.lot_unit_link lu3
      JOIN core.spatial_unit su ON su.id = lu3.spatial_unit_id
      LEFT JOIN core.address ad ON ad.id = su.address_id
      LEFT JOIN core.municipality m ON m.ibge_code = ad.municipality_code
      WHERE lu3.lot_id = al.id
      ORDER BY su.created_at
      LIMIT 1
    ) a
  )                                                    AS address
FROM core.auction_lot al
LEFT JOIN core.auction au ON au.id = al.auction_id
LEFT JOIN core.auctioneer auc ON auc.id = au.auctioneer_id
LEFT JOIN core.court co ON co.id = au.court_id
WHERE al.current_status <> 'cancelado'
;

-- -----------------------------------------------------------------------------
-- C. Permissões (PostgREST roles do Supabase)
-- -----------------------------------------------------------------------------
GRANT USAGE ON SCHEMA public_v1 TO anon, authenticated;
GRANT SELECT ON ALL TABLES IN SCHEMA public_v1 TO anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public_v1
  GRANT SELECT ON TABLES TO anon, authenticated;

COMMIT;
