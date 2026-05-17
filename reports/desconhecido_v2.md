# Análise do bucket `desconhecido` (v2)

Investigação dos 47 sites classificados como `provider=desconhecido` em
`site_providers_v2.csv`. HTML cached lido localmente (preferência static,
fallback dynamic); sem fetch HTTP. Identificadas duas classes de pistas:
(a) **N leiloeiros distintos do INNLEI resolvendo para o mesmo host** — sinal
forte de plataforma compartilhada/operador único; (b) **template Laravel +
Inertia.js** com `<title inertia>`, `data-page=`, `/build/assets/app-*.css` e
`<meta name="csrf-token">` — mesmo stack visual em 4 sites distintos.

## Candidatos a novo provider (>=3 sites)

| nome sugerido | assinatura (regex/host) | n | sites |
|---|---|--:|---|
| `portal_zuk` | host == `portalzuk.com.br` OR `cdn.portalzuk.com.br` no html OR `asseturl = "https://cdn.portalzuk.com.br/` | 7 | portalzuk.com.br (Dora Plat x5, Zukerman, Badolato) |
| `inertia_laravel_leiloes` | `<title\s+inertia` E `data-page=` E `/build/assets/app-[A-Za-z0-9_-]+\.css` | 4 | globoleiloes.com.br, balbinoleiloes.com.br, satoleiloes.com.br, peracchileiloes.com.br |
| `globo_leiloes` | host == `globoleiloes.com.br` (cluster de 4 leiloeiros INNLEI) | 4 | globoleiloes.com.br |
| `balbino_leiloes` | host == `balbinoleiloes.com.br` (família Balbino, 5 leiloeiros) | 5 | balbinoleiloes.com.br |
| `deseulance` | host == `deseulance.com` (Deseulance Ltda — 4 leiloeiros DCB) | 4 | deseulance.com |
| `parque_dos_leiloes` | host == `parquedosleiloes.com.br` OR `"dynUrl"` meta + `Desenvolvido por BRClick` | 3 | parquedosleiloes.com.br (Braggio, Tavares) |
| `gp_leiloes` | host == `gpleiloes.com.br` (3 leiloeiros MG) | 3 | gpleiloes.com.br |

Observação: `inertia_laravel_leiloes` é template-level — sobrepõe os hosts
`globoleiloes` + `balbinoleiloes` + `satoleiloes` + `peracchileiloes`. Provavelmente é o vendor real
(mesmo Laravel+Vite+Inertia, componente "Home/Index", paleta idêntica). Os
hosts individuais podem ser sub-providers ou white-labels do mesmo SaaS.
Confirmação visual recomendada antes de promover.

## Outros sinais < 3 sites (não promovidos)

- `simonleiloes.com.br` (2 slugs) — Next.js (`_next/static`) custom build.
- `satoleiloes.com.br` (2 slugs) — coberto pelo template Inertia acima.
- `d335luupugsy2.cloudfront.net` aparece em ~80 sites do dataset inteiro,
  mas hospeda principalmente `rdstation-forms` (marketing widget RD Station)
  e loaders de chat — sinal fraco, não é plataforma de leilão.

## Sites que permanecem `proprio_html` legítimo (1 slug cada, sem assinatura compartilhada)

odarlicanezinleiloes.com.br, vitorcalableiloeiro.com.br, leiloeirodian.com.br
(footer "Desenvolvido por marianocampagnaro" — desenvolvedor freelance),
jorgebrasil.lel.br, leiloariasmart.com.br, kwara.com.br (marketplace próprio
Kwara), simoesleiloes.com.br, usadaomaquinas.com.br, fnbassets.com.br (site
institucional da FNBASSETS — não é cliente, é vendor sem clientes detectados
neste batch), ffaconstrutora.com.br (Mailchimp embed, site construtora),
tokleiloes.com.br, adaleiloes.com.br ("almost here" placeholder),
norteleiloes.com.br ("Desenvolvido por" truncado, dev anônimo),
tableau.com.br, fernandobraga.lel.br (Laravel custom mas single-site),
grupocarvalholeiloes.com.br.

## Recomendação

Adicionar 2 regras prioritárias ao `detect_providers.py`:
1. `rule_portal_zuk` antes de qualquer regra genérica — cobre 7 sites.
2. `rule_inertia_laravel_leiloes` cobrindo o template Vite+Inertia — cobre 4
   sites e provavelmente captura mais quando aplicada ao dataset inteiro
   (rodar `rg` por `<title inertia>` no cache antes de promover).
Hosts isolados (`balbino_leiloes`, `globo_leiloes`, `deseulance`,
`parque_dos_leiloes`, `gp_leiloes`) podem virar regras host-based simples se a
estratégia futura tratar cada operador como provider.
