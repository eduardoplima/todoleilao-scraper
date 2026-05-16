-- Atualiza public_v1.lot_search para expor mais 2 colunas:
--   - sale_mode                  (core.sale_mode: leilao | venda_direta | leilao_e_venda_direta)
--   - direct_sale_deadline_at    (prazo de propostas pra venda direta)
--
-- Mantém as colunas já expostas em sql/public_v1_lot_search_with_modality.sql:
--   - auction_modality, occupancy, has_encumbrances, encumbrance_kinds
--
-- Aplicação:
--   psql "$SUPABASE_DB_URL" -f sql/sale_mode.sql
--   psql "$SUPABASE_DB_URL" -f sql/public_v1_lot_search_with_sale_mode.sql
--   psql "$SUPABASE_DB_URL" -f sql/public_v1_stats_mv.sql      # recria CASCADE
--
-- Refresh continua agendado em sql/public_v1_refresh.sql.

DROP MATERIALIZED VIEW IF EXISTS public_v1.lot_search CASCADE;

CREATE MATERIALIZED VIEW public_v1.lot_search AS
WITH primary_unit AS (
  SELECT DISTINCT ON (lu.lot_id)
    lu.lot_id,
    su.id AS spatial_unit_id,
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
  ORDER BY lu.lot_id, su.created_at
),
next_round AS (
  SELECT DISTINCT ON (ar.lot_id)
    ar.lot_id,
    ar.round_number,
    ar.scheduled_at,
    ar.minimum_bid,
    ar.status
  FROM core.auction_round ar
  ORDER BY ar.lot_id, ar.scheduled_at
),
primary_image AS (
  SELECT DISTINCT ON (image.lot_id)
    image.lot_id,
    image.source_url AS thumb_url
  FROM core.image
  WHERE image.lot_id IS NOT NULL
  ORDER BY image.lot_id, image.display_order, image.created_at
),
encumbr_by_unit AS (
  SELECT
    bu.spatial_unit_id,
    bu.occupancy,
    array_agg(DISTINCT e.kind::text)
      FILTER (
        WHERE e.id IS NOT NULL
          AND e.status NOT IN ('quitado_pelo_arrematante','cancelado')
      ) AS active_kinds
  FROM core.ba_unit bu
  LEFT JOIN core.encumbrance e ON e.ba_unit_id = bu.id
  GROUP BY bu.spatial_unit_id, bu.occupancy
)
SELECT
  al.id AS lot_id,
  "left"(al.id::text, 8) AS lot_id_short,
  al.lot_number,
  al.source_url,
  al.current_status,
  al.appraisal_value,
  COALESCE(al.scraped_at, al.created_at) AS scraped_at,
  pu.kind,
  pu.useful_area,
  pu.private_area,
  pu.total_area,
  pu.bedrooms,
  pu.bathrooms,
  pu.parking_spots,
  ad.uf,
  ad.municipality_code AS municipality_ibge_code,
  m.name AS municipality_name,
  ad.district,
  ad.geom,
  nr.round_number AS next_round_number,
  nr.scheduled_at AS next_round_at,
  COALESCE(nr.minimum_bid, al.minimum_bid) AS minimum_bid,
  CASE
    WHEN al.appraisal_value IS NOT NULL
         AND al.appraisal_value::numeric > 0::numeric
         AND COALESCE(nr.minimum_bid, al.minimum_bid) IS NOT NULL
      THEN round(100::numeric * (1::numeric -
        COALESCE(nr.minimum_bid, al.minimum_bid)::numeric / al.appraisal_value::numeric), 2)
    ELSE NULL::numeric
  END AS discount_pct,
  pi.thumb_url,
  lower(regexp_replace(translate(((
    CASE
      WHEN pu.kind IS NULL OR pu.kind::text = 'desconhecida'::text THEN 'imovel'::text
      ELSE pu.kind::text
    END ||
    CASE
      WHEN m.name IS NOT NULL THEN '-'::text || m.name
      ELSE ''::text
    END) || '-'::text) || COALESCE(al.lot_number, "left"(al.id::text, 8)),
    'áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ'::text,
    'aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC'::text),
    '[^a-zA-Z0-9]+'::text, '-'::text, 'g'::text)) AS slug,
  COALESCE(core.extract_creditors(al.description), '{}'::text[]) AS creditors,

  -- Modalidade do processo + ocupação + ônus (mantidos de modality v1)
  a.modality AS auction_modality,
  eu.occupancy AS occupancy,
  (COALESCE(array_length(eu.active_kinds, 1), 0) > 0) AS has_encumbrances,
  COALESCE(eu.active_kinds, '{}'::text[]) AS encumbrance_kinds,

  -- NOVO: modalidade de venda (leilão x venda direta)
  al.sale_mode,
  al.direct_sale_deadline_at

FROM core.auction_lot al
LEFT JOIN core.auction a ON a.id = al.auction_id
LEFT JOIN primary_unit pu ON pu.lot_id = al.id
LEFT JOIN core.address ad ON ad.id = pu.address_id
LEFT JOIN core.municipality m ON m.ibge_code::bpchar = ad.municipality_code::bpchar
LEFT JOIN next_round nr ON nr.lot_id = al.id
LEFT JOIN primary_image pi ON pi.lot_id = al.id
LEFT JOIN encumbr_by_unit eu ON eu.spatial_unit_id = pu.spatial_unit_id
WHERE al.current_status <> 'cancelado'::core.lot_status
  AND NOT EXISTS (
    SELECT 1 FROM core.lot_canonical_link lcl
    WHERE lcl.secondary_lot_id = al.id
  );

CREATE UNIQUE INDEX lot_search_pk ON public_v1.lot_search (lot_id);
CREATE INDEX lot_search_uf_status_idx ON public_v1.lot_search (uf, current_status);
CREATE INDEX lot_search_muni_idx ON public_v1.lot_search (municipality_ibge_code);
CREATE INDEX lot_search_modality_idx ON public_v1.lot_search (auction_modality);
CREATE INDEX lot_search_occupancy_idx ON public_v1.lot_search (occupancy);
CREATE INDEX lot_search_has_encumbrances_idx ON public_v1.lot_search (has_encumbrances);
CREATE INDEX lot_search_geom_idx ON public_v1.lot_search USING gist (geom);
-- Filtros do front: venda direta + deadline
CREATE INDEX lot_search_sale_mode_idx ON public_v1.lot_search (sale_mode)
  WHERE sale_mode <> 'leilao';
CREATE INDEX lot_search_direct_sale_deadline_idx ON public_v1.lot_search (direct_sale_deadline_at)
  WHERE direct_sale_deadline_at IS NOT NULL;

GRANT SELECT ON public_v1.lot_search TO anon, authenticated, service_role;

COMMENT ON MATERIALIZED VIEW public_v1.lot_search IS
  'Snapshot agregado de lots ativos + modality/occupancy/encumbrances + sale_mode. '
  'Refresh agendado em sql/public_v1_refresh.sql.';

-- IMPORTANTE: o DROP CASCADE acima removeu também public_v1.uf_stats e
-- public_v1.municipality_stats. Rode em seguida:
--   psql "$SUPABASE_DB_URL" -f sql/public_v1_stats_mv.sql
