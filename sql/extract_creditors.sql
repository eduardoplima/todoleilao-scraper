-- Função e atualização da MV `public_v1.lot_search` para expor o array
-- `creditors text[]` derivado da descrição do lote.
--
-- Bancos canônicos identificados via regex sobre core.auction_lot.description.
-- A lista cobre os credores mais frequentes em leilões judiciais (CPC) e
-- extrajudiciais (Lei 9.514) no Brasil. Falsos positivos são possíveis
-- (ex: "perto do Banco do Brasil" em endereço), mas o trade-off é aceitável
-- para o caso de uso "filtro por banco" no frontend.
--
-- Aplicação:
--   psql "$SUPABASE_DB_URL" -f sql/extract_creditors.sql
--   psql "$SUPABASE_DB_URL" -c "REFRESH MATERIALIZED VIEW public_v1.lot_search;"

CREATE OR REPLACE FUNCTION core.extract_creditors(description text)
RETURNS text[]
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT ARRAY(
    SELECT canonical
    FROM (
      VALUES
        ('Caixa Econômica Federal', '(?i)caixa\s+econ[oô]mica\s+federal|\mCEF\M'),
        ('Banco do Brasil',         '(?i)banco\s+do\s+brasil|\mBB\s+S\.?\s?A\M'),
        ('Banco Bradesco',          '(?i)\mbradesco\M'),
        ('Banco Santander',         '(?i)\msantander\M'),
        ('Banco Itaú',              '(?i)\mita[uú]\s+unibanco|\mbanco\s+ita[uú]\M'),
        ('Banco do Nordeste',       '(?i)banco\s+do\s+nordeste|\mBNB\M'),
        ('Banrisul',                '(?i)banrisul|banco\s+do\s+estado\s+do\s+rio\s+grande\s+do\s+sul'),
        ('BRB',                     '(?i)\mBRB\M|banco\s+de\s+bras[ií]lia'),
        ('Banco Votorantim',        '(?i)\mvotorantim\M'),
        ('Banco Inter',             '(?i)banco\s+inter\M'),
        ('Banco Safra',             '(?i)\msafra\M'),
        ('Sicoob',                  '(?i)\msicoob\M'),
        ('Sicredi',                 '(?i)\msicredi\M'),
        ('Banco Daycoval',          '(?i)\mdaycoval\M'),
        ('BTG Pactual',             '(?i)btg\s+pactual'),
        ('Nubank',                  '(?i)\mnubank\M|nu\s+pagamentos'),
        ('C6 Bank',                 '(?i)c6\s*bank'),
        ('Banco Original',          '(?i)banco\s+original'),
        ('HSBC',                    '(?i)\mHSBC\M'),
        ('Banco Fibra',             '(?i)banco\s+fibra')
    ) AS banks(canonical, pattern)
    WHERE description ~ pattern
  );
$$;

COMMENT ON FUNCTION core.extract_creditors(text) IS
  'Extrai credores/bancos mencionados na descrição de um lote (regex sobre 20 bancos canônicos). Retorna text[] que pode ser filtrado via @> (contains) no PostgREST.';

-- ---------------------------------------------------------------------------
-- Recreate MV adicionando coluna `creditors`
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
         lot_id,
         round_number,
         scheduled_at,
         minimum_bid,
         status
  FROM core.auction_round
  ORDER BY lot_id, scheduled_at ASC
),
primary_image AS (
  SELECT DISTINCT ON (lot_id)
         lot_id,
         source_url AS thumb_url
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
  -- Credores/bancos extraídos da descrição (NULL → array vazio).
  COALESCE(core.extract_creditors(al.description), '{}'::text[]) AS creditors
FROM core.auction_lot al
LEFT JOIN primary_unit pu  ON pu.lot_id = al.id
LEFT JOIN core.address ad  ON ad.id = pu.address_id
LEFT JOIN core.municipality m ON m.ibge_code = ad.municipality_code
LEFT JOIN next_round nr    ON nr.lot_id = al.id
LEFT JOIN primary_image pi ON pi.lot_id = al.id
WHERE al.current_status <> 'cancelado'
;

-- Índices (idênticos ao DDL original) + GIN para filtragem por creditor.
CREATE UNIQUE INDEX lot_search_pk
  ON public_v1.lot_search (lot_id);

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

CREATE INDEX lot_search_creditors_gin
  ON public_v1.lot_search USING GIN (creditors);

GRANT SELECT ON public_v1.lot_search TO anon, authenticated;
