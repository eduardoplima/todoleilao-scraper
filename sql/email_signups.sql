-- =============================================================================
-- email_signups.sql
-- Captura de leads (newsletter / "avise-me quando aparecer um lote do tipo X").
-- Versão 0.1.0 — 2026-05-10
--
-- O front já chama `sb.from('email_signups').insert(...)` com graceful
-- fallback. Quando esta tabela existir, signups começam a persistir sem
-- mudança de código no front.
--
-- LGPD: e-mail é dado pessoal de PF. Base legal: art. 7º I (consentimento)
-- + art. 7º V (execução de contrato — alerta solicitado pelo titular).
-- O titular pode pedir exclusão a qualquer momento (art. 18 LGPD).
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public_v1.email_signups (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email        text NOT NULL,
  source       text,                                  -- "footer", "alert_form", "first_visit"
  filters      jsonb,                                 -- filtros do alerta, opcional
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT email_signups_email_unique UNIQUE (email),
  CONSTRAINT email_signups_email_format CHECK (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$')
);

CREATE INDEX IF NOT EXISTS email_signups_created_at_idx
  ON public_v1.email_signups (created_at DESC);

-- Permissões mínimas: anon pode INSERT (newsletter signup) mas NÃO pode
-- SELECT (leak de e-mails seria vazamento). authenticated tampouco lê
-- por enquanto — admin futuro vai usar service_role.
GRANT USAGE ON SCHEMA public_v1 TO anon, authenticated;
GRANT INSERT (email, source, filters) ON public_v1.email_signups TO anon, authenticated;

-- Sem GRANT SELECT, GRANT UPDATE, GRANT DELETE para anon/authenticated.
-- O front que faz `INSERT` precisa adicionar `?on_conflict=email&select=` ou
-- chamar com Prefer: return=minimal pra evitar erro de read-after-write.

COMMENT ON TABLE public_v1.email_signups IS
  'Inscrições de newsletter / alertas. anon pode INSERT, ninguém lê via PostgREST. '
  'Acesso administrativo via service_role. Direito de exclusão (LGPD art. 18) '
  'manual via DPO no v1, automatizado depois.';

COMMIT;
