-- =============================================================================
-- classify_unit_kind.sql
-- Classifica core.spatial_unit.kind a partir do texto de auction_lot.description
-- via regex priorizada. Resolve B1 — hoje 100% dos spatial_unit têm
-- kind='desconhecida' porque o spider nem populava o property_type.
--
-- Fase A do Caminho C (vide conversa). Backfill imediato + trigger pra
-- novos. Fase B (spider/pipeline) entra em commit separado.
--
-- Ordem das regras é deliberada — vai do mais específico pro mais
-- genérico. Match na primeira que casar.
--
-- Versão 0.1.0 — 2026-05-10
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- A. Classificador
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.classify_unit_kind(p_text text)
RETURNS core.unit_kind
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
  t text;
BEGIN
  IF p_text IS NULL OR length(trim(p_text)) = 0 THEN
    RETURN 'desconhecida';
  END IF;
  t := core.unaccent_lite(p_text);  -- lowercase + sem acentos

  -- Específicos (mais raros, mais distintos):
  IF t ~ '\mvaga\s+(de\s+)?garagem\M'                                     THEN RETURN 'vaga_garagem'; END IF;
  IF t ~ '\m(kitnet|kitchenette)\M'                                       THEN RETURN 'kitnet_studio'; END IF;
  IF t ~ '\m(studio|conjugado)\s+(resid|imobil)'                          THEN RETURN 'kitnet_studio'; END IF;
  IF t ~ '\m(flat\s+resid|apart-?hotel)\M'                                THEN RETURN 'flat'; END IF;
  IF t ~ '\msobrado\M'                                                    THEN RETURN 'sobrado'; END IF;
  IF t ~ '\mgalpao\M'                                                     THEN RETURN 'galpao'; END IF;
  IF t ~ '\m(sala\s+comercial|conjunto\s+comercial|salas?\s+\d+\s+do\s+predio)\M' THEN RETURN 'sala_comercial'; END IF;
  IF t ~ '\mloja\M' AND t !~ '\mlojista\M'                                THEN RETURN 'loja'; END IF;
  IF t ~ '\m(predio\s+(inteiro|comercial)|edificio\s+inteiro)\M'          THEN RETURN 'predio_inteiro'; END IF;

  -- Imóveis residenciais comuns:
  IF t ~ '\m(apartamento|aptos?\.?|cobertura|unidade\s+autonoma)\M'       THEN RETURN 'apartamento'; END IF;

  -- Rurais (antes de "casa", senão "casa de fazenda" cairia em casa):
  IF t ~ '\mfazenda\M'                                                    THEN RETURN 'fazenda'; END IF;
  IF t ~ '\msitio\M'                                                      THEN RETURN 'sitio'; END IF;
  IF t ~ '\mchacara\M'                                                    THEN RETURN 'chacara'; END IF;

  -- Frações (antes de terreno/casa):
  IF t ~ '\mfracao\s+(de|do|da|ideal)\s+(imovel|terreno|fazenda|casa|apartamento|matricula)' THEN RETURN 'cota_imovel'; END IF;
  IF t ~ '\mcota\s+(do|da|de)\s+(imovel|matricula)\M'                     THEN RETURN 'cota_imovel'; END IF;

  -- Terreno: rural primeiro (sinais de tamanho rural), depois urbano:
  IF t ~ '\m(terreno\s+rural|area\s+rural|gleba\s+rural|imovel\s+rural)\M' THEN RETURN 'terreno_rural'; END IF;
  IF t ~ '\m(\d+[\.,]?\d*)\s*(hectares?|alqueires|ha\b)' AND
     t ~ '\m(terreno|gleba|area|fazenda|imovel)\M'                         THEN RETURN 'terreno_rural'; END IF;
  IF t ~ '\m(terreno|lote\s+de\s+terreno|loteamento|lote\s+urbano)\M'     THEN RETURN 'terreno_urbano'; END IF;
  IF t ~ '\mgleba\M'                                                      THEN RETURN 'terreno_rural'; END IF;

  -- Casa: depois das exclusões acima (sobrado, fazenda, etc.):
  IF t ~ '\mcasa\s+(residencial|terrea|geminada|de\s+\d|n[°.\s]+\d)'       THEN RETURN 'casa'; END IF;
  IF t ~ '\m(uma\s+casa|residencia\s+unifamiliar)\M'                      THEN RETURN 'casa'; END IF;

  -- "imóvel residencial" / "imóvel comercial" (genéricos como tiebreaker):
  IF t ~ '\m(imovel|residencia)\s+residencial\M'                          THEN RETURN 'casa'; END IF;
  IF t ~ '\mimovel\s+comercial\M'                                         THEN RETURN 'sala_comercial'; END IF;

  -- "casa" sozinho (último; pode haver falsos positivos com "casa de força", "casa-grande"):
  IF t ~ '\mcasa\M' AND t !~ '\mcasa\s+(de\s+forca|grande)\M'              THEN RETURN 'casa'; END IF;

  -- "imóvel" genérico → tiebreaker conservador:
  IF t ~ '\mimovel\M'                                                      THEN RETURN 'outro'; END IF;

  RETURN 'desconhecida';
END;
$$;

-- -----------------------------------------------------------------------------
-- B. Aplicador por lot — atualiza todos os spatial_unit linkados a um lot.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.classify_lot_kinds(p_lot_id uuid)
RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
  v_text text;
  v_kind core.unit_kind;
  v_count int := 0;
BEGIN
  SELECT description INTO v_text FROM core.auction_lot WHERE id = p_lot_id;
  IF v_text IS NULL OR length(trim(v_text)) = 0 THEN
    RETURN 0;
  END IF;
  v_kind := core.classify_unit_kind(v_text);
  IF v_kind = 'desconhecida' THEN
    RETURN 0;
  END IF;

  UPDATE core.spatial_unit su
  SET kind = v_kind, updated_at = now()
  WHERE su.id IN (SELECT spatial_unit_id FROM core.lot_unit_link WHERE lot_id = p_lot_id)
    AND (su.kind = 'desconhecida' OR su.kind <> v_kind);
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

-- -----------------------------------------------------------------------------
-- C. Backfill em massa
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.classify_pending_lot_kinds(p_limit int DEFAULT 5000)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_id        uuid;
  v_processed int := 0;
  v_resolved  int := 0;
  v_updates   int;
BEGIN
  FOR v_id IN
    SELECT al.id
    FROM core.auction_lot al
    WHERE al.description IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM core.lot_unit_link lu
        JOIN core.spatial_unit su ON su.id = lu.spatial_unit_id
        WHERE lu.lot_id = al.id AND su.kind = 'desconhecida'
      )
    LIMIT p_limit
  LOOP
    v_updates := core.classify_lot_kinds(v_id);
    IF v_updates > 0 THEN
      v_resolved := v_resolved + 1;
    END IF;
    v_processed := v_processed + 1;
  END LOOP;
  RETURN jsonb_build_object('processed', v_processed, 'resolved', v_resolved);
END;
$$;

-- -----------------------------------------------------------------------------
-- D. Trigger pra novos lots
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION core.classify_lot_kind_trg() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.description IS NOT NULL AND coalesce(OLD.description, '') <> NEW.description THEN
    PERFORM core.classify_lot_kinds(NEW.id);
  END IF;
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS auction_lot_classify_kind_trg ON core.auction_lot;
CREATE TRIGGER auction_lot_classify_kind_trg
AFTER INSERT OR UPDATE OF description ON core.auction_lot
FOR EACH ROW EXECUTE FUNCTION core.classify_lot_kind_trg();

COMMIT;
