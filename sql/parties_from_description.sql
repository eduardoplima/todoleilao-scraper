-- parties_from_description.sql
--
-- Popula core.party + core.party_role_in_auction automaticamente quando
-- core.auction_lot.description ganha menção a banco/credor (regex via
-- core.extract_creditors).
--
-- Reuso: core.extract_creditors() já existe (sql/extract_creditors.sql) e
-- devolve text[] com bancos canônicos detectados na description.
--
-- Estratégia:
--   1. Função `core.upsert_creditor_party(lot_id uuid, bank_name text)`
--      - garante existência da party (PJ, display_name=bank_name)
--      - garante existência do role 'fiduciario' apontando para o lot
--      - idempotente
--   2. Trigger AFTER INSERT OR UPDATE OF description ON core.auction_lot
--      chama upsert_creditor_party() para cada banco em extract_creditors().
--
-- LIMITAÇÃO: a regra padrão usa role='fiduciario' (extrajudicial Lei 9.514).
-- Casos judiciais (role='exequente') ou venda direta não são inferidos aqui;
-- pipelines de spider podem chamar upsert_creditor_party explicitamente.

-- ---------------------------------------------------------------------------
-- Garantir UNIQUE em (party_id, lot_id, role) para INSERT idempotente.
-- (Tabela core.party_role_in_auction não tem essa constraint hoje.)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'party_role_in_auction_party_lot_role_unique'
  ) THEN
    ALTER TABLE core.party_role_in_auction
      ADD CONSTRAINT party_role_in_auction_party_lot_role_unique
      UNIQUE (party_id, lot_id, role);
  END IF;
END$$;

-- ---------------------------------------------------------------------------
-- Upsert helper. Idempotente.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.upsert_creditor_party(
  p_lot_id uuid,
  p_bank_name text,
  p_role core.party_role DEFAULT 'fiduciario'
) RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
  v_party_id uuid;
BEGIN
  -- Reusa party existente por display_name+kind (sem CNPJ disponível na
  -- extração via regex; melhoria futura: anexar tabela canônica de CNPJ).
  SELECT id INTO v_party_id
  FROM core.party
  WHERE kind = 'pessoa_juridica'
    AND lower(display_name) = lower(p_bank_name)
  LIMIT 1;

  IF v_party_id IS NULL THEN
    INSERT INTO core.party (kind, display_name, is_public_official, parser_version)
    VALUES ('pessoa_juridica', p_bank_name, false, 'extract_creditors_v1')
    RETURNING id INTO v_party_id;
  END IF;

  INSERT INTO core.party_role_in_auction (party_id, lot_id, role, notes)
  VALUES (v_party_id, p_lot_id, p_role, 'auto: extract_creditors')
  ON CONFLICT ON CONSTRAINT party_role_in_auction_party_lot_role_unique
  DO NOTHING;

  RETURN v_party_id;
END;
$$;

COMMENT ON FUNCTION core.upsert_creditor_party(uuid, text, core.party_role) IS
  'Garante existência de core.party (PJ) e core.party_role_in_auction para um banco/credor detectado na description. Idempotente.';

-- ---------------------------------------------------------------------------
-- Trigger: na inserção/update de description, popula parties.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.lot_extract_parties_trg()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_bank text;
BEGIN
  IF NEW.description IS NULL OR length(NEW.description) < 20 THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.description IS NOT DISTINCT FROM NEW.description THEN
    RETURN NEW;
  END IF;

  FOREACH v_bank IN ARRAY core.extract_creditors(NEW.description) LOOP
    PERFORM core.upsert_creditor_party(NEW.id, v_bank);
  END LOOP;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS auction_lot_extract_parties_trg ON core.auction_lot;
CREATE TRIGGER auction_lot_extract_parties_trg
  AFTER INSERT OR UPDATE OF description ON core.auction_lot
  FOR EACH ROW
  EXECUTE FUNCTION core.lot_extract_parties_trg();

COMMENT ON TRIGGER auction_lot_extract_parties_trg ON core.auction_lot IS
  'Popula core.party + core.party_role_in_auction (role=fiduciario) a partir de bancos detectados em description via core.extract_creditors.';

-- ---------------------------------------------------------------------------
-- Backfill — para lots já existentes no DB (rodar 1x).
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  r record;
  v_bank text;
BEGIN
  FOR r IN
    SELECT id, description
    FROM core.auction_lot
    WHERE description IS NOT NULL
      AND length(description) >= 20
      AND NOT EXISTS (
        SELECT 1 FROM core.party_role_in_auction pra
        WHERE pra.lot_id = core.auction_lot.id
      )
  LOOP
    FOREACH v_bank IN ARRAY core.extract_creditors(r.description) LOOP
      PERFORM core.upsert_creditor_party(r.id, v_bank);
    END LOOP;
  END LOOP;
END$$;
