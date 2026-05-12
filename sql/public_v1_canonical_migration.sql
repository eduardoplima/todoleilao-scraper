-- Migration: filtra secondaries da MV `lot_search` e adiciona `alternate_sources`
-- em `lot_detail`.
--
-- Pré-requisitos (aplicar antes desta migration):
--   1. sql/lot_canonical_link.sql (tabela de dedup)
--   2. sql/extract_creditors.sql (função regex + MV com creditors[])
--   3. sql/parties_from_description.sql (trigger upsert party)
--
-- Esta migration:
--   - Recreate `public_v1.lot_search` filtrando WHERE NOT EXISTS lot_canonical_link
--     (secondaries somem da listagem; só canonical aparece).
--   - Atualiza `public_v1.lot_detail` com:
--       creditors text[]      — bancos do lote (via core.extract_creditors)
--       alternate_sources jsonb — lista de URLs secundárias linkadas a este canonical

-- ---------------------------------------------------------------------------
-- A. MV lot_search — filtra secondaries
-- ---------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS public_v1.lot_search CASCADE;
CREATE MATERIALIZED VIEW public_v1.lot_search AS
WITH primary_unit AS (
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
  SELECT DISTINCT ON (lot_id)
         lot_id, round_number, scheduled_at, minimum_bid, status
  FROM core.auction_round
  ORDER BY lot_id, scheduled_at ASC
),
primary_image AS (
  SELECT DISTINCT ON (lot_id)
         lot_id, source_url AS thumb_url
  FROM core.image
  WHERE lot_id IS NOT NULL
  ORDER BY lot_id, display_order ASC, created_at ASC
)
SELECT
  al.id                                                  AS lot_id,
  LEFT(al.id::text, 8)                                   AS lot_id_short,
  al.lot_number,
  al.source_url,
  al.current_status,
  al.appraisal_value,
  COALESCE(al.scraped_at, al.created_at)                 AS scraped_at,
  pu.kind,
  pu.useful_area,
  pu.private_area,
  pu.total_area,
  pu.bedrooms,
  pu.bathrooms,
  pu.parking_spots,
  ad.uf,
  ad.municipality_code                                   AS municipality_ibge_code,
  m.name                                                 AS municipality_name,
  ad.district,
  ad.geom,
  nr.round_number                                        AS next_round_number,
  nr.scheduled_at                                        AS next_round_at,
  COALESCE(nr.minimum_bid, al.minimum_bid)               AS minimum_bid,
  CASE
    WHEN al.appraisal_value IS NOT NULL
         AND al.appraisal_value > 0
         AND COALESCE(nr.minimum_bid, al.minimum_bid) IS NOT NULL
    THEN ROUND((100 * (1 - COALESCE(nr.minimum_bid, al.minimum_bid) / al.appraisal_value))::numeric, 2)
  END                                                    AS discount_pct,
  pi.thumb_url,
  lower(regexp_replace(
    translate(
      (CASE
        WHEN pu.kind IS NULL OR pu.kind::text = 'desconhecida' THEN 'imovel'
        ELSE pu.kind::text
       END)
      || (CASE WHEN m.name IS NOT NULL THEN '-' || m.name ELSE '' END)
      || '-' || coalesce(al.lot_number, left(al.id::text, 8)),
      'áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
      'aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC'
    ),
    '[^a-zA-Z0-9]+', '-', 'g'
  ))                                                     AS slug,
  COALESCE(core.extract_creditors(al.description), '{}'::text[]) AS creditors
FROM core.auction_lot al
LEFT JOIN primary_unit pu  ON pu.lot_id = al.id
LEFT JOIN core.address ad  ON ad.id = pu.address_id
LEFT JOIN core.municipality m ON m.ibge_code = ad.municipality_code
LEFT JOIN next_round nr    ON nr.lot_id = al.id
LEFT JOIN primary_image pi ON pi.lot_id = al.id
-- Filtro novo: oculta secondaries do dedup canonical_link
WHERE al.current_status <> 'cancelado'
  AND NOT EXISTS (
    SELECT 1 FROM core.lot_canonical_link lcl
    WHERE lcl.secondary_lot_id = al.id
  )
;

-- Reindexar (igual ao DDL original + GIN creditors).
CREATE UNIQUE INDEX lot_search_pk         ON public_v1.lot_search (lot_id);
CREATE INDEX lot_search_uf_kind_status_idx ON public_v1.lot_search (uf, kind, current_status);
CREATE INDEX lot_search_appraisal_idx      ON public_v1.lot_search (appraisal_value);
CREATE INDEX lot_search_next_round_idx     ON public_v1.lot_search (next_round_at);
CREATE INDEX lot_search_geom_gix           ON public_v1.lot_search USING GIST (geom);
CREATE INDEX lot_search_slug_idx           ON public_v1.lot_search (slug);
CREATE INDEX lot_search_creditors_gin      ON public_v1.lot_search USING GIN (creditors);

GRANT SELECT ON public_v1.lot_search TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- B. View lot_detail — adiciona creditors[] + alternate_sources jsonb
-- ---------------------------------------------------------------------------
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
  au.id                                                AS auction_id,
  au.modality                                          AS auction_modality,
  au.origin                                            AS auction_origin,
  au.process_number,
  au.first_round_at,
  au.last_round_at,
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
  CASE
    WHEN au.modality::text LIKE 'judicial%' AND co.id IS NOT NULL THEN
      json_build_object(
        'short_name', co.short_name,
        'full_name',  co.full_name,
        'court_url',  co.court_url,
        'uf',         co.uf
      )
  END                                                  AS court,
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
  (
    SELECT row_to_json(u)
    FROM (
      SELECT su.kind, su.useful_area, su.private_area, su.total_area,
             su.land_area, su.built_area, su.bedrooms, su.bathrooms,
             su.parking_spots, su.floor_number, su.year_built,
             su.condominium_name, su.registry_number,
             (SELECT b.occupancy FROM core.ba_unit b
                WHERE b.spatial_unit_id = su.id
                ORDER BY b.created_at LIMIT 1)             AS occupancy,
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
  )                                                    AS address,
  -- NOVO: bancos detectados via core.extract_creditors
  COALESCE(core.extract_creditors(al.description), '{}'::text[]) AS creditors,
  -- NOVO: lista de secondaries linkados (URLs do banco quando o canonical é o leiloeiro)
  COALESCE((
    SELECT json_agg(
             json_build_object(
               'lot_id',      sec.id,
               'source_url',  sec.source_url,
               'source_kind', src.source_kind,
               'match_kind',  lcl.match_kind,
               'confidence',  lcl.confidence
             )
           )
    FROM core.lot_canonical_link lcl
    JOIN core.auction_lot sec ON sec.id = lcl.secondary_lot_id
    LEFT JOIN core.source src ON src.id = sec.source_id
    WHERE lcl.canonical_lot_id = al.id
  ), '[]'::json)                                       AS alternate_sources
FROM core.auction_lot al
LEFT JOIN core.auction au ON au.id = al.auction_id
LEFT JOIN core.auctioneer auc ON auc.id = au.auctioneer_id
LEFT JOIN core.court co ON co.id = au.court_id
WHERE al.current_status <> 'cancelado'
;

GRANT SELECT ON public_v1.lot_detail TO anon, authenticated;
