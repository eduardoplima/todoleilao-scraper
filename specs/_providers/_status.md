# Recon arquitetural por provider — status

Gerado por `scripts/build_arch_status.py`. Não editar manualmente.

## Providers tentados

| provider | n_sites | passed_hard | fill_rate | bids | gotchas |
| --- | ---: | :---: | ---: | :---: | --- |
| `bomvalor` | 10 | ✅ | 84% | — | Provider BOMVALOR (Mercado Bomvalor) — plataforma multi-tenant brasileira. APA & BRF Leilões (apabrfleiloes.com.br) é tenant `apabrfleiloes` |
| `degrau_publicidade` | 26 | ✅ | 96% | ✅ | Provider Degrau Publicidade (footer/meta 'Sua Plataforma de Leilão \| Degrau Publicidade e Internet'). Multi-tenant com domínios próprios por |
| `leilao_br` | 18 | ✅ | 92% | — | Provider leilao_br (e-leiloes Nuxt SSR variant: confiancaleiloes/e-leiloeiro). Dados extraídos de <script id='__NUXT_DATA__'>. lances=[] no  |
| `leilao_pro` | 83 | ✅ | 84% | ✅ | Plataforma leilao_pro (Leilão Pro / leilao.pro). Provider NÃO expõe leilões encerrados publicamente — lots desaparecem do listing após o tér |
| `leiloes_judiciais_br` | 30 | ✅ | 72% | — | Provider leiloes_judiciais_br (canonical: leiloesjudiciais.com.br + state-specific subdomains tipo leiloesjudiciaismg.com.br). Plataforma Nu |
| `leiloesbr` | 6 | ✅ | 76% | ✅ | Provider LEILOESBR (Marcio Pinho — leiloesbr.com.br) NÃO trabalha com imóveis. Tenant amostrado: tbaracajuleiloes.com.br (Thiago Barros Card |
| `leiloesweb` | 3 | ✅ | 96% | ✅ | Provider leiloesweb (template ASP/PHP, encoding ISO-8859-1, Leilões Web - www.leiloesweb.com.br). Tenant: bampileiloes.com.br. Recon arquite |
| `leilotech` | 18 | ✅ | 92% | — | Provider leilotech (Laravel + Livewire, CDN cdn.leilotech.workers.dev). Estado completo do lote em <... wire:snapshot="..."> no HTML inicial |
| `mega_leiloes` | 2 | ✅ | 92% | ✅ | Provider Mega Leilões (megaleiloes.com.br) — plataforma proprietária PHP/Yii (Othis). Pilot ESCOLHIDO em leilão ENCERRADO/ARREMATADO via /le |
| `plataforma_leiloar` | 21 | ✅ | 92% | ✅ | Provider plataforma_leiloar (CakePHP 'Leiloar'). Pilot é leilão encerrado/suspenso com 2 lances públicos (NENE 07/08, freddf77 08/08 R$108.3 |
| `s4b_digital` | 43 | ✅ | 72% | — | Provider s4b_digital (NP/Eckert/JMF/Saladeleiloes/Barreto multi-tenant). API: offer-query.superbid.net + event-query.superbid.net. Bids hist |
| `sishp` | 6 | ✅ | 84% | ✅ | Plataforma SISHP (URLs /sishp/{leilao,arquivoAnexo,arquivoLogomarca}/...). Site sfrazao.com.br (Antônio Carlos Celso Santos Frazão / Victor  |
| `sodre_santoro` | 1 | ✅ | 88% | — | Provider Nuxt + API search-lots (Elasticsearch) + detalhes legacy PHP em leilao.sodresantoro.com.br. Pilot escolhido: imóvel (vaga de garage |
| `softgt` | 8 | ✅ | 84% | ✅ | Plataforma SoftGT (PHP+jQuery). Tenant: pbcastro (PR). Provider EXPÕE listing de leilões encerrados (/home-encerrado/, 156 leilões), MAS sem |
| `soleon` | 116 | ✅ | 84% | ✅ | Recon arquitetural do provider SOLEON (Soluções para Leilões Online), 116 tenants em data/intermediate/site_analysis.csv. Tenant amostrado:  |
| `suporte_leiloes` | 51 | ✅ | 88% | — | Recon arquitetural do provider suporte_leiloes (Suporte Leilões / SL). 51 sites em data/intermediate/site_analysis.csv apontam para esta pla |
| `wix` | 3 | ✅ | 80% | — | Provider 'wix' = tech-stack detector (Wix.com Website Builder), nao plataforma de leilao. Site arquimedesleiloes.com.br e pagina estatica de |
| `wordpress` | 10 | ✅ | 88% | ✅ | Recon arquitetural do provider 'wordpress' — bucket residual (10 tenants em data/intermediate/site_analysis.csv) marcando WordPress como tec |
| `palacio_dos_leiloes` | 5 | ❌ | 0% | — | — |

## Top 5 campos com pior fill-rate

| campo | fill-rate médio |
| --- | ---: |
| `address.cep` | 26% |
| `encumbrances_raw` | 28% |
| `bids` | 53% |
| `area_sqm` | 56% |
| `address.complement` | 72% |

## Providers em escopo ainda não tentados

Nenhum — todos os providers em escopo foram tentados.
