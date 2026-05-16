-- core.sale_mode + colunas em core.auction_lot pra suportar "venda direta".
--
-- Lots em "venda direta" não têm praças com data agendada — em vez disso,
-- aceitam propostas até um deadline. O spider hoje extrai data só de
-- "1º LEILÃO" / "2º LEILÃO" e marca status='desconhecido' qualquer outro
-- caso → front exibe ENCERRADO erroneamente.
--
-- Solução: campo dedicado em core.auction_lot que o spider preenche
-- quando o site indica "Venda direta disponível até: DD/MM/YYYY".
--
-- Aplicação:
--   psql "$SUPABASE_DB_URL" -f sql/sale_mode.sql
--
-- Backfill desnecessário — todos os lots existentes ficam 'leilao' default
-- (correto: snapshot atual é majoritariamente leilão).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sale_mode' AND typnamespace = 'core'::regnamespace) THEN
    CREATE TYPE core.sale_mode AS ENUM (
      'leilao',                  -- só 1ª/2ª praça
      'venda_direta',            -- só propostas com prazo
      'leilao_e_venda_direta'    -- ambos simultaneamente disponíveis
    );
  END IF;
END $$;

ALTER TABLE core.auction_lot
  ADD COLUMN IF NOT EXISTS sale_mode core.sale_mode NOT NULL DEFAULT 'leilao',
  ADD COLUMN IF NOT EXISTS direct_sale_deadline_at timestamptz;

-- Índice parcial — só lots em venda direta interessam pra filtros do front.
CREATE INDEX IF NOT EXISTS auction_lot_sale_mode_idx
  ON core.auction_lot (sale_mode)
  WHERE sale_mode <> 'leilao';

CREATE INDEX IF NOT EXISTS auction_lot_direct_sale_deadline_idx
  ON core.auction_lot (direct_sale_deadline_at)
  WHERE direct_sale_deadline_at IS NOT NULL;

COMMENT ON COLUMN core.auction_lot.sale_mode IS
  'Modalidade de venda do lot. Default leilao. venda_direta = aceita propostas até direct_sale_deadline_at sem praça agendada.';
COMMENT ON COLUMN core.auction_lot.direct_sale_deadline_at IS
  'Quando sale_mode != leilao, prazo final para propostas em venda direta. NULL em modo leilao puro.';
