# Recon arquitetural por provider — síntese executiva

Snapshot dos resultados do `/recon-arch` (executado em 2026-05-01),
cruzando contagens de `data/intermediate/site_providers.csv` com os
artefatos por provider em `specs/_providers/<provider>/` (`validation.json`,
`recon.md`, `pilot_item.json`, `selectors.yaml`).

567 leiloeiros · 22 providers · 19 providers tentados (excluídos:
`proprio_html`, `desconhecido`, `parked_ww17`).

## Tabela 1 — provider × cobertura

| provedor | sites | % | blueprint | bids | nota crítica |
|---|---:|---:|:---:|:---:|---|
| soleon | 116 | 20.5% | ✅ | ✅ | cross-tenant via meta-refresh, 84% fill |
| proprio_html | 71 | 12.5% | ❌ | — | custom, Fase 2 caso-a-caso |
| leilao_pro | 83 | 14.6% | ✅ | ✅ | Mercure SSE em ativos, 84% fill |
| suporte_leiloes | 51 | 9.0% | ✅ | — | provider não publica encerrados, 88% |
| s4b_digital | 43 | 7.6% | ⚠️ | 🔒 | bids gated por 401 auth (Superbid Group) |
| desconhecido | 27 | 4.8% | ❌ | — | custom, Fase 2 caso-a-caso |
| leiloes_judiciais_br | 30 | 5.3% | ✅ | 🔒 | bids gated por login (Nuxt 3 SSR) |
| degrau_publicidade | 26 | 4.6% | ✅ | ✅ | ASP.NET ApiEngine, 96% fill (melhor cobertura) |
| plataforma_leiloar | 21 | 3.7% | ✅ | ✅ | CakePHP POST search, 92% fill |
| leilao_br | 18 | 3.2% | ⚠️ | — | blueprint só ~2/18 (Nuxt); resto Laravel |
| leilotech | 18 | 3.2% | ✅ | — | Livewire, bids só agregados, 92% |
| bomvalor | 10 | 1.8% | ✅ | 🔒 | bids login-gated, 84% |
| wordpress | 10 | 1.8% | ⚠️ | ✅ | heterogêneo (4 variants); só woo-uwa tem bids reais |
| parked_ww17 | 9 | 1.6% | ❌ | — | domínios em parking, **sem leilões** |
| softgt | 8 | 1.4% | ✅ | — | historico.php=500 em encerrados, pilot=ativo |
| leiloesbr | 6 | 1.1% | 🚫 | ✅ | **filatelia/numismática, NÃO imóveis** |
| sishp | 6 | 1.1% | ✅ | ✅ | encerrados na home (sem rota dedicada), 88% |
| palacio_dos_leiloes | 5 | 0.9% | 🚫 | — | **0 imóveis (só auto/eletro/maquinário)** |
| wix | 3 | 0.5% | ❌ | — | tech-stack, não plataforma; cada site único |
| leiloesweb | 3 | 0.5% | ✅ | ✅ | ISO-8859-1, 96% fill |
| mega_leiloes | 2 | 0.4% | ✅ | ✅ | 8 lances mascarados nativos, 92% |
| sodre_santoro | 1 | 0.2% | ✅ | — | encerrados não expostos, 88% |

**Legenda blueprint**:
- ✅ pronto — selectors portáveis, item-piloto válido em `specs/_providers/<provider>/`
- ⚠️ parcial — blueprint cobre só subconjunto (auth-gated, stack heterogêneo, etc.)
- ❌ caso-a-caso — provider sem padrão multi-tenant (custom HTML); cair no `/recon-batch` por leiloeiro
- 🚫 fora de escopo — não publica imóveis (filatelia, automotivo, parking)

**Legenda bids**:
- ✅ extraídos publicamente, sem auth
- 🔒 existem mas exigem login/auth para acessar
- — não disponíveis pelo provider

## Tabela 2 — cobertura agregada

