-- =============================================================================
-- bootstrap_lot_address.sql
-- Cria core.address mínimo (uf + municipality_code + geom centroide) pra
-- lots cujo spider não conseguiu extrair endereço estruturado.
--
-- Resolve B6 — 32/1033 lots ficam invisíveis no front por falta de
-- municipality_name (filtro de UF/cidade não os mostra).
--
-- Estratégia: regex permissivo extrai "City / UF" do fim da description,
-- match IBGE, cria address+spatial_unit+ba_unit+lot_unit_link sintéticos
-- com geocoding_source='municipality_centroid' (mesma qualidade que os
-- outros lots municipais).
--
-- Versão 0.1.0 — 2026-05-10
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- A. Extrator permissivo (sem exigir "Cidade:" prefix)
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.try_extract_city_uf(p_text text)
RETURNS TABLE (city text, uf text)
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
  m text[];
BEGIN
  IF p_text IS NULL THEN RETURN; END IF;
  -- Tenta padrão "City / UF" próximo ao fim. Aceita:
  --   "Florianópolis/SC"
  --   "Belo Horizonte / MG"
  --   "São José do Rio Preto - SP"
  -- Bem permissivo — pega último match porque description pode ter
  -- vários "/" ou "-" antes (ex.: "12/06/2026 às 14:00").
  m := regexp_match(
    p_text,
    '([A-Z][A-Za-zÀ-ÿ\s.''-]{2,40})\s*[/\-]\s*([A-Z]{2})(?:\s|\.|$|,|"|<)',
    ''
  );
  IF m IS NULL THEN RETURN; END IF;
  city := trim(m[1]);
  uf := upper(trim(m[2]));
  -- Filtros de falso-positivo — palavras-chave indicativas de não-cidade
  IF length(city) < 3 THEN RETURN; END IF;
  IF city ~* '^(às|em|de|da|do|no|na|para|por|com|sem|leil|R\$|\d|lote|tipo|valor)' THEN RETURN; END IF;
  RETURN NEXT;
END;
$$;

-- -----------------------------------------------------------------------------
-- B. Bootstrap por lot
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.bootstrap_lot_address(p_lot_id uuid)
RETURNS boolean
LANGUAGE plpgsql AS $$
DECLARE
  v_desc      text;
  v_source_id uuid;
  v_extracted record;
  v_ibge      core.ibge_municipality_code;
  v_addr_id   uuid;
  v_su_id     uuid;
  v_centroid  extensions.geometry;
BEGIN
  -- Skip se já tem address linkada
  IF EXISTS (
    SELECT 1 FROM core.lot_unit_link lu
    JOIN core.spatial_unit su ON su.id = lu.spatial_unit_id
    JOIN core.address a ON a.id = su.address_id
    WHERE lu.lot_id = p_lot_id
  ) THEN RETURN false; END IF;

  SELECT description, source_id INTO v_desc, v_source_id
  FROM core.auction_lot WHERE id = p_lot_id;
  IF v_desc IS NULL OR length(trim(v_desc)) < 10 THEN RETURN false; END IF;

  SELECT * INTO v_extracted FROM core.try_extract_city_uf(v_desc) LIMIT 1;
  IF v_extracted IS NULL OR v_extracted.uf IS NULL THEN RETURN false; END IF;

  v_ibge := core.match_municipality(v_extracted.uf, v_extracted.city);
  IF v_ibge IS NULL THEN RETURN false; END IF;

  SELECT centroid INTO v_centroid FROM core.municipality WHERE ibge_code = v_ibge;

  -- Cria address mínimo
  INSERT INTO core.address (uf, municipality_code, geom, geocoding_source, raw_text)
  VALUES (v_extracted.uf, v_ibge, v_centroid, 'municipality_centroid_bootstrap', v_desc)
  RETURNING id INTO v_addr_id;

  -- Reusa spatial_unit existente do lot (criado pelo pipeline) ou cria novo
  SELECT su.id INTO v_su_id
  FROM core.lot_unit_link lu
  JOIN core.spatial_unit su ON su.id = lu.spatial_unit_id
  WHERE lu.lot_id = p_lot_id
  ORDER BY su.created_at LIMIT 1;

  IF v_su_id IS NOT NULL THEN
    UPDATE core.spatial_unit SET address_id = v_addr_id, updated_at = now()
    WHERE id = v_su_id AND address_id IS NULL;
  ELSE
    INSERT INTO core.spatial_unit (kind, address_id, source_id)
    VALUES ('desconhecida', v_addr_id, v_source_id)
    RETURNING id INTO v_su_id;
    INSERT INTO core.lot_unit_link (lot_id, spatial_unit_id) VALUES (p_lot_id, v_su_id)
    ON CONFLICT DO NOTHING;
    INSERT INTO core.ba_unit (spatial_unit_id, source_id) VALUES (v_su_id, v_source_id)
    ON CONFLICT DO NOTHING;
  END IF;

  -- Re-classifica kind agora que tem mais material
  PERFORM core.classify_lot_kinds(p_lot_id);

  RETURN true;
END;
$$;

-- -----------------------------------------------------------------------------
-- C. Batch
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.bootstrap_pending_addresses(p_limit int DEFAULT 1000)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_id        uuid;
  v_processed int := 0;
  v_resolved  int := 0;
BEGIN
  FOR v_id IN
    SELECT al.id FROM core.auction_lot al
    WHERE al.description IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM core.lot_unit_link lu
        JOIN core.spatial_unit su ON su.id = lu.spatial_unit_id
        JOIN core.address a ON a.id = su.address_id
        WHERE lu.lot_id = al.id
      )
    LIMIT p_limit
  LOOP
    IF core.bootstrap_lot_address(v_id) THEN
      v_resolved := v_resolved + 1;
    END IF;
    v_processed := v_processed + 1;
  END LOOP;
  RETURN jsonb_build_object('processed', v_processed, 'resolved', v_resolved);
END;
$$;

COMMIT;