| Categoria | Sites | % | Conteúdo |
|---|---:|---:|---|
| ✅ Blueprint pronto | 375 | 66.1% | 13 providers, spider direto: soleon, leilao_pro, suporte_leiloes, leiloes_judiciais_br, degrau_publicidade, plataforma_leiloar, leilotech, bomvalor, softgt, sishp, sodre_santoro, mega_leiloes, leiloesweb |
| ⚠️ Blueprint parcial | 71 | 12.5% | s4b_digital (43, auth) + leilao_br (18, só Nuxt) + wordpress (10, heterogêneo) |
| ❌ Caso-a-caso | 101 | 17.8% | proprio_html (71) + desconhecido (27) + wix (3) |
| 🚫 Fora de escopo | 20 | 3.5% | parked_ww17 (9) + leiloesbr (6, filatelia) + palacio_dos_leiloes (5, automotivo) |
| **Total** | **567** | **100%** | |

## Tabela 3 — bids por provider (em escopo)

Providers que expuseram histórico de lances publicamente (9):

| provedor | sites | mecanismo |
|---|---:|---|
| soleon | 116 | tabela HTML em detalhe |
| leilao_pro | 83 | Mercure SSE (em ativos; encerrados não expostos) |
| degrau_publicidade | 26 | XHR `/ApiEngine/GetLancesPropostasLote` |
| plataforma_leiloar | 21 | tabela HTML após POST search (CakePHP) |
| wordpress | 10 | só na variante woo-uwa (bid history em meta WC) |
| sishp | 6 | tabela HTML na própria home |
| leiloesweb | 3 | tabela HTML em `/leilao/detalhe_leilao/{id}` |
| mega_leiloes | 2 | tabela com 8 lances mascarados nativos |
| **soma** | **267** | **47.1% dos sites totais** |

Auth-gated (extraível com credenciais futuras):

| provedor | sites |
|---|---:|
| s4b_digital | 43 |
| leiloes_judiciais_br | 30 |
| bomvalor | 10 |
| **soma** | **83** |

## Insights

1. **78.7% dos 567 leiloeiros (446 sites) cabem em 15 spiders de provider** — em vez de 567 spiders individuais.
2. Os **9 providers com `bids:✅` representam 267 sites (47%)** com histórico de lances público — base para análise de comportamento de arrematantes na Fase 2.
3. Filtros importantes para o pipeline da Fase 2:
   - **Excluir antes de descobrir imóveis**: `parked_ww17`, `leiloesbr`, `palacio_dos_leiloes` (20 sites onde não há imóveis a coletar).
   - **Adicionar credenciais para bids**: 83 sites em `s4b_digital` + `leiloes_judiciais_br` + `bomvalor` se quisermos histórico completo.
4. **`leilao_br` precisa de blueprint complementar**: o atual cobre só ~2/18 sites (Nuxt SSR); restante usa Laravel — abrir provider derivado `leilao_br_laravel` faz sentido na Fase 2.
5. **`wordpress` e `wix`** confirmam que **detecção por tech-stack genérico** é fraca para definir spider. Os 3 sites Wix são marketing-only; os 10 WordPress têm 4 plugins WC distintos — cada um exige seu próprio fingerprint.

## Como reproduzir / atualizar

```bash
# Re-classifica providers com base no HTML cacheado (rápido, offline)
uv run python scripts/detect_providers.py

# Re-mapeia arquitetura de cada provider (lento; varre 19 providers sequencialmente)
/recon-arch

# Atualiza este sumário (manualmente — não há script automático)
# Fonte: reports/providers.md (totais) + specs/_providers/_status.md (status por provider)
```

## Arquivos-fonte

- `data/intermediate/site_providers.csv` (gitignored) — 1 linha por leiloeiro: provider classificado.
- `reports/providers.md` — tabelas de totais por provider.
- `specs/_providers/<provider>/recon.md` — narrativa arquitetural (URLs, paginação, gotchas).
- `specs/_providers/<provider>/selectors.yaml` — blueprint declarativo (selectors CSS/XPath).
- `specs/_providers/<provider>/pilot_item.json` — item-piloto extraído (com `bids[]` quando exposto).
- `specs/_providers/<provider>/validation.json` — passed_hard + fill_rate.
- `specs/_providers/_status.md` — status agregado por provider (gerado).
