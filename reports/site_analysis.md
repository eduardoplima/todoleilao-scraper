# Análise dos sites dos leiloeiros (fases 4-5)

Consolidação dos artefatos de descoberta para os **567 candidatos** que passaram em `confidence ∈ {high, medium}` no `filter_real_estate` e cujos sites externos foram analisados em `site_analyzer` + `listing_finder`.

_Gerado a partir de `data/intermediate/site_analysis.csv` + `listing_urls.csv`._

## TL;DR

- **Total analisado**: 567
- **Sites acessíveis** (sem erro de rede): 566 (99.8%)
- **Listing URL identificada**: 392 (69.1%)
- **Validação OK** (≥5 itens com preço na URL candidata): 280 (49.4%)
- **Precisam de revisão manual**: 287 (50.6%)
- **Sites que exigem JS para mostrar listagem**: 86 (15.2%)

## Distribuição de rendering

![Distribuição de rendering](figures/rendering_distribution.png)

| rendering | sites | % |
|---|---:|---:|
| `static` | 378 | 66.7% |
| `hybrid` | 61 | 10.8% |
| `dynamic` | 120 | 21.2% |
| `unknown` | 8 | 1.4% |
| **total** | **567** | 100.0% |

Leitura: `static` é JSP/PHP/SSR retornando o HTML completo na resposta inicial; `dynamic` exige JavaScript pra popular a listagem; `hybrid` mistura — parte vem no HTML, parte é hidratada client-side; `unknown` quando nem httpx nem Playwright encontraram links úteis (sites com home minimalista ou bloqueados).

## Top 10 com mais imóveis detectados

Métrica = ocorrências de preço (`R$ X.XXX,XX`) na URL candidata da listagem, via httpx.

| # | leiloeiro | UF | site | rendering | listing_url | items |
|---:|---|---|---|---|---|---:|
| 1 | JEFÉRSON BENEDETTO | RS | https://www.benedettoleiloes.com.br | hybrid | https://www.benedettoleiloes.com.br/leiloes | 205 |
| 2 | Kátia Cerqueira da Silva Casaes | BA | https://www.kcleiloes.com.br/ | static | https://mercado.bomvalor.com.br/kcleiloes/katia-cerqueira-da-silva-casaes/imove… | 162 |
| 3 | BRUNO DUARTE ARAÚJO DOS SANTOS | DF | https://www.oaleiloes.com.br | static | https://www.oaleiloes.com.br/leilao/361 | 156 |
| 4 | ORLANDO ARAÚJO DOS SANTOS | DF | https://www.oaleiloes.com.br | static | https://www.oaleiloes.com.br/leilao/361 | 156 |
| 5 | MOACIRA TEGONI GOEDERT | DF | https://www.moacira.lel.br | static | https://www.moacira.lel.br/leilao/730 | 151 |
| 6 | Milena Rosa Di Giacomo Adri | TO | https://www.megaleiloes.com.br/ms | static | https://www.megaleiloes.com.br/imoveis | 138 |
| 7 | FERNANDO JOSE CERELLO GONCALVES PEREIRA | MT | https://www.megaleiloes.com.br | hybrid | https://www.megaleiloes.com.br/imoveis | 138 |
| 8 | LEVY DOS SANTOS MORAES FILHO | SC | https://www.santosmoraesleiloes.com.br | static | https://leiloessantosmoraes.com.br/externo/leilao/127/leilao-senad-secretaria-n… | 130 |
| 9 | Thaís Costa Bastos Teixeira | MG | https://www.leiloesjudiciaismg.com.br | static | https://www.leiloesjudiciaismg.com.br/imoveis | 105 |
| 10 | JORGE VITORIO ESPOLADOR | PR | https://www.jeleiloes.com.br | hybrid | https://www.jeleiloes.com.br/leiloes/2780 | 102 |

## Plano de implementação dos spiders

Ordenamos por **(rendering, items_detected desc)**: estáticos primeiro (simples Scrapy + parse), depois hybrid (Scrapy com pequenas concessões), depois dynamic (precisam de `scrapy-playwright`).

### Bloco 1 — `rendering = static` (top 20)

| ord | leiloeiro | UF | site | listing_url | items | tech_stack |
|---:|---|---|---|---|---:|---|
| 1 | Kátia Cerqueira da Silva Casaes | BA | https://www.kcleiloes.com.br/ | https://mercado.bomvalor.com.br/kcleiloes/katia-cerqueira-d… | 162 | jQuery; Bootstrap |
| 2 | BRUNO DUARTE ARAÚJO DOS SANTOS | DF | https://www.oaleiloes.com.br | https://www.oaleiloes.com.br/leilao/361 | 156 | jQuery; Bootstrap |
| 3 | ORLANDO ARAÚJO DOS SANTOS | DF | https://www.oaleiloes.com.br | https://www.oaleiloes.com.br/leilao/361 | 156 | jQuery; Bootstrap |
| 4 | MOACIRA TEGONI GOEDERT | DF | https://www.moacira.lel.br | https://www.moacira.lel.br/leilao/730 | 151 | jQuery; Bootstrap |
| 5 | Milena Rosa Di Giacomo Adri | TO | https://www.megaleiloes.com.br/ms | https://www.megaleiloes.com.br/imoveis | 138 | jQuery; Bootstrap; Mega Leilões |
| 6 | LEVY DOS SANTOS MORAES FILHO | SC | https://www.santosmoraesleiloes.com.br | https://leiloessantosmoraes.com.br/externo/leilao/127/leila… | 130 | jQuery; Bootstrap |
| 7 | Thaís Costa Bastos Teixeira | MG | https://www.leiloesjudiciaismg.com.br | https://www.leiloesjudiciaismg.com.br/imoveis | 105 | WordPress; Nuxt; Vue; Superbid |
| 8 | SÉRGIO DE PAULA PEREIRA | ES | https://www.esleiloes.com.br/ | https://www.esleiloes.com.br/eventos/leilao/36/policia-civi… | 98 | nan |
| 9 | VICENTE DE PAULO ALBUQUERQUE COSTA… | AM | https://www.vipleiloes.com.br | https://www.leilaovip.com.br/ | 84 | jQuery; Bootstrap |
| 10 | VICENTE DE PAULO A. COTA FILHO | AM | https://www.vipleiloes.com.br | https://www.leilaovip.com.br/ | 84 | jQuery; Bootstrap |
| 11 | Mariana Gouvêa Lessa&nbsp; | RO | https://www.vipleiloes.com.br | https://www.leilaovip.com.br/ | 84 | jQuery; Bootstrap |
| 12 | Rodrigo Schmitz | BA | https://www.hammer.lel.br | https://www.hammer.lel.br/leilao/1829/lotes | 60 | jQuery; Bootstrap |
| 13 | ANGELICA MIEKO INOUE DANTAS | SP | https://WWW.LANCETOTAL.COM.BR | https://lancetotal.com.br/leilao.php?idLeilao=1103 | 60 | jQuery; Bootstrap |
| 14 | Angela Eiko Inoque dos Santos | PI | https://www.lancetotal.com.br/ | https://lancetotal.com.br/leilao.php?idLeilao=1103 | 60 | jQuery; Bootstrap |
| 15 | Cassiano Ricardo Dall Ago e Silva | PI | https://www.cassianoleiloes.com.br | https://www.cassianoleiloes.com.br/lotes/imovel | 60 | jQuery; Bootstrap |
| 16 | DARCI MULLER | RS | http://www.mullerleiloes.com.br | https://www.mullerleiloes.com.br/lotes/imovel | 54 | jQuery; Bootstrap |
| 17 | DANIEL COSTA MÜLLER | RS | http://www.mullerleiloes.com.br | https://www.mullerleiloes.com.br/lotes/imovel | 54 | jQuery; Bootstrap |
| 18 | ALEXANDRE RECH | RS | https://www.rechleiloes.com.br | https://www.rechleiloes.com.br/lotes/imovel | 53 | jQuery; Bootstrap |
| 19 | Viviane Garzon Corrêa | MG | https://www.bolsadeleiloes.com.br | https://www.bolsadeleiloes.com.br/leilao/496 | 50 | jQuery; Bootstrap |
| 20 | RENI JOSÉ BONFANDINI | RS | https://www.leiloesbonfadini.com.br | https://leiloesbonfadini.com.br/arroio-do-meio/ | 48 | WordPress |

### Bloco 2 — `rendering = hybrid` (top 10)

| ord | leiloeiro | UF | site | listing_url | items | tech_stack |
|---:|---|---|---|---|---:|---|
| 21 | JEFÉRSON BENEDETTO | RS | https://www.benedettoleiloes.com.br | https://www.benedettoleiloes.com.br/leiloes | 205 | Vue; jQuery; Bootstrap |
| 22 | FERNANDO JOSE CERELLO GONCALVES PE… | MT | https://www.megaleiloes.com.br | https://www.megaleiloes.com.br/imoveis | 138 | jQuery; Bootstrap; Mega Leilões |
| 23 | JORGE VITORIO ESPOLADOR | PR | https://www.jeleiloes.com.br | https://www.jeleiloes.com.br/leiloes/2780 | 102 | jQuery; Bootstrap |
| 24 | Italo Trindade Moura Filho | PI | https://www.italoleiloes.com | https://www.italoleiloes.com/leiloes | 101 | jQuery; Bootstrap |
| 25 | DIOGO MATTOS DIAS MARTINS | AL | https://www.inovaleilao.com.br | https://www.inovaleilao.com.br/subcategorias/2#resultados | 81 | jQuery; Bootstrap |
| 26 | Lucas Kury Dias Martins | AL | https://www.inovaleilao.com.br | https://www.inovaleilao.com.br/subcategorias/2#resultados | 81 | jQuery; Bootstrap |
| 27 | VICENTE ALVES PEREIRA NETO | SC | https://www.agencialeilao.com.br | https://www.agencialeilao.com.br/leiloes | 48 | jQuery; Bootstrap |
| 28 | JOÃO ANTÔNIO CARGNELUTTI | RS | https://www.cargneluttileiloes.com.br | https://www.cargneluttileiloes.com.br/lotes/imovel | 43 | jQuery; Bootstrap |
| 29 | ERNI CARLOS ORO | RS | https://www.oroleiloes.lel.br | https://www.oroleiloes.lel.br/lotes/imovel | 43 | jQuery; Bootstrap |
| 30 | JOÍO ANTÔNIO CARGNELUTTI | RS | http://www.cargneluttileiloes.com.br | https://www.cargneluttileiloes.com.br/lotes/imovel | 43 | jQuery; Bootstrap |

### Bloco 3 — `rendering = dynamic` (top 10)

| ord | leiloeiro | UF | site | listing_url | items | tech_stack |
|---:|---|---|---|---|---:|---|
| 31 | José Luiz Pereira Vizeu | DF | https://www.flexleiloes.com.br | https://www.flexleiloes.com.br/imoveis/ | 40 | jQuery; Bootstrap |
| 32 | Luciano Resende Rodrigues | SC | https://www.lancecertoleiloes.com.br | https://www.lancecertoleiloes.com.br/leilao/050526PART | 33 | jQuery; Bootstrap |
| 33 | BEATRIZ SILVA CARVALHO | PR | https://www.grupocarvalholeiloes.com.br | https://www.grupocarvalholeiloes.com.br/leilao/leilao-publi… | 28 | Next.js |
| 34 | CARLOS CAMPANHÃ | SP | https://www.projudleiloes.com.br | https://www.projudleiloes.com.br/leilao/lapa-moveis-escrito… | 21 | jQuery; Bootstrap |
| 35 | Fábio Maciel Amarante | MG | https://www.nortedeminasleiloes.com.br | https://nortedeminasleiloes.com.br/leilao | 12 | jQuery; Bootstrap |
| 36 | TATIANA PAULA ZANI DE SOUZA | DF | https://www.liderleiloes.com.br | https://www.liderleiloes.com.br/leiloes/163 | 11 | jQuery; Bootstrap |
| 37 | CAROLINE DE SOUSA RIBAS | DF | https://www.liderleiloes.com.br | https://www.liderleiloes.com.br/leiloes/163 | 11 | jQuery; Bootstrap |
| 38 | TATIANA PAULA ZANI DE SOUSA | DF | https://www.liderleiloes.com.br | https://www.liderleiloes.com.br/leiloes/163 | 11 | jQuery; Bootstrap |
| 39 | POLIANA MIKEJEVS CALÇA | PR | https://www.superbid.net | https://www.superbid.net/oferta/imovel-residencial-e-comerc… | 8 | WordPress; Next.js; Superbid |
| 40 | MARCELO VALLAND | DF | https://www.valland.com.br | https://www.hastapublica.com.br/lote/103647/Imóvel-industri… | 7 | jQuery; Bootstrap |

Observação: muitos leiloeiros compartilham domínios (ex.: `*.leilao.br`, `shopleiloes.*`, `superbid`). Antes de começar, **dedupe por domínio raiz** para evitar 280 spiders quando o número real de plataformas é uma fração disso.

Estimativa rápida: as 280 linhas validadas usam apenas ~**220** hosts distintos.

## Sites para revisão manual

São **287 sites** (50.6%) onde o detector achou <5 itens com preço na URL candidata. Causas mais comuns: layouts que não casam com o vocab de keywords, SPAs que precisam de JS na própria listagem (o validate é httpx-only), ou sites institucionais sem catálogo na home.

### Por categoria

| confidence | rendering | sites |
|---|---|---:|
| high | dynamic | 78 |
| high | hybrid | 12 |
| high | static | 111 |
| high | unknown | 1 |
| medium | dynamic | 20 |
| medium | hybrid | 6 |
| medium | static | 53 |
| medium | unknown | 6 |

### Lista (até 50 primeiros)

| leiloeiro | UF | site | confidence | rendering | requires_js | nota |
|---|---|---|---|---|:---:|---|
| Felipe Gonzaga Daux | SC | https://www.daux.com.br | high | static | N | nan |
| NATÁLIA NARITA NUNES DE FREITAS | DF | https://www.natalialeiloes.com.br | high | static | N | nan |
| UNO DUARTE ARAÚJO DOS SANTOS | DF | https://www.leiloes61.com.br | high | static | N | nan |
| Mauro Colodete | PE | https://colodeteleiloes.com.br/ | high | static | N | nan |
| CLAUDIO SOUSA DOS SANTOS | SP | https://www.allianceleiloes.com.br | high | static | N | nan |
| DEDIANA FARIAS | RS | https://www.fariasleiloes.com.br | high | static | N | nan |
| DÉBORA REGINA BARZ | RS | https://www.deborabarzleiloes.com.br | high | static | N | nan |
| Diego Wolf De Oliveira | SC | https://www.diegoleiloes.com.br | high | static | N | nan |
| Regina Aude Leite De Araujo Silva | MS | https://www.reginaaudeleiloes.com.br | high | static | N | nan |
| DÉBORA JANAÍNA MÜLLER CORTES | RS | http://www.deboramullerleiloes.com.br | high | static | N | nan |
| SILVIA HELENA BALBINO BARROS PALMA | DF | https://www.leilomaster.com.br | high | static | N | nan |
| César Luis Moresco | DF | https://www.morescoleiloes.com.br | high | static | N | nan |
| MÁRIO LESSA FREITAS FILHO | RS | https://www.lessaleiloes.com.br | high | static | N | nan |
| GALVÍO ADENYR LOPES JUNIOR | PR | http://www.lancejusto.com.br | high | static | N | nan |
| NEWTON JORGE GONÇALVES DE OLIVEIRA | PR | https://www.newtonleiloes.com.br/ | high | static | N | nan |
| VANESSA GOELZER DE ARAÚJO VARGAS E… | PR | https://www.vargasepintoleiloes.com.br | high | static | N | nan |
| FERNANDA VON ZUCCALMAGLIO | RS | https://www.zuccalmaglioleiloes.com.br | high | static | N | nan |
| GALVÃO ADENYR LOPES JUNIOR | PR | https://www.lancejusto.com.br | high | static | N | nan |
| EDUARDO VIVIAN | RS | https://www.eduardovivian.com | high | static | N | nan |
| JOÍO HONOR COIROLLO DE SOUZA | RS | http://www.jhcleiloeirooficial.lel.br | high | static | N | nan |
| JUSSIARA SANTOS ERMANO SUKIENNIK | DF | https://www.jussiaraleiloes.com | high | static | N | nan |
| Rodrigo de Oliveira Lopes | MG | https://www.leiloesuberlandia.com.br | high | static | N | nan |
| Luiz Washington Campolina Santos | MG | https://www.luizcampolina.com.br | high | static | N | nan |
| Diórgenes Valério Jorge | SC | https://www.catarinenseleiloes.com.br | high | static | N | nan |
| ODILSON FUMAGALLI AVILA | RS | https://www.fumagallileiloes.com.br | high | static | N | nan |
| Quênia De Luca Martins | SC | https://www.leiloes-sc.com.br | high | static | N | nan |
| JOÃO HONOR COIROLLO DE SOUZA | RS | https://www.jgcargneluttileiloes.com.br | high | static | N | nan |
| JOÃO GUILHERME CARGNELUTTI | RS | https://www.jgcargneluttileiloes.com.br | high | static | N | nan |
| HENRIQUE ARNOLDO JUNIOR | RS | https://arnoldoleiloes.com.br | high | static | N | nan |
| FERNANDO DE OLIVEIRA KUSS | MG | http://www.ksleiloes.com.br | high | static | N | nan |
| JOÍO GUILHERME CARGNELUTTI | RS | http://www.jgcargneluttileiloes.com.br | high | static | N | nan |
| EDUARDO SCHMITZ | AL | https://www.clicleiloes.com.br/ | high | static | N | nan |
| EDUARDO SCHMITZ | MG | https://www.clicleiloes.com.br | high | static | N | nan |
| Tarcílio Leite | MS | https://www.casadeleiloes.com.br | high | static | N | nan |
| Luci Vera Primaz Dos Reis | SC | https://www.luciverareisleiloes.com.br | high | static | N | nan |
| SANDRA REGINA WONTROBA | RS | http://www.swleiloes.com.br | high | static | N | nan |
| Suelem Regina Bocasanta | SC | https://www.sbleiloes.lel.br | high | static | N | nan |
| PEDRO DO PRADO UTZIG | RS | https://www.utzigleiloes.com.br | high | static | N | nan |
| JOSÉ ALMIRO CHAGAS DE ALENCASTRO | RS | https://alencastroleiloes.com.br | high | static | N | nan |
| JORGE ERLI RITTA | RS | https://www.jritta.lel.br | high | static | N | nan |
| ROGERIO DAMASIO DE OLIVEIRA | SP | https://WWW.DAMASIOLEILOES.COM.BR | high | static | N | nan |
| LUIS FILIPE GEYER FLORES | RS | http://www.leiloeiros.lel.br | high | static | N | nan |
| SÉRGIO RICARDO DE BRITO BORGES | RS | http://www.gestorleiloes.com.br | high | static | N | nan |
| Lincoln de Azevedo Fernandes | MG | https://www.lincolnleiloes.com.br | high | static | Y | nan |
| RANGEL MACHADO | RS | https://www.rangelleiloes.com.br | high | static | N | nan |
| Ricardo Bampi | SC | https://www.bampileiloes.com.br | high | static | N | nan |
| Francisco das Chagas Pereira Júnior | CE | https://www.pereiraleiloesce.com.br | high | static | N | nan |
| João Lopes Cavalcante | CE | https://www.lopesleiloes.net.br | high | static | N | nan |
| Flávia Figueira Messias | MG | https://www.messiasleiloes.com.br | high | static | N | nan |
| Moreno César Oliveira Farias | MG | https://www.brfleiloes.com.br | high | static | N | nan |

_(+237 adicionais omitidos — ver tabela completa abaixo.)_

## Tabela completa

<details>
<summary>Todos os 567 candidatos (clique para expandir)</summary>

| leiloeiro | UF | site | confidence | http | rendering | listing_url | items | review |
|---|---|---|---|---|---|---|---:|:---:|
| JEFÉRSON BENEDETTO | RS | https://www.benedettoleiloes.com.br | medium | 200 | hybrid | https://www.benedettoleiloes.com.br/leiloes | 205 | ✓ |
| Kátia Cerqueira da Silva Casaes | BA | https://www.kcleiloes.com.br/ | high | 200 | static | https://mercado.bomvalor.com.br/kcleiloes/katia-cerqueira-d… | 162 | ✓ |
| BRUNO DUARTE ARAÚJO DOS SANTOS | DF | https://www.oaleiloes.com.br | high | 200 | static | https://www.oaleiloes.com.br/leilao/361 | 156 | ✓ |
| ORLANDO ARAÚJO DOS SANTOS | DF | https://www.oaleiloes.com.br | high | 200 | static | https://www.oaleiloes.com.br/leilao/361 | 156 | ✓ |
| MOACIRA TEGONI GOEDERT | DF | https://www.moacira.lel.br | high | 200 | static | https://www.moacira.lel.br/leilao/730 | 151 | ✓ |
| Milena Rosa Di Giacomo Adri | TO | https://www.megaleiloes.com.br/ms | medium | 200 | static | https://www.megaleiloes.com.br/imoveis | 138 | ✓ |
| FERNANDO JOSE CERELLO GONCALVES PE… | MT | https://www.megaleiloes.com.br | high | 200 | hybrid | https://www.megaleiloes.com.br/imoveis | 138 | ✓ |
| LEVY DOS SANTOS MORAES FILHO | SC | https://www.santosmoraesleiloes.com.br | medium | 200 | static | https://leiloessantosmoraes.com.br/externo/leilao/127/leila… | 130 | ✓ |
| Thaís Costa Bastos Teixeira | MG | https://www.leiloesjudiciaismg.com.br | high | 200 | static | https://www.leiloesjudiciaismg.com.br/imoveis | 105 | ✓ |
| JORGE VITORIO ESPOLADOR | PR | https://www.jeleiloes.com.br | medium | 200 | hybrid | https://www.jeleiloes.com.br/leiloes/2780 | 102 | ✓ |
| Italo Trindade Moura Filho | PI | https://www.italoleiloes.com | high | 200 | hybrid | https://www.italoleiloes.com/leiloes | 101 | ✓ |
| SÉRGIO DE PAULA PEREIRA | ES | https://www.esleiloes.com.br/ | medium | 200 | static | https://www.esleiloes.com.br/eventos/leilao/36/policia-civi… | 98 | ✓ |
| VICENTE DE PAULO ALBUQUERQUE COSTA… | AM | https://www.vipleiloes.com.br | medium | 200 | static | https://www.leilaovip.com.br/ | 84 | ✓ |
| VICENTE DE PAULO A. COTA FILHO | AM | https://www.vipleiloes.com.br | medium | 200 | static | https://www.leilaovip.com.br/ | 84 | ✓ |
| Mariana Gouvêa Lessa&nbsp; | RO | https://www.vipleiloes.com.br | medium | 200 | static | https://www.leilaovip.com.br/ | 84 | ✓ |
| DIOGO MATTOS DIAS MARTINS | AL | https://www.inovaleilao.com.br | medium | 200 | hybrid | https://www.inovaleilao.com.br/subcategorias/2#resultados | 81 | ✓ |
| Lucas Kury Dias Martins | AL | https://www.inovaleilao.com.br | medium | 200 | hybrid | https://www.inovaleilao.com.br/subcategorias/2#resultados | 81 | ✓ |
| Rodrigo Schmitz | BA | https://www.hammer.lel.br | high | 200 | static | https://www.hammer.lel.br/leilao/1829/lotes | 60 | ✓ |
| ANGELICA MIEKO INOUE DANTAS | SP | https://WWW.LANCETOTAL.COM.BR | medium | 200 | static | https://lancetotal.com.br/leilao.php?idLeilao=1103 | 60 | ✓ |
| Angela Eiko Inoque dos Santos | PI | https://www.lancetotal.com.br/ | medium | 200 | static | https://lancetotal.com.br/leilao.php?idLeilao=1103 | 60 | ✓ |
| Cassiano Ricardo Dall Ago e Silva | PI | https://www.cassianoleiloes.com.br | high | 200 | static | https://www.cassianoleiloes.com.br/lotes/imovel | 60 | ✓ |
| DARCI MULLER | RS | http://www.mullerleiloes.com.br | high | 200 | static | https://www.mullerleiloes.com.br/lotes/imovel | 54 | ✓ |
| DANIEL COSTA MÜLLER | RS | http://www.mullerleiloes.com.br | high | 200 | static | https://www.mullerleiloes.com.br/lotes/imovel | 54 | ✓ |
| ALEXANDRE RECH | RS | https://www.rechleiloes.com.br | high | 200 | static | https://www.rechleiloes.com.br/lotes/imovel | 53 | ✓ |
| Viviane Garzon Corrêa | MG | https://www.bolsadeleiloes.com.br | medium | 200 | static | https://www.bolsadeleiloes.com.br/leilao/496 | 50 | ✓ |
| RENI JOSÉ BONFANDINI | RS | https://www.leiloesbonfadini.com.br | medium | 200 | static | https://leiloesbonfadini.com.br/arroio-do-meio/ | 48 | ✓ |
| VICENTE ALVES PEREIRA NETO | SC | https://www.agencialeilao.com.br | high | 200 | hybrid | https://www.agencialeilao.com.br/leiloes | 48 | ✓ |
| Giovanni Silva Wersdoefer | SC | https://www.hastapublica.lel.br | high | 200 | static | https://www.hastapublica.lel.br/leilao/lotes/imoveis | 47 | ✓ |
| LUCAS FERREIRA | RS | http://www.leiloeirodian.com | high | 200 | unknown | https://www.leiloeirodian.com.br/ | 47 | ✓ |
| Ricardo Ferreira Gomes | SC | https://www.ricardogomesleiloes.com.br | medium | 200 | static | https://www.ricardogomesleiloes.com.br/leiloes/34 | 47 | ✓ |
| ROGÉRIO BRONZATTO | RS | https://www.bronzattoleiloes.com.br | high | 200 | static | https://www.bronzattoleiloes.com.br/lotes/imovel | 46 | ✓ |
| LISIANE ZEIFERT | RS | http://www.bronzattoleiloes.com.br | high | 200 | static | https://www.bronzattoleiloes.com.br/lotes/imovel | 46 | ✓ |
| Lucas Andreatta de Oliveir | MT | https://leiloariasmart.com.br | high | 200 | static | https://leiloariasmart.com.br/leiloes/ocupados | 44 | ✓ |
| Fábio Marlon Machado | SC | https://www.machadoleiloeiro.com.br | high | 200 | static | https://www.machadoleiloeiro.com.br/lotes/imovel | 44 | ✓ |
| EDUARDO JESUS BORDIGNON | PR | http://www.leilopar.com.br | high | 200 | static | https://www.leilopar.com.br/lotes/imovel | 43 | ✓ |
| JOÃO ANTÔNIO CARGNELUTTI | RS | https://www.cargneluttileiloes.com.br | high | 200 | hybrid | https://www.cargneluttileiloes.com.br/lotes/imovel | 43 | ✓ |
| ERNI CARLOS ORO | RS | https://www.oroleiloes.lel.br | high | 200 | hybrid | https://www.oroleiloes.lel.br/lotes/imovel | 43 | ✓ |
| JOÍO ANTÔNIO CARGNELUTTI | RS | http://www.cargneluttileiloes.com.br | high | 200 | hybrid | https://www.cargneluttileiloes.com.br/lotes/imovel | 43 | ✓ |
| CAMILA LAIS CARGNELUTTI | RS | https://www.cargneluttileiloes.com.br | high | 200 | hybrid | https://www.cargneluttileiloes.com.br/lotes/imovel | 43 | ✓ |
| Sérgio Sousa Rodrigues | MG | https://www.bhleiloaria.com.br | high | 200 | static | https://bhleiloaria.com.br/busca/segmento/imoveis | 42 | ✓ |
| Francisco David Batista de Souza | MG | https://www.franciscodavidleiloeiro.com… | high | 200 | static | https://franciscodavidleiloeiro.com.br/busca/segmento/imove… | 42 | ✓ |
| EDER JORDAN DE SOUZA | DF | https://oreidosleiloes.com.br | high | 200 | static | https://oreidosleiloes.com.br/busca/segmento/imoveis | 42 | ✓ |
| SIDNEY BELARMINO FERREIRA JUNIOR | PR | https://www.sfleiloes.com.br/ | medium | 200 | static | https://www.sfleiloes.com.br/categoria/1 | 42 | ✓ |
| Dênis de Oliveira Fernandes | MG | https://www.leiloeirodenis.com.br | high | 200 | static | https://leiloeirodenis.com.br/busca/segmento/imoveis | 42 | ✓ |
| SEBASTIÍO FELIX DA COSTA NETO | DF | https://www.costanetoleiloeiro.com.br | high | 200 | static | https://costanetoleiloeiro.com.br/busca/segmento/imoveis | 42 | ✓ |
| PAULO HENRIQUE DE ALMEIDA TOLENTINO | DF | https://www.paulotolentino.com.br | high | 200 | static | https://paulotolentino.com.br/busca/segmento/imoveis | 42 | ✓ |
| FERNANDO GONÇALVES COSTA | DF | https://www.multleiloes.com | high | 200 | static | https://multleiloes.com/busca/segmento/imoveis | 42 | ✓ |
| Álvaro Antonio Mussa Pereira | MT | https://www.alvaroantonioleiloes.com.br/ | medium | 200 | static | https://www.alvaroantonioleiloes.com.br/eventos/leilao/129/… | 42 | ✓ |
| SEBASTIÃO FELIX DA COSTA NETO | DF | https://www.costanetoleiloeiro.com.br | high | 200 | static | https://costanetoleiloeiro.com.br/busca/segmento/imoveis | 42 | ✓ |
| Jorge Vinicius De Moura Correa | SC | https://www.renovarleiloes.com.br | high | 200 | static | https://www.renovarleiloes.com.br/leilao/lotes/imoveis | 40 | ✓ |
| José Luiz Pereira Vizeu | DF | https://www.flexleiloes.com.br | medium | 200 | dynamic | https://www.flexleiloes.com.br/imoveis/ | 40 | ✓ |
| WESLEY SILVA RAMOS | AP | http://www.wrleiloes.com.br | high | 200 | static | https://www.wrleiloes.com.br/leilao/741/leilao-departamento… | 40 | ✓ |
| GILMAR SANTOS DOS SANTOS | RS | https://www.santoseborinleiloes.com.br | high | 200 | static | https://www.santoseborinleiloes.com.br/leilao/lotes/imoveis | 40 | ✓ |
| GERSON ANOR BORIN DA SILVA NETO | RS | https://www.santoseborinleiloes.com.br | high | 200 | static | https://www.santoseborinleiloes.com.br/leilao/lotes/imoveis | 40 | ✓ |
| FRANCISCO HILLESHEIM | RS | https://www.alemaoleiloeiro.com.br | high | 200 | static | https://www.alemaoleiloeiro.com.br/lotes/imovel | 40 | ✓ |
| JUCENARA DE MELLO VIEIRA BORDIGNON | RS | http://www.juleiloes.com.br | high | 200 | static | https://www.juleiloes.com.br/leilao/lotes/imoveis | 40 | ✓ |
| Rafael Ceretta Alegranzzi | SC | http://www.renovarleiloes.com.br | high | 200 | static | https://www.renovarleiloes.com.br/leilao/lotes/imoveis | 40 | ✓ |
| MOYSES PEDROSO DE MORAES | RS | https://www.moraesleiloes.com.br | high | 200 | static | https://www.moraesleiloes.com.br/lotes/imovel | 36 | ✓ |
| ANDERSON LOPES DE PAULA | DF | https://www.e-leiloeiro.leilao.br/ | high | 200 | hybrid | https://www.e-leiloes.com.br/leilao/imoveis | 36 | ✓ |
| MARILAINE BORGES DE PAULA | PR | https://www.confiancaleiloes.leilao.br/ | high | 200 | hybrid | https://www.e-leiloes.com.br/leilao/imoveis | 36 | ✓ |
| ANDERSON LOPES DE PAULA | GO | https://www.e-leiloeiro.leilao.br/ | high | 200 | hybrid | https://www.e-leiloes.com.br/leilao/imoveis | 36 | ✓ |
| TIAGO BRUNELLI DE MORAES | RS | https://www.moraesleiloes.com.br | high | 200 | static | https://www.moraesleiloes.com.br/lotes/imovel | 36 | ✓ |
| DENYS PYERRE DE OLIVEIRA | DF | https://www.leje.com.br | high | 200 | static | https://www.leje.com.br/index.php?acao=evento&cod=7630 | 35 | ✓ |
| Horany Wermelinger Costa do Nascim… | MG | https://www.wermelingerleiloes.com.br | medium | 200 | static | https://www.wermelingerleiloes.com.br/ | 35 | ✓ |
| Horany Costa do Nascimento | MG | https://www.wermelingerleiloes.com.br | medium | 200 | static | https://www.wermelingerleiloes.com.br/ | 35 | ✓ |
| Vera Maria Aguiar de Sousa | RO | https://www.leiloesaguiar.com.br | high | 200 | hybrid | https://www.leiloesaguiar.com.br/lotes/imovel | 35 | ✓ |
| Vera Lúcia Aguiar de Sousa | RO | https://www.leiloesaguiar.com.br/ | high | 200 | hybrid | https://www.leiloesaguiar.com.br/lotes/imovel | 35 | ✓ |
| GUSTAVO CORREA PEREIRA DA SILVA | SP | https://www.leiloesonlinems.com.br | high | 200 | static | https://www.leiloesonlinems.com.br/leilao/comissao-de-alien… | 34 | ✓ |
| OZIAS TAVARES PEREIRA | DF | https://www.parquedosleiloes.com.br | medium | 200 | hybrid | https://www.parquedosleiloes.com.br/leiloes-judiciais | 34 | ✓ |
| OZIAS PEREIRA TAVARES | DF | https://www.parquedosleiloes.com.br | medium | 200 | hybrid | https://www.parquedosleiloes.com.br/leiloes-judiciais | 34 | ✓ |
| GIAN ROBERTO CAGNI BRAGGIO | DF | https://www.parquedosleiloes.com.br | medium | 200 | hybrid | https://www.parquedosleiloes.com.br/leiloes-judiciais | 34 | ✓ |
| Paulo César Agostinho | MG | https://www.agostinholeiloes.com.br | high | 200 | static | https://www.agostinholeiloes.com.br/lotes/imovel | 34 | ✓ |
| FLÁVIO BITTENCOURT GARCIA | RS | http://www.flaviogarcia.lel.br | medium | 200 | static | https://www.flaviogarcia.lel.br/leilao/leilao-unificado/197 | 33 | ✓ |
| Luciano Resende Rodrigues | SC | https://www.lancecertoleiloes.com.br | high | 200 | dynamic | https://www.lancecertoleiloes.com.br/leilao/050526PART | 33 | ✓ |
| AYRTON DE SOUZA PORTO FILHO | ES | https://www.emleilao.com.br | medium | 200 | static | https://www.emleilao.com.br/eventos/leilao/86/leilao-de-33-… | 33 | ✓ |
| Priscilla Lopes Ribeiro Ferreira | MG | https://www.ferreiraleiloes.com.br | high | 200 | static | https://www.ferreiraleiloes.com.br/lotes/imovel | 32 | ✓ |
| SÉRGIO AUGUSTO DOS SANTOS | RS | https://www.saleiloes.lel.br | high | 200 | static | https://www.nsleiloes.leilao.br/leilao/lotes/imoveis | 31 | ✓ |
| Neila Rosane Ribeiro Dos Santos | SC | https://www.nsleiloes.lel.br | high | 200 | static | https://www.nsleiloes.leilao.br/leilao/lotes/imoveis | 31 | ✓ |
| Ivana Montenegro Castelo Branco Ro… | BA | https://www.patiorochaleiloes.com.br/ | high | 200 | static | https://www.patiorochaleiloes.com.br/lotes/imovel | 31 | ✓ |
| BRUNO HENRIQUE DOS SANTOS | RS | http://www.nsleiloes.leilao.br | high | 200 | static | https://www.nsleiloes.leilao.br/leilao/lotes/imoveis | 31 | ✓ |
| Gelson Bourschiet | PR | http://www.gelsonleiloes.com.br | medium | 200 | static | https://shopleiloes.leilao.br/leilao/31/grande-leilao-prefe… | 30 | ✓ |
| Isaías Rosa Ramos Júnior | MG | https://www.isaiasleiloes.com.br | high | 200 | hybrid | https://www.isaiasleiloes.com.br/lotes/imovel | 30 | ✓ |
| Flávio Duarte Ceruli | MG | https://www.leiloesceruli.com.br | high | 200 | hybrid | https://www.leiloesceruli.com.br/lotes/imovel | 30 | ✓ |
| Carla Karine Santos Agostinho | MG | https://www.purcenaleiloes.com.br | high | 200 | hybrid | https://www.purcenaleiloes.com.br/lotes/imovel | 30 | ✓ |
| Jose Ivan de Souza Rabelo | SE | https://www.realizaleiloes.com.br | high | 200 | static | https://www.realizaleiloes.com.br/leilao/292/lotes | 30 | ✓ |
| Gutemberg da Silva Araújo | BA | https://www.gutembergaraujoleiloes.com.… | high | 200 | static | https://www.gutembergaraujoleiloes.com.br/leilao/226/lotes | 30 | ✓ |
| Cristiane de Almeida Rabelo Góis | SE | https://www.realizaleiloes.com.br | high | 200 | static | https://www.realizaleiloes.com.br/leilao/292/lotes | 30 | ✓ |
| Péricles Luciano Santos de Jesus | BA | https://www.centraldosleiloes.com.br/ | high | 200 | static | https://www.centraldosleiloes.com.br/lotes/imovel | 30 | ✓ |
| JAIR VICENTE MARTINS | PR | https://www.vmleiloes.com.br/ | high | 200 | static | https://vmleiloes.com.br/leilao/562/leilao-judicial-em-curi… | 30 | ✓ |
| RUBEM RODRIGUES GARCIA | RS | http://www.rubemgarcia.com.br | high | 200 | static | https://www.amtleiloes.com.br/leilao-detran/leilao-detran-c… | 30 | ✓ |
| CAROLINA TREIN SILVEIRA | RS | https://www.leffaleiloes.com.br | high | 200 | static | https://www.leffaleiloes.com.br/leilao/leilao-da-prefeitura… | 30 | ✓ |
| Daniel Elias Garcia | BA | https://www.danielgarcialeiloes.com.br/ | high | 200 | hybrid | https://www.danielgarcialeiloes.com.br/leiloes | 30 | ✓ |
| LUCIANO GONÇALVES BORBA ASSUNÇÍO | DF | https://www.leiloeirosdebrasilia.com.br | high | 200 | static | https://www.leiloeirosdebrasilia.com.br/lotes/imovel | 30 | ✓ |
| ÁLVARO MARQUES TEIXEIRA | RS | https://www.amtleiloes.com.br | high | 200 | static | https://www.amtleiloes.com.br/leilao-detran/leilao-detran-c… | 30 | ✓ |
| ANA LÚCIA BORBA ASSUNÇÍO | DF | https://www.leiloeirosdebrasilia.com.br | high | 200 | static | https://www.leiloeirosdebrasilia.com.br/lotes/imovel | 30 | ✓ |
| LUCIANO GONÇALVES BORBA ASSUNÇÃO | DF | https://www.leiloeirosdebrasilia.com.br | high | 200 | static | https://www.leiloeirosdebrasilia.com.br/lotes/imovel | 30 | ✓ |
| Teófilo Santos de Jesus | BA | https://www.centraldosleiloes.com.br | high | 200 | static | https://www.centraldosleiloes.com.br/lotes/imovel | 30 | ✓ |
| ANDRE GUSTAVO BOUÇAS IGNÁCIO | DF | https://www.brasilialeiloes.com.br | high | 200 | static | https://www.brasilialeiloes.com.br/externo/por-categoria/4 | 30 | ✓ |
| MARCO GEOVANNE TOBIAS DA SILVA | DF | https://www.bsbleiloes.com.br | high | 200 | static | https://www.bsbleiloes.com.br/leilao/3o-leilao-de-abril-202… | 30 | ✓ |
| ANA LÚCIA BORBA ASSUNÇÃO | DF | https://www.leiloeirosdebrasilia.com.br | high | 200 | static | https://www.leiloeirosdebrasilia.com.br/lotes/imovel | 30 | ✓ |
| Giovano Ávila Alves | DF | https://www.soleiloes.com.br/ | high | 200 | static | https://www.soleiloes.com.br/leilao/1o-grande-leilao-nacion… | 30 | ✓ |
| Ives Harrison Nasar dos Santos | CE | https://www.nasarleiloes.com.br | medium | 200 | hybrid | https://www.nasarleiloes.com.br/externo/leilao/76 | 29 | ✓ |
| NAIO DE FREITAS RAUPP | RS | https://www.rauppleiloes.com.br | high | 200 | static | https://www.rauppleiloes.com.br/leilao/lotes/imoveis | 29 | ✓ |
| ALEX SANDRO VIEIRA FELIX | PR | https://alleiloes.com.br/ | medium | 200 | static | https://alleiloes.com.br/leilao/376/leilao-de-veiculos-da-p… | 29 | ✓ |
| ADRIANO MELNISKI | PR | https://www.amleiloeiro.com.br | high | 200 | static | https://amleiloeiro.com.br/leilao/298/leilao-vara-civel-e-d… | 29 | ✓ |
| Valério César de Azevedo Déda | SE | https://www.lancese.com.br | high | 200 | static | https://www.lancese.com.br/lotes/imovel | 28 | ✓ |
| Carlos Gustavo Santos Fiel | SE | https://www.lancese.com.br | high | 200 | static | https://www.lancese.com.br/lotes/imovel | 28 | ✓ |
| Adriana Pires Amancio | MG | https://www.apaleiloes.com.br/ | high | 200 | hybrid | https://mercado.bomvalor.com.br/apabrfleiloes/busca/segment… | 28 | ✓ |
| BEATRIZ SILVA CARVALHO | PR | https://www.grupocarvalholeiloes.com.br | medium | 200 | dynamic | https://www.grupocarvalholeiloes.com.br/leilao/leilao-publi… | 28 | ✓ |
| LUIZ CARLOS DALE NOGARI DOS SANTOS | RS | https://www.leilaosantos.com.br | high | 200 | static | https://www.leilaosantos.com.br/leilao/1499/lotes | 27 | ✓ |
| GILMAR THUME | RS | https://www.gtleiloes.com.br | high | 200 | static | https://www.gtleiloes.com.br/leilao/leilao-da-justica-estad… | 27 | ✓ |
| JEFFERSON ADRIANO DA COSTA | PR | https://www.jacleiloes.com.br | high | 200 | static | https://www.jacleiloes.com.br/leilao/lotes/imoveis | 27 | ✓ |
| RENNAN DE SOUZA MENEGON | DF | https://www.melhorleiloes.com.br | medium | 200 | static | https://www.melhorleiloes.com.br/leiloes/17 | 27 | ✓ |
| SAMI RAICHER | MT | https://www.raicherleiloes.com.br | high | 200 | hybrid | https://www.raicherleiloes.com.br/leiloes | 27 | ✓ |
| Josecelli Kildare Fraga Gomes | BA | https://www.kildareleiloes.com.br/ | high | 200 | static | https://www.kildareleiloes.com.br/leilao/2702/lotes | 27 | ✓ |
| Marcos Garcia Almeida | MG | https://www.3torresleiloes.com.br | high | 200 | hybrid | https://www.3torresleiloes.com.br/lotes/imovel | 26 | ✓ |
| Glener Brasil Cassiano | MG | https://www.leiloesbrasilcassiano.com.br | high | 200 | static | https://leiloesbrasilcassiano.com.br/leiloes/leilao/leilao-… | 26 | ✓ |
| Magnun Luiz Serpa | SC | https://www.serpaleiloes.com.br | medium | 200 | static | https://www.serpaleiloes.com.br/eventos/leilao/213/imoveis-… | 26 | ✓ |
| MARCOS ROBERTO TORRES | MG | https://www.3torresleiloes.com.br | high | 200 | hybrid | https://www.3torresleiloes.com.br/lotes/imovel | 26 | ✓ |
| MARCELO SOUZA SCHONARDIE | RS | https://www.marceloleiloeiro.com.br | high | 200 | static | https://www.marceloleiloeiro.com.br/leilao/lotes/imoveis | 25 | ✓ |
| Arthur Ferreira Nunes | BA | https://www.nordesteleiloes.com.br | medium | 200 | static | https://leiloes.arthurnunes.leilao.br/leiloes/110-conselho-… | 25 | ✓ |
| ALESSANDRO FAHRION PINTO | RS | https://www.regionalleiloes.com.br/ | high | 200 | static | https://www.regionalleiloes.com.br/leilao/lotes/imoveis | 25 | ✓ |
| RODRIGO ZAGO SZORTYKA | RS | https://www.szortykaleiloes.com.br | high | 200 | static | https://www.szortykaleiloes.com.br/leilao/lotes/imoveis | 24 | ✓ |
| ANTÔNIO PEDRO PACHECO LOPES | RS | https://www.superleiloes.net | high | 200 | static | https://www.superleiloes.net/leilao/lotes/imoveis | 23 | ✓ |
| SANDRA DE FATIMA SANTOS | PR | https://www.sandrasantosleiloes.com.br | medium | 200 | static | https://www.sandrasantosleiloes.com.br/eventos/leilao/403/p… | 22 | ✓ |
| CONRADO AUGUSTO CARVALHO DE MAGALH… | PR | http://www.magalhaesleiloes.com.br | medium | 200 | static | http://www.magalhaesleiloes.com.br/eventos/leilao/12/imovei… | 22 | ✓ |
| LUIZ FERNANDO MORAES DA CRUZ | RS | http://www.santamarialeiloes.com.br | high | 200 | static | https://www.santamarialeiloes.com.br/leilao/lotes/imoveis | 22 | ✓ |
| JOSE LAZARO RIBEIRO MENEZES JUNIOR | RS | http://www.santamarialeiloes.com.br | high | 200 | static | https://www.santamarialeiloes.com.br/leilao/lotes/imoveis | 22 | ✓ |
| Flares Aguiar da Silva | MT | https://faleiloes.com.br/ | high | 200 | static | https://faleiloes.com.br/lotes/imovel | 21 | ✓ |
| MAURO PEREIRA DE OLIVEIRA | RS | https://www.mpleilao.com | high | 200 | static | https://www.mpleilao.com.br/leilao/excelente-leilao-da-pref… | 21 | ✓ |
| Wendel Machado Garcia | SC | https://www.wendelgarcia.com.br | high | 200 | static | https://www.wendelgarcia.com.br/leilao/leilao-judicial-trab… | 21 | ✓ |
| MARCELLO PEREIRA DE OLIVEIRA | RS | https://www.mpleilao.com | high | 200 | static | https://www.mpleilao.com.br/leilao/excelente-leilao-da-pref… | 21 | ✓ |
| JACQUES JOCHIMS FERNANDES | RS | https://www.grandesleiloes.com.br | high | 200 | static | https://www.grandesleiloes.com.br/leilao/lotes/imoveis | 21 | ✓ |
| GIBRALTAR PEDRO CIPRIANO VIDAL | RS | https://www.vidalleiloes.com.br | high | 200 | static | https://www.vidalleiloes.com.br/leilao/lotes/imoveis | 21 | ✓ |
| CARLOS CAMPANHÃ | SP | https://www.projudleiloes.com.br | high | 200 | dynamic | https://www.projudleiloes.com.br/leilao/lapa-moveis-escrito… | 21 | ✓ |
| ROBERTA POSSANI ZAGO | RS | http://www.rzleiloes.com.br | high | 200 | static | https://www.rz.leilao.br/leilao/leilao-de-maquinas-veiculos… | 21 | ✓ |
| MARCELLO SILVA DE OLIVEIRA | RS | http://www.mpleilao.com.br | high | 200 | static | https://www.mpleilao.com.br/leilao/excelente-leilao-da-pref… | 21 | ✓ |
| Preposto: Yasmin Mikejevs Lorga | MT | https://faleiloes.com.br/ | high | 200 | static | https://faleiloes.com.br/lotes/imovel | 21 | ✓ |
| SÉRGIO ROBERTO PIMENTEL SCHOLANTE | RS | https://www.scholante.com.br | high | 200 | static | https://www.scholanteleiloes.com.br/leilao/leilao-da-justic… | 20 | ✓ |
| Dora Plat | MG | https://www.zukerman.com.br | high | 200 | hybrid | https://www.portalzuk.com.br/imovel/sp/ferraz-de-vasconcelo… | 20 | ✓ |
| Marco Túlio Montenegro Cavalcanti … | BA | https://www.marcotulioleiloes.com.br | medium | 200 | hybrid | https://www.marcotulioleiloes.com.br/leiloes/287 | 20 | ✓ |
| Érica Cristina Alves | MG | https://www.alvesleiloes.com.br | high | 200 | static | https://www.alvesleiloes.com.br/leiloes/encerrados | 20 | ✓ |
| Rogério Menezes Nunes | PI | https://www.rogeriomenezes.com.br | high | 200 | static | https://www.rogeriomenezes.com.br/leilao/1533 | 20 | ✓ |
| FABIO SAMIR MACHADO | RS | https://www.machadoleiloesrs.com.br | high | 200 | static | https://www.machadoleiloesrs.com.br/leilao/lotes/imoveis | 20 | ✓ |
| ROGÉRIO MENEZES NUNES | RJ | https://www.rogeriomenezes.com.br/ | high | 200 | static | https://www.rogeriomenezes.com.br/leilao/1533 | 20 | ✓ |
| DORA PLAT | MT | https://www.portalzuk.com.br/ | high | 200 | hybrid | https://www.portalzuk.com.br/imovel/sp/ferraz-de-vasconcelo… | 20 | ✓ |
| MAURÍCIO GEHM | RS | https://www.mgleiloes-rs.com.br | high | 200 | static | https://www.mgleiloes-rs.com.br/lotes/imovel | 20 | ✓ |
| Luzinete Mussa de Moraes Pereira | MT | https://www.lumussaleiloes.com.br/ | medium | 200 | static | https://www.lumussaleiloes.com.br/eventos/leilao/142/prefei… | 20 | ✓ |
| Kleiber Leite Pereira | PI | https://www.kleiberleiloes.com.br | medium | 200 | static | https://www.kleiberleiloes.com.br/?tipo=leilao | 20 | ✓ |
| LEILA NANCI KARASIAKI | GO | https://www.lkleiloes.com.br | high | 200 | static | https://www.lkleiloes.com.br/lotes/categoria/veiculos | 19 | ✓ |
| LUCIENE MARQUES DE SOUSA BARRETO | DF | https://www.marquesbarretoleiloes.com.br | high | 200 | static | https://www.marquesbarretoleiloes.com.br/externo/leiloes-pa… | 19 | ✓ |
| ARTUR NOGARI DOS SANTOS | PR | http://www.nogarileiloes.com.br | high | 200 | static | https://www.nogarileiloes.com.br/lotes/imovel | 19 | ✓ |
| JORGE FERLIN DALE NOGARI DOS SANTOS | SC | https://www.nogarileiloes.com.br | high | 200 | static | https://www.nogarileiloes.com.br/lotes/imovel | 19 | ✓ |
| PAULO DE OLIVEIRA AZEVEDO | GO | https://www.lkleiloes.com.br | high | 200 | static | https://www.lkleiloes.com.br/lotes/categoria/veiculos | 19 | ✓ |
| DANIELLE JOY KARASIAKI CARVALHO | GO | https://www.lkleiloes.com.br | high | 200 | static | https://www.lkleiloes.com.br/lotes/categoria/veiculos | 19 | ✓ |
| GUSTAVO TURANI | RS | http://www.turanileiloes.com.br | high | 200 | static | https://www.turanileiloes.com.br/imoveis | 19 | ✓ |
| Marco Aurélio Périco Góes | SC | https://www.marcoleiloes.com.br | medium | 200 | static | https://www.marcoleiloes.com.br/leiloes/70 | 18 | ✓ |
| ARGEMIRO LUIZ FINATTO | RS | https://www.finattoleiloes.com.br | medium | 200 | hybrid | https://www.finattoleiloes.com.br/evento/41 | 18 | ✓ |
| João Luiz de França Neto | BA | https://www.ccjleiloes.com.br/ | high | 200 | hybrid | https://www.ccjleiloes.com.br/leilao/520/lotes | 17 | ✓ |
| Antônio Romero Ferreira da Silva | BA | https://www.ccjleiloes.com.br/ | high | 200 | hybrid | https://www.ccjleiloes.com.br/leilao/520/lotes | 17 | ✓ |
| FABIO GOMES PIETOSO | RS | https://www.pietosoleiloes.com.br | high | 200 | static | https://www.pietosoleiloes.com.br/leilao/lotes/imoveis | 17 | ✓ |
| CARMEN GOMES PIETOSO | RS | https://www.pietosoleiloes.lel.br | high | 200 | static | https://www.pietosoleiloes.com.br/leilao/lotes/imoveis | 17 | ✓ |
| Jamile Santana Cerqueira | BA | https://www.ccjleiloes.com.br | high | 200 | hybrid | https://www.ccjleiloes.com.br/leilao/520/lotes | 17 | ✓ |
| MAURÍCIO RODRIGO BACK | RS | https://www.backleiloes.com.br | high | 200 | hybrid | https://www.backleiloes.com.br/lotes/imovel?categoria_id= | 16 | ✓ |
| Marcos Antonio Tulio | SC | https://www.tulioleiloes.com.br | medium | 200 | static | https://tulioleiloes.com.br/leilao/112/leilao-senad-policia… | 16 | ✓ |
| Matheus Werneck de Oliveira Santos | MG | https://www.leiloarialoucoporleiloes.co… | high | 200 | static | https://www.leiloarialoucoporleiloes.com.br/leilao/75/lotes | 15 | ✓ |
| Lilian Dutra Portugal | MG | https://www.lilianportugal.com.br | medium | 200 | static | https://www.lilianportugal.com.br/eventos/leilao/222/leilao… | 15 | ✓ |
| Humberto Amaro Batista Filho | MG | https://www.lilianportugal.com.br | medium | 200 | static | https://www.lilianportugal.com.br/eventos/leilao/222/leilao… | 15 | ✓ |
| LEOMAR KIRINUS | RS | http://www.leomarkirinusleiloes.com.br | high | 200 | static | https://www.leomarkirinusleiloes.com.br/leilao/lotes/imoveis | 15 | ✓ |
| VIRIATO DOMINGUES CRAVO | BA | https://www.cravoleiloes.com.br/ | high | 200 | static | https://www.cravoleiloes.com.br/lotes/imovel | 15 | ✓ |
| ADRIANO CARLOS OLIVEIRA SILVA | DF | https://www.adringleiloes.com.br | medium | 200 | static | https://www.adringleiloes.com.br/externo/lote/380/leilao-si… | 15 | ✓ |
| WILLIAM MENDES KIRINUS | RS | http://www.leomarkirinusleiloes.com.br | high | 200 | static | https://www.leomarkirinusleiloes.com.br/leilao/lotes/imoveis | 15 | ✓ |
| ALESSANDRA CAVALCANTI ANTUNES | SP | https://www.kwara.com.br/ | medium | 200 | static | https://www.kwara.com.br/evento/leilao-de-eletros-moveis-e-… | 14 | ✓ |
| Sued Peter Bastos Dyna | SC | https://www.suedpeterleiloes.com.br | medium | 200 | static | https://www.suedpeterleiloes.com.br/buscador?categoria=2 | 14 | ✓ |
| ANDRESSA SEDREZ TERRES TONIAL FERR… | RS | http://www.tonialleiloes.com.br | high | 200 | static | https://www.tonialleiloes.com.br/leilao/lotes/imoveis | 14 | ✓ |
| Victor Oliveira Dorta | MT | https://www.victordortaleiloes.com.br | high | 200 | hybrid | https://www.victordortaleiloes.com.br/lotes/imovel | 14 | ✓ |
| Daiane Fucks Pelentir | SC | http://www.agilileiloes.com.br | high | 200 | static | https://www.agilileiloes.com.br/leilao/lotes/imoveis | 13 | ✓ |
| ALEX FONSECA LOTTERMANN | RS | http://www.lottermannleiloes.com.br | high | 200 | static | https://www.lottermannleiloes.com.br/leilao/leilao-judicial… | 13 | ✓ |
| SÉRGIO LIPINSKI BRANDÃO JUNIOR | RS | https://www.lipinskileiloes.com.br | high | 200 | static | https://www.lipinskileiloes.com.br/leilao/scania-l-111-2p-f… | 12 | ✓ |
| Leonardo Coelho Avelar | TO | https://www.arrematabem.com.br | high | 200 | static | https://arrematabem.com.br/lote/1164/imovel-em-goianiago | 12 | ✓ |
| Fábio Maciel Amarante | MG | https://www.nortedeminasleiloes.com.br | medium | 200 | dynamic | https://nortedeminasleiloes.com.br/leilao | 12 | ✓ |
| SÉRGIO LIPINSKI BRANDÍO JUNIOR | RS | http://www.lipinskileiloes.com.br | high | 200 | static | https://www.lipinskileiloes.com.br/leilao/scania-l-111-2p-f… | 12 | ✓ |
| Bruno Pimentel Rosa | MT | https://lancevip.com.br/ | medium | 200 | static | https://lancevip.com.br/buscador?categoria=2 | 12 | ✓ |
| UNO PIMENTEL ROSA | RO | https://lancevip.com.br/ | medium | 200 | static | https://lancevip.com.br/buscador?categoria=2 | 12 | ✓ |
| THAIS SILVA MOREIRA DE SOUSA | AM | https://www.tmleiloes.com.br | high | 200 | static | https://www.tmleiloes.com.br/lotes/imovel | 12 | ✓ |
| VOLNEI ZACCARIAS | RS | https://www.zaccariasleiloes.com.br | high | 200 | static | https://www.zaccariasleiloes.com.br/leilao/leilao-da-comarc… | 12 | ✓ |
| Jean Fernando Ribeiro Pavesi | SC | https://www.brasilsulleiloes.com.br | high | 200 | static | https://www.brasilsulleiloes.com.br/lotes/imovel | 11 | ✓ |
| JOSÉ LUIS PARDO SANTAYANA CARDOSO | RS | https://www.santayanaleiloes.com.br | high | 200 | static | https://www.santayanaleiloes.com.br/leilao/lotes/imoveis | 11 | ✓ |
| JOHN LEVY ZAGO AMARAL | RS | http://www.zagoleiloes.com.br | high | 200 | hybrid | https://www.zagoleiloes.com.br/lotes/imovel?categoria_id= | 11 | ✓ |
| EDUARDO ABREU ALVES BARBOSA | SC | https://www.bestleiloes.com.br | high | 200 | static | https://www.bestleiloes.com.br/lotes/imovel | 11 | ✓ |
| JOSÉ LÁZARO RIBEIRO MENEZES | RS | http://www.mercadoleiloes.com.br | high | 200 | static | https://mercadoleiloes.com.br/leilao/ | 11 | ✓ |
| CLAUDIO CESAR KUSS | PR | https://www.claudiokussleiloes.com.br/ | high | 200 | static | https://www.claudiokussleiloes.com.br/relacao-foto/869 | 11 | ✓ |
| TATIANA PAULA ZANI DE SOUZA | DF | https://www.liderleiloes.com.br | medium | 200 | dynamic | https://www.liderleiloes.com.br/leiloes/163 | 11 | ✓ |
| CAROLINE DE SOUSA RIBAS | DF | https://www.liderleiloes.com.br | medium | 200 | dynamic | https://www.liderleiloes.com.br/leiloes/163 | 11 | ✓ |
| TATIANA PAULA ZANI DE SOUSA | DF | https://www.liderleiloes.com.br | medium | 200 | dynamic | https://www.liderleiloes.com.br/leiloes/163 | 11 | ✓ |
| JEAN MIGUEL CORRÊA | RS | http://www.casaforteleiloes.com.br | high | 200 | static | https://www.casaforteleiloes.com.br/oferta/leilao/imoveis/v… | 11 | ✓ |
| CLECI AMABILE LEVY ZAGO | RS | http://www.zagoleiloes.com.br | high | 200 | hybrid | https://www.zagoleiloes.com.br/lotes/imovel?categoria_id= | 11 | ✓ |
| VALDINEI GENEROSO SILVEIRA | RS | http://www.vsleiloes.com | high | 200 | static | https://www.vsleiloes.com/leilao/lotes/imoveis | 11 | ✓ |
| Aridina Maria Do Amaral | SC | https://www.formulaleiloes.com.br | high | 200 | static | https://www.formulaleiloes.com.br/?pg=item&id=272&item=faor… | 10 | ✓ |
| Júlio Ramos Luz | SC | https://www.portaldoleiloeiro.com.br | high | 200 | static | https://www.portaldoleiloeiro.com.br/?pg=item&id=272&item=f… | 10 | ✓ |
| FERNANDA TERRES DE PAULA | RS | https://www.fernandaleiloes.lel.br | high | 200 | static | https://www.fernandaleiloes.lel.br/leilao/lotes/imoveis | 10 | ✓ |
| Gilson Aparecido Mariano | MG | https://www.marianoleiloes.com.br | medium | 200 | static | https://www.marianoleiloes.com.br/leiloes/275 | 9 | ✓ |
| Rosa Lúcia Lopes Carstens | SC | https://www.leiloeiro.online | high | 200 | static | https://www.leiloeiro.online/lotes/imovel | 9 | ✓ |
| Carlos Vinicius de Carvalho Mascar… | SE | https://www.rjleiloes.com.br | high | 200 | static | https://www.rjleiloes.com.br/lotes/imovel | 9 | ✓ |
| Paulo Castelan Minatto | SC | https://www.casadoleilao.com | high | 200 | static | https://www.casadoleilao.com/externo/lote/2052/leilao-4a-va… | 9 | ✓ |
| Alexsander Pretti Domingos | MG | https://www.universodosleiloes.com.br | high | 200 | static | https://mercado.bomvalor.com.br/universodosleiloes/alexsand… | 9 | ✓ |
| Paulo Mario Lopes Machado | SC | https://www.leiloeiro.online | high | 200 | static | https://www.leiloeiro.online/lotes/imovel | 9 | ✓ |
| Arnaldo Emílio Colombarolli | MG | https://arnaldoleiloes.com.br/ | high | 200 | hybrid | https://arnaldoleiloes.com.br/lote/LOTE-14---Imovel-Lagoa-S… | 9 | ✓ |
| JOSÉ CLÓVIS VAZ DE SOUZA | RS | http://www.clovisleiloeiro.com.br | high | 200 | static | https://www.clovisleiloeiro.com.br/leilao/lotes/imoveis | 9 | ✓ |
| KAIO ALBUQUERQUE ROSA BOTELHO | DF | https://www.duxleiloes.com.br | high | 200 | static | https://www.duxleiloes.com.br/lote/57120/leilao-tjdft-07037… | 9 | ✓ |
| Rudival Almeida Gomes Junior | BA | https://www.rjleiloes.com.br | high | 200 | static | https://www.rjleiloes.com.br/lotes/imovel | 9 | ✓ |
| João Simões de Almeida Júnior | MG | https://www.simoesleiloes.com.br | medium | 200 | static | http://suporteleiloes.com/ | 9 | ✓ |
| GUILHERME EDUARDO STUTZ TOPOROSKI | PR | https://topoleiloes.com.br | high | 200 | static | https://topoleiloes.com.br/lote/33991/comercialindustrial-a… | 9 | ✓ |
| VALÉRIA PONTES BRAGA KAHN | RJ | HTTPS://MVLEILOES.COM.BR | high | 200 | static | https://mvleiloes.com.br/leilao_imoveis/terreno-de-45-000m%… | 9 | ✓ |
| GILBERTO RUIZ GUILHEN | PR | http://www.ggleiloes.com.br | medium | 200 | static | https://www.suporteleiloes.com.br | 9 | ✓ |
| Anderson Luchtenberg | SC | https://www.goldenbrazilleiloes.com.br | high | 200 | static | https://www.goldenbrazilleiloes.com.br/leilao/lotes/imoveis | 9 | ✓ |
| Guilherme E. Stutz Toporoski | SC | https://www.topoleiloes.com.br | high | 200 | static | https://topoleiloes.com.br/lote/33991/comercialindustrial-a… | 9 | ✓ |
| Kleiber Leite Pereira Junior | MT | https://www.kleiberjrleiloes.com.br/ | medium | 200 | static | https://www.suporteleiloes.com.br | 9 | ✓ |
| ENNO DE FIGUEIREDO PORTO | ES | https://www.portoleiloes.com.br/ | medium | 200 | static | https://www.suporteleiloes.com.br | 9 | ✓ |
| Thiago Luis Stefanelli Campos | MG | https://www.stefanellileiloes.com.br | medium | 200 | static | https://www.suporteleiloes.com.br | 9 | ✓ |
| POLIANA MIKEJEVS CALÇA | PR | https://www.superbid.net | medium | 200 | dynamic | https://www.superbid.net/oferta/imovel-residencial-e-comerc… | 8 | ✓ |
| Francisco Portela Aguiar | RO | https://www.portelaleiloes.com.br | high | 200 | static | https://www.portelaleiloes.com.br/leiloes/encerrados | 8 | ✓ |
| Enéas Carrilho De Vasconcelos Neto | SC | https://www.arrematebem.com.br | high | 200 | static | https://vasconcelosleiloes.com.br/lote/471/imovel-rural-em-… | 8 | ✓ |
| JOÍO LUIZ DE OLIVEIRA | PR | https://www.joaoluizleiloes.com.br | high | 200 | static | https://www.joaoluizleiloes.com.br/lotes/imovel | 8 | ✓ |
| SPENCER D’AVILA FOGAGNOLI | PR | https://spencerleiloes.com.br/ | medium | 200 | static | https://spencerleiloes.com.br/leilao/761/vara-de-familia-e-… | 8 | ✓ |
| RAFAEL DANIELEWICZ | PR | https://rdleiloes.com.br/ | high | 200 | static | https://rdleiloes.com.br/lote/1088/leilao-judicial-de-apart… | 8 | ✓ |
| Alglécio Bueno da Silva | MT | https://www.leiloesgoias.com.br | high | 200 | static | https://www.buenoleiloes.com.br/eventos/leilao/justica-do-t… | 8 | ✓ |
| MARIA CLARICE DE OLIVEIRA | PR | https://mariaclariceleiloes.com.br/ | medium | 200 | static | https://mariaclariceleiloes.com.br/lote/21782/imovel-aparta… | 8 | ✓ |
| LUIZ BARBOSA DE LIMA JUNIOR | PR | https://www.lbleiloes.com.br/ | medium | 200 | static | https://www.lbleiloes.com.br/categoria/1 | 8 | ✓ |
| MARCELO SOARES DE OLIVEIRA | PR | https://oleiloes.com.br/ | high | 200 | static | https://oleiloes.com.br/lote/CS4265/1 | 8 | ✓ |
| ANA MARIA DAL'AQUA PAZ | RS | http://www.dalaqualeiloes.com.br | medium | 200 | static | http://www.dalaqualeiloes.com.br/eventos/leilao/71/comarca-… | 8 | ✓ |
| MARCELO TREVISAN | RS | https://www.trevisanleiloes.com.br | high | 200 | static | https://www.trevisanleiloes.com.br/leilao/lotes/imoveis | 7 | ✓ |
| MARCELO VALLAND | DF | https://www.valland.com.br | high | 200 | dynamic | https://www.hastapublica.com.br/lote/103647/Imóvel-industri… | 7 | ✓ |
| Eustácio Medeiros Neves | BA | https://www.eustacio.com.br | high | 200 | static | https://eustacio.com.br/leilao/leilao34/ | 7 | ✓ |
| GABRIEL SILVA DA ROSA | RS | https://www.gabrielleiloes.com.br | high | 200 | static | https://www.gabrielleiloes.com.br/leilao/lotes/imoveis | 7 | ✓ |
| LUIZ EGIDIO CRUZ MEDEIROS | PR | https://www.medeirosleiloes.com.br | high | 200 | static | https://www.medeirosleiloes.com.br/leilao/lotes/imoveis | 7 | ✓ |
| CARLOS AUGUSTO RIBEIRO LIMA | DF | https://www.infinityleiloes.com.br | high | 200 | static | https://www.infinityleiloes.com.br/leilao/587/lotes | 7 | ✓ |
| Patricia Pimentel Grocoski Costa | AM | https://www.pimentelleiloes.com.br/ | high | 200 | hybrid | https://www.pimentelleiloes.com.br/lotes/imovel | 7 | ✓ |
| SILVIO LUCIAN | RS | https://www.lucianleiloes.com.br | medium | 200 | static | https://www.lucianleiloes.com.br/categoria/6/imoveis/leilao… | 6 | ✓ |
| Wellington Martins Araújo | MT | https://www.araujoleiloes.com.br/ | medium | 200 | hybrid | https://araujoleiloes.com.br/leilao/425-leilao-cuiaba/ | 6 | ✓ |
| JOSÉ PAULO PEREIRA CARVALHO BONATTO | RS | https://leiloeirobonatto.com/ | high | 200 | static | https://www.leiloeirobonatto.com | 6 | ✓ |
| Maurício Paes Inácio | BA | https://www.hastaleiloes.com.br/ | high | 200 | static | https://www.hastaleiloes.com.br/leiloes/encerrados | 6 | ✓ |
| Hilda Emília de Souza Costa Lima | BA | https://www.hastaleiloes.com.br/ | high | 200 | static | https://www.hastaleiloes.com.br/leiloes/encerrados | 6 | ✓ |
| Katiuscia Martins Araujo | MT | https://www.araujoleiloes.com.br/ | medium | 200 | hybrid | https://araujoleiloes.com.br/leilao/425-leilao-cuiaba/ | 6 | ✓ |
| MICHELLI FELINI GAL LOPES | RS | http://www.michellileiloes.com.br | high | 200 | static | https://www.michellileiloes.com.br/leilao/lotes/imoveis | 6 | ✓ |
| DANIEL LAZOWNIK DUARTE | RS | https://www.dldleiloeiro.com.br | high | 200 | static | https://www.dldleiloeiro.com.br/leilao/lotes/imoveis | 6 | ✓ |
| ANTÔNIO RICARDO SILVA DE LARA | RS | http://www.leiloeslaraforster.com.br | high | 200 | static | https://www.leiloeslaraforster.com.br/leilao/detalhe_leilao… | 6 | ✓ |
| Irani Flores | MT | https://www.leilaobrasil.com.br/ | medium | 200 | static | https://www.leilaobrasil.com.br/eventos/leilao/4409/imovel-… | 6 | ✓ |
| Murilo Paes Lopes Lourenço | MT | https://www.leilaobrasil.com.br/ | medium | 200 | static | https://www.leilaobrasil.com.br/eventos/leilao/4409/imovel-… | 6 | ✓ |
| DAGMAR CONCEICAO DE SOUZA FLORES | MT | https://www.leilaobrasil.com.br | medium | 200 | static | https://www.leilaobrasil.com.br/eventos/leilao/4409/imovel-… | 6 | ✓ |
| TELMO ARMANDO MORALES NETO | RS | https://www.lucianleiloes.com.br | medium | 200 | static | https://www.lucianleiloes.com.br/categoria/6/imoveis/leilao… | 6 | ✓ |
| GIULIANO FERRONATO | RS | http://www.clicleilao.com.br | high | 200 | static | https://www.ferronato.leilao.br/leilao/lotes/imoveis | 5 | ✓ |
| Marco Antônio Barbosa de Oliveira … | MA | https://www.marcoantonioleiloeiro.com.br | medium | 200 | static | https://www.marcoantonioleiloeiro.com.br/eventos/leilao/110… | 5 | ✓ |
| MARCIANO BARBIERI | RS | https://www.leiloeirobarbieri.com.br | high | 200 | static | https://www.leiloeirobarbieri.com.br/leilao/imovel-rua-sepe… | 5 | ✓ |
| Marcelo Carneiro Bernardelli | MS | https://www.marcaleiloes.com.br | high | 200 | static | https://www.marcaleiloes.com.br/buscador?categoria=2 | 5 | ✓ |
| MANOEL LUIZ NEVES VELHO | RS | https://www.leilaobutia.com.br | high | 200 | static | https://www.leilaobutia.com.br/leilao/lotes/imoveis | 5 | ✓ |
| JEAN CARLO ROSA | GO | https://www.prosperarleiloes.com.br | high | 200 | static | https://www.prosperarleiloes.com.br/externo/lote/276/leilao… | 5 | ✓ |
| JOSEANE DE AVILA SCOTTO | RS | http://www.leiloes.rs | high | 200 | static | https://www.scottoleiloes.com.br/leilao/lotes/imoveis | 5 | ✓ |
| Ronald de Freitas Moreira | MG | https://www.rofremleiloes.com.br | medium | 200 | static | https://www.rofremleiloes.com.br/buscador?categoria=2 | 5 | ✓ |
| Rodrigo Collyer Santos de Oliveira | MG | https://www.rodrigoleiloeiro.com.br | medium | 200 | static | https://www.rodrigoleiloeiro.com.br/eventos/leilao/1101/imo… | 5 | ✓ |
| Pedro Miranda Jinkings | MG | https://www.milhaoleiloes.com.br | high | 200 | dynamic | https://www.milhaoleiloes.com.br/lote/venda-direta-fazenda-… | 5 | ✓ |
| Osman Sobral e Silva | SE | https://www.leiloesfreire.com.br/ | medium | 200 | static | https://www.leiloesfreire.com.br/categoria-lote/7 | 5 | ✓ |
| IVAN LEOCI BARTMANN | RS | https://www.bartmannleiloes.com.br | high | 200 | static | https://www.bartmannleiloes.com.br/leilao/lotes/imoveis | 5 | ✓ |
| GRAZIELLA TASSI SANTOS | GO | https://www.gfleiloes.com.br | high | 200 | dynamic | https://www.gfleiloes.com.br/lote/1-terreno-area-de-107129m… | 5 | ✓ |
| VALENTINA BORGES DE PAULA | GO | https://www.gfleiloes.com.br | high | 200 | dynamic | https://www.gfleiloes.com.br/lote/1-terreno-area-de-107129m… | 5 | ✓ |
| ADRIANO DE JESUS SILVA | GO | https://www.gfleiloes.com.br | high | 200 | dynamic | https://www.gfleiloes.com.br/lote/1-terreno-area-de-107129m… | 5 | ✓ |
| ADOLPHO AGOSTINHO MENDES QUARESMA | GO | https://www.gfleiloes.com.br | high | 200 | dynamic | https://www.gfleiloes.com.br/lote/1-terreno-area-de-107129m… | 5 | ✓ |
| EDUARDO DOS REIS | SP | https://www.casareisleiloesonline.com.b… | high | 200 | dynamic | https://www.casareisleiloes.com.br/lote/imovel-comercial-av… | 5 | ✓ |
| ROBERTO DOS REIS JUNIOR | SP | https://www.casareisleiloesonline.com.b… | high | 200 | dynamic | https://www.casareisleiloes.com.br/lote/imovel-comercial-av… | 5 | ✓ |
| CLADEMIR DOS SANTOS FLORES | RS | http://www.clademirleiloeiro.com.br | high | 200 | static | https://www.clademirleiloeiro.com.br/leilao/lotes/imoveis | 5 | ✓ |
| ANDRÉ BAZACAS VELHO | RS | https://www.leilaobutia.com.br | high | 200 | static | https://www.leilaobutia.com.br/leilao/lotes/imoveis | 5 | ✓ |
| ENO LOUREIRO DE MENEZES | RS | http://www.blmleiloes.com.br | high | 200 | static | https://www.blm.leilao.br/leilao/lotes/imoveis | 5 | ✓ |
| Guilherme Caixeta Borges | MG | https://www.milhaoleiloes.com.br | high | 200 | dynamic | https://www.milhaoleiloes.com.br/lote/venda-direta-fazenda-… | 5 | ✓ |
| Guilherme A. Scarpari De Lucca | SC | https://www.deluccaleiloes.com.br | high | 200 | static | https://www.deluccaleiloes.com.br/leilao/lotes/imoveis | 5 | ✓ |
| BRENO LOUREIRO DE MENEZES | RS | http://www.blmleiloes.com.br | high | 200 | static | https://www.blm.leilao.br/leilao/lotes/imoveis | 5 | ✓ |
| João Gabriel da Silva e Oliveira | MT | https://www.marcaleiloes.com.br | high | 200 | static | https://www.marcaleiloes.com.br/buscador?categoria=2 | 5 | ✓ |
| FLAVIO DUARTE CERULI | GO | https://www.gfleiloes.com.br | high | 200 | dynamic | https://www.gfleiloes.com.br/lote/1-terreno-area-de-107129m… | 5 | ✓ |
| DORA PLAT | GO | https://www.gfleiloes.com.br | high | 200 | dynamic | https://www.gfleiloes.com.br/lote/1-terreno-area-de-107129m… | 5 | ✓ |
| Carlos Henrique Barbosa | MT | https://www.chbarbosaleiloes.com.br | high | 200 | dynamic | https://www.chbarbosaleiloes.com.br/lote/imovel-rural-com-2… | 5 | ✓ |
| DIEGO WOLF DE OLIVEIRA | GO | https://www.gfleiloes.com.br | high | 200 | dynamic | https://www.gfleiloes.com.br/lote/1-terreno-area-de-107129m… | 5 | ✓ |
| Alex Vieira Passos | MT | https://portalax.com.br/ | medium | 200 | dynamic | https://portalax.com.br/leilao/1-leilao-judicial---tribunal… | 4 | ⚠ |
| Jorge José João Filho | MG | https://www.tradicaoleiloes.com.br | high | 200 | hybrid | https://www.tradicaoleiloes.com.br/lote/edital-sicoob-agroc… | 4 | ⚠ |
| Felipe Gonzaga Daux | SC | https://www.daux.com.br | high | 200 | static | https://www.daux.com.br/leilao/255 | 4 | ⚠ |
| FELIPE GUIMARÃES CARRIJO | AM | https://www.leilomaster.com.br | high | 200 | dynamic | https://leilo.com.br/leilao | 4 | ⚠ |
| NATÁLIA NARITA NUNES DE FREITAS | DF | https://www.natalialeiloes.com.br | high | 200 | static | https://www.natalialeiloes.com.br/leilao/925/lotes | 4 | ⚠ |
| UNO DUARTE ARAÚJO DOS SANTOS | DF | https://www.leiloes61.com.br | high | 200 | static | https://leiloes61.com.br/externo/leiloes-passados | 4 | ⚠ |
| Sergio Fleury Batista | MT | https://www.leilomaster.com.br/ | high | 200 | dynamic | https://leilo.com.br/leilao/?leilao.nome=LEIL%C3%83O%20DE%2… | 4 | ⚠ |
| Mauro Colodete | PE | https://colodeteleiloes.com.br/ | high | 200 | static | https://colodeteleiloes.com.br/leilao/1684/lotes | 4 | ⚠ |
| Alexandre Buaiz Neto | ES | https://www.buaizleiloes.com.br/ | medium | 200 | static | https://www.buaizleiloes.com.br/eventos/leilao/607/1-um-imo… | 4 | ⚠ |
| CLAUDIO SOUSA DOS SANTOS | SP | https://www.allianceleiloes.com.br | high | 200 | static | https://www.allianceleiloes.com.br/leiloes/70-casa-jabaquara | 4 | ⚠ |
| LEONARDO NUNES LOBO | GO | https://www.leilo.com.br | high | 200 | dynamic | https://leilo.com.br/leilao/?leilao.nome=LEIL%C3%83O%20DE%2… | 4 | ⚠ |
| RODRIGO PAES CAMAPUM BRINGEL | GO | https://www.leilo.com.br | high | 200 | dynamic | https://leilo.com.br/leilao/?leilao.nome=LEIL%C3%83O%20DE%2… | 4 | ⚠ |
| RAFAELA MELO FERREIRA MARZANO | BA | https://www.palaciodosleiloes.com.br/ | high | 200 | dynamic | https://www.palaciodosleiloes.com.br/site/leilao.php?leilao… | 4 | ⚠ |
| IZABELLA MELO FERREIRA PRAES | MG | https://www.palaciodosleiloes.com.br/ | high | 200 | dynamic | https://www.palaciodosleiloes.com.br/site/leilao.php?leilao… | 4 | ⚠ |
| CRISTIANO GOMES FERREIRA | MG | https://www.palaciodosleiloes.com.br/ | high | 200 | dynamic | https://www.palaciodosleiloes.com.br/site/leilao.php?leilao… | 4 | ⚠ |
| FELIPE GUIMARÍES CARRIJO | AM | https://www.leilomaster.com.br | high | 200 | dynamic | https://leilo.com.br/leilao | 4 | ⚠ |
| DEDIANA FARIAS | RS | https://www.fariasleiloes.com.br | high | 200 | static | https://www.fariasleiloes.com.br/leilao/lotes/imoveis | 4 | ⚠ |
| DÉBORA REGINA BARZ | RS | https://www.deborabarzleiloes.com.br | high | 200 | static | https://www.deborabarzleiloes.com.br/leilao/lotes/imoveis | 4 | ⚠ |
| HELIANA MARIA OLIVEIRA MELO FERREI… | MG | https://www.palaciodosleiloes.com.br/ | high | 200 | dynamic | https://www.palaciodosleiloes.com.br/site/leilao.php?leilao… | 4 | ⚠ |
| CRISTIANO BRANCHIERI ESCOLA | RS | https://www.cristianoescolaleiloes.com.… | medium | 200 | hybrid | https://www.cristianoescolaleiloes.com.br/leilao-unico/leil… | 4 | ⚠ |
| Diego Wolf De Oliveira | SC | https://www.diegoleiloes.com.br | high | 200 | static | https://www.diegoleiloes.com.br/lotes/imovel | 4 | ⚠ |
| Regina Aude Leite De Araujo Silva | MS | https://www.reginaaudeleiloes.com.br | high | 200 | static | https://www.reginaaudeleiloes.com.br/leilao/1-vara-de-execu… | 4 | ⚠ |
| DÉBORA JANAÍNA MÜLLER CORTES | RS | http://www.deboramullerleiloes.com.br | high | 200 | static | https://www.deboramullerleiloes.com.br/leilao/leilao-em-can… | 4 | ⚠ |
| Rogério Lopes Ferreira | MG | https://www.palaciodosleiloes.com.br/ | high | 200 | dynamic | https://www.palaciodosleiloes.com.br/site/leilao.php?leilao… | 4 | ⚠ |
| SILVIA HELENA BALBINO BARROS PALMA | DF | https://www.leilomaster.com.br | high | 200 | static | https://leilo.com.br/leilao | 4 | ⚠ |
| Ely Da Luz Ramos | SC | https://www.elydaluzramos.com.br | medium | 200 | static | https://www.elydaluzramos.com.br/oferta/leilao/imoveis/casa… | 4 | ⚠ |
| César Luis Moresco | DF | https://www.morescoleiloes.com.br | high | 200 | static | https://www.morescoleiloes.com.br/leilao/leilao-imovel-cida… | 4 | ⚠ |
| Vinícius Vidal Lacerda | PB | https://www.vlleiloes.com.br | medium | 200 | static | https://www.vlleiloes.com.br/eventos/leilao/382/judicial-su… | 4 | ⚠ |
| Luiz Felipe Perpétuo Lobato | MG | https://www.luizlobatoleiloeiro.com.br | medium | 200 | static | https://www.luizlobatoleiloeiro.com.br/oferta/leilao/imovei… | 3 | ⚠ |
| José Arquimedes Câmara | MG | https://www.arquimedesleiloes.com.br | medium | 200 | static | https://www.arquimedesleiloes.com.br/leiloesarealizar | 3 | ⚠ |
| MÁRIO LESSA FREITAS FILHO | RS | https://www.lessaleiloes.com.br | high | 200 | static | https://www.lessaleiloes.com.br/leilao/lotes/imoveis | 3 | ⚠ |
| Anderson Douglas Gali Falleiros | BA | https://www.falleirosleiloes.com.br | high | 200 | dynamic | https://www.falleirosleiloes.com.br/lote/exemplo-de-leilao-… | 3 | ⚠ |
| IONEIDE MARIA FERNANDES SAMPAIO | DF | https://www.almoedaleiloes.com.br | medium | 200 | static | https://www.almoedaleiloes.com.br/externo/leilao/57/leilao-… | 3 | ⚠ |
| VILTON PEREIRA DA SILVA | GO | https://www.innovaleiloes.com.br | medium | 200 | static | https://www.innovaleiloes.com.br/lote/50438/leilao-de-um-im… | 3 | ⚠ |
| GALVÍO ADENYR LOPES JUNIOR | PR | http://www.lancejusto.com.br | high | 200 | static | https://lancejusto.com.br/lote/425/condominio-theodoro-de-b… | 3 | ⚠ |
| NEWTON JORGE GONÇALVES DE OLIVEIRA | PR | https://www.newtonleiloes.com.br/ | high | 200 | static | https://newtonleiloes.com.br/lote/1623/terreno-em-paranavai… | 3 | ⚠ |
| Silvio Luiz Silva de Moura Leite | MT | https://www.mlleiloes.com.br | medium | 200 | static | https://www.mlleiloes.com.br/externo/leilao/51/leilao-judic… | 3 | ⚠ |
| VANESSA GOELZER DE ARAÚJO VARGAS E… | PR | https://www.vargasepintoleiloes.com.br | high | 200 | static | https://www.vargasepintoleiloes.com.br/externo/leilao/127/l… | 3 | ⚠ |
| FERNANDA VON ZUCCALMAGLIO | RS | https://www.zuccalmaglioleiloes.com.br | high | 200 | static | https://www.zuccalmaglioleiloes.com.br/leilao/lotes/imoveis | 3 | ⚠ |
| GALVÃO ADENYR LOPES JUNIOR | PR | https://www.lancejusto.com.br | high | 200 | static | https://lancejusto.com.br/lote/425/condominio-theodoro-de-b… | 3 | ⚠ |
| EDUARDO VIVIAN | RS | https://www.eduardovivian.com | high | 200 | static | https://www.eduardovivian.com.br/leilao/em-osorio-na-rua-ba… | 3 | ⚠ |
| Ulisses Donizete Ramos | SC | https://donizetteleiloes.leilao.br/ | medium | 200 | static | https://donizetteleiloes.leilao.br/eventos/leilao/imovel-ur… | 3 | ⚠ |
| JOÍO HONOR COIROLLO DE SOUZA | RS | http://www.jhcleiloeirooficial.lel.br | high | 200 | static | https://www.jhcleiloeirooficial.lel.br/leilao/lotes/imoveis | 3 | ⚠ |
| ANTONIO ALEXANDRE RAOTA | RS | https://www.raotaleiloes.com.br | high | 200 | dynamic | https://www.raotaleiloes.com.br/lote/terreno-beira-do-rio-j… | 3 | ⚠ |
| JUSSIARA SANTOS ERMANO SUKIENNIK | DF | https://www.jussiaraleiloes.com | high | 200 | static | https://www.jussiaraleiloes.com/externo/lote/5636/leilao-da… | 3 | ⚠ |
| Luiz Tenório De Paula | RJ | https://www.depaulaonline.com.br | medium | 200 | hybrid | https://www.depaulaonline.com.br/leiloes/324 | 3 | ⚠ |
| FERNANDO CÉZAR TOBIAS DA SILVA | DF | https://www.dfleiloes.com.br | medium | 200 | static | https://www.dfleiloes.com.br/externo/leilao/300 | 3 | ⚠ |
| Rodrigo de Oliveira Lopes | MG | https://www.leiloesuberlandia.com.br | high | 200 | static | https://www.leiloesuberlandia.com.br/externo/leilao/751/lei… | 3 | ⚠ |
| Luiz Washington Campolina Santos | MG | https://www.luizcampolina.com.br | high | 200 | static | https://luizcampolina.com.br/produto/lote-1-bem-imovel-rura… | 2 | ⚠ |
| Diórgenes Valério Jorge | SC | https://www.catarinenseleiloes.com.br | high | 200 | static | https://www.djleilao.com.br/leilao/lotes/imoveis | 2 | ⚠ |
| ODILSON FUMAGALLI AVILA | RS | https://www.fumagallileiloes.com.br | high | 200 | static | https://www.fumagallileiloes.com.br/leilao/lotes/imoveis | 2 | ⚠ |
| Quênia De Luca Martins | SC | https://www.leiloes-sc.com.br | high | 200 | static | https://www.leiloes-sc.com.br/leilao/lotes/imoveis | 2 | ⚠ |
| JOÃO HONOR COIROLLO DE SOUZA | RS | https://www.jgcargneluttileiloes.com.br | high | 200 | static | https://www.jgcargneluttileiloes.com.br/leilao/1/lotes | 2 | ⚠ |
| JOÃO GUILHERME CARGNELUTTI | RS | https://www.jgcargneluttileiloes.com.br | high | 200 | static | https://www.jgcargneluttileiloes.com.br/leilao/1/lotes | 2 | ⚠ |
| HENRIQUE ARNOLDO JUNIOR | RS | https://arnoldoleiloes.com.br | high | 200 | static | https://www.arnoldoleiloes.com.br/leilao/lotes/imoveis | 2 | ⚠ |
| LUCAS EDUARDO DALCANALE | PR | https://dalcanaleleiloes.com.br/ | medium | 200 | static | https://dalcanaleleiloes.com.br/categoria/1 | 2 | ⚠ |
| ERICK SOARES HAMMOUD TELES | GO | https://www.tezaleiloes.com.br | high | 200 | hybrid | https://www.teza.com.br/Redirect/698/ | 2 | ⚠ |
| FERNANDO DE OLIVEIRA KUSS | MG | http://www.ksleiloes.com.br | high | 200 | static | https://ksleiloes.com.br/lote/5/fazenda-mandaguari | 2 | ⚠ |
| JOÍO GUILHERME CARGNELUTTI | RS | http://www.jgcargneluttileiloes.com.br | high | 200 | static | https://www.jgcargneluttileiloes.com.br/leilao/1/lotes | 2 | ⚠ |
| EDUARDO SCHMITZ | AL | https://www.clicleiloes.com.br/ | high | 200 | static | https://www.clicleiloes.com.br/lotes/imovel | 2 | ⚠ |
| EDUARDO SCHMITZ | MG | https://www.clicleiloes.com.br | high | 200 | static | https://www.clicleiloes.com.br/lotes/imovel | 2 | ⚠ |
| Renan Souza Silva | MG | https://www.silvaleiloes.com.br | high | 200 | dynamic | https://www.silvaleiloes.com.br/lote/curitiba-pr-veiculo-fo… | 2 | ⚠ |
| Tarcílio Leite | MS | https://www.casadeleiloes.com.br | high | 200 | static | https://www.casadeleiloes.com.br/leilao/1-vara-de-execucao-… | 2 | ⚠ |
| Gabriel Fardin Pereira | ES | https://www.vixleiloes.com.br/ | medium | 200 | static | https://www.vixleiloes.com.br/leiloes/52 | 2 | ⚠ |
| EDMAR OLIVEIRA ANDRADE NETO | SP | https://www.agleiloes.com.br/ | high | 200 | dynamic | https://www.agleiloes.com.br/lote/itatiba-res-reserva-bella… | 2 | ⚠ |
| ERICK SOARES TELES | MT | https://www.teza.com.br/ | high | 200 | hybrid | https://www.teza.com.br/Redirect/698/ | 2 | ⚠ |
| Luci Vera Primaz Dos Reis | SC | https://www.luciverareisleiloes.com.br | high | 200 | static | https://www.luciverareisleiloes.com.br/leilao/comarca-de-cr… | 1 | ⚠ |
| SANDRA REGINA WONTROBA | RS | http://www.swleiloes.com.br | high | 200 | static | https://www.swleiloes.com.br/leilao/lotes/imoveis | 1 | ⚠ |
| Suelem Regina Bocasanta | SC | https://www.sbleiloes.lel.br | high | 200 | static | https://www.sb.leilao.br/leilao/lotes/imoveis | 1 | ⚠ |
| PEDRO DO PRADO UTZIG | RS | https://www.utzigleiloes.com.br | high | 200 | static | https://www.utzigleiloes.com.br/leilao/lotes/imoveis | 1 | ⚠ |
| JOSÉ FERNANDO DE QUINA | RS | https://www.qleilao.lel.br | high | 200 | dynamic | https://www.qleilao.lel.br/evento/de-375mil-por-apenas-r300… | 1 | ⚠ |
| JOSÉ ALMIRO CHAGAS DE ALENCASTRO | RS | https://alencastroleiloes.com.br | high | 200 | static | https://www.alencastroleiloes.com.br/lotes-leilao-10-de-fev… | 1 | ⚠ |
| JORGE ERLI RITTA | RS | https://www.jritta.lel.br | high | 200 | static | https://www.jritta.lel.br/leilao/lotes/imoveis | 1 | ⚠ |
| ROGERIO DAMASIO DE OLIVEIRA | SP | https://WWW.DAMASIOLEILOES.COM.BR | high | 200 | static | https://www.damasioleiloes.com.br/leilao/4/lotes | 1 | ⚠ |
| LUIS FILIPE GEYER FLORES | RS | http://www.leiloeiros.lel.br | high | 200 | static | https://www.jritta.lel.br/leilao/lotes/imoveis | 1 | ⚠ |
| ALEXSANDRO PEREIRA | RS | https://www.alexsandroleiloes.com.br | medium | 200 | static | https://www.alexsandroleiloes.com.br/leilao-virtual/leilao-… | 1 | ⚠ |
| Guilherme Lopes de Souza | MG | https://www.leilominas.com.br | high | 200 | unknown | nan | 0 | ⚠ |
| Luiz Balbino Da Silva Junior | SC | https://www.balbinoleiloes.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| Ruam Carlos Chaves Gotardo | MG | https://www.leiloesnovaserrana.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| JIMMY ASAMI | AM | https://www.asamileiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| SÉRGIO RICARDO DE BRITO BORGES | RS | http://www.gestorleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| Marcos Paulo Branco de Morais | MG | https://www.saladeleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| Sarita Ana Giacomazzi Araujo | SC | https://www.pandacolecoes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| Luiz Ubiratã de Carvalho | DF | https://www.luizleiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| Antonio Jose da Silva Filho | MT | https://www.ajleiloes.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| Lorrana Ramos Mendes Gotardo | MG | https://www.lorranaleiloes.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| José Antônio Rodovalho Junior | MT | https://www.leiloesjudiciaismgnorte.com… | high | 200 | dynamic | https://www.joserodovalholeiloes.com.br/index/mapa-imoveis?… | 0 | ⚠ |
| Lincoln de Azevedo Fernandes | MG | https://www.lincolnleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| Leonardo Veiga de Jesus Chaves | MG | https://www.leonardoveigaleiloes.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| Gustavo Costa Aguiar Oliveira | MG | https://www.gpleiloes.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| Kananda Sofia Silva Macedo | MG | https://www.kanandaleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| CONCEIÇÃO MARIA FIXER | SC | https://www.mariafixerleiloes.com.br | high | 200 | dynamic | https://www.mariafixerleiloes.com.br/index/mapa-imoveis?exi… | 0 | ⚠ |
| RANGEL MACHADO | RS | https://www.rangelleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| GIORDANO BRUNO COAN AMADOR | PR | https://www.giordanoleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| Ricardo Bampi | SC | https://www.bampileiloes.com.br | high | 200 | static | https://www.bampileiloes.com.br/leilao/juizes | 0 | ⚠ |
| Francisco das Chagas Pereira Júnior | CE | https://www.pereiraleiloesce.com.br | high | 200 | static | nan | 0 | ⚠ |
| PAULO RENATO HUMOR | RS | http://www.prhleiloes.com.br | medium | 200 | dynamic | http://www.prhleiloes.com.br/leilao.asp?Num=61384 | 0 | ⚠ |
| João Lopes Cavalcante | CE | https://www.lopesleiloes.net.br | high | 200 | static | nan | 0 | ⚠ |
| Flávia Figueira Messias | MG | https://www.messiasleiloes.com.br | high | 200 | static | https://www.messiasleiloes.com.br/index/mapa-imoveis?exibeM… | 0 | ⚠ |
| Fernando Chui | MG | https://www.chuileiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| Fernando Montenegro Castelo | CE | https://www.montenegroleiloes.com.br | medium | 200 | unknown | nan | 0 | ⚠ |
| Tatiane Dos Santos Duarte | SC | https://www.dloficiais.com.br | medium | 200 | static | nan | 0 | ⚠ |
| Fábio Manoel Guimarães | DF | https://www.fabioleiloes.com.br | high | 200 | dynamic | https://www.fabioleiloes.com.br/index/mapa-imoveis?exibeMap… | 0 | ⚠ |
| Fábio Guimarães de Carvalho | MG | https://www.fabioguimaraesleiloes.com.br | medium | 200 | hybrid | nan | 0 | ⚠ |
| Emidio José Correia de Medeiros | MG | https://www.emidiomedeirosleiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| Davison Mauro Moreira | MG | https://www.davisonmoreira.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| Moreno César Oliveira Farias | MG | https://www.brfleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| Bruno Lopes Pereira dos Reis | MG | https://www.iarremate.com/bruno-reis-ar… | medium | 200 | static | nan | 0 | ⚠ |
| Ângela Assis Oliveira Bechara | MG | https://www.angelabecharaleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| Moreno Augusto Magalhães da Anunci… | MG | https://www.bmleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| André Fonseca Dias | MG | https://www.agilleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| CARLO FERRARI | DF | https://www.carloferrarileiloes.com.br | high | 200 | hybrid | https://www.carloferrarileiloes.com.br/index/mapa-imoveis?e… | 0 | ⚠ |
| ARNOLD STRASS | MG | https://www.savoyleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| Alexandra Benedita de Sousa Casado | MG | https://www.ecoleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| ANDRE MARIO ARAUJO | SP | https://www.andrearaujoleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| Álvaro Sérgio Fuzo | DF | https://www.leiloesjudiciaisgo.com.br | high | 200 | dynamic | https://alvaroleiloes.com.br/index/mapa-imoveis?exibeMapa=1 | 0 | ⚠ |
| LUIZ DE CHIRICO JUNIOR | SP | https://www.leiloesdonorte.com.br | high | 200 | static | nan | 0 | ⚠ |
| João Paulo Ferreira | CE | https://www.montenegroleiloes.com.br | medium | 200 | unknown | nan | 0 | ⚠ |
| MARCELO HENRIQUE PERRARO | RS | https://www.leiloeirojudicial.lel.br | high | 200 | static | nan | 0 | ⚠ |
| MAURICIO SAMBUGARI APPOLINARIO | SP | https://www.selectleiloes.com.br | high | 200 | static | https://www.selectleiloes.com.br/leilao/juizes | 0 | ⚠ |
| Danyllo de Oliveira Maia | DF | https://dmleiloesjudiciais.com.br | high | 200 | dynamic | https://dmleiloesjudiciais.com.br/index/mapa-imoveis?exibeM… | 0 | ⚠ |
| Maria Conceição Maria Fixer | CE | https://www.mariafixerleiloes.com.br | high | 200 | dynamic | https://www.mariafixerleiloes.com.br/index/mapa-imoveis?exi… | 0 | ⚠ |
| Jorge Francisco | DF | https://www.jfleiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| Rubens Henrique De Castro | SC | https://www.usadaomaquinas.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| IAN GALVÃO FROTA | AM | https://www.amazonasleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| André Luiz Wuitschik | SC | https://www.andreluizleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| Cirlei Freitas Balbino Da Silva | SC | https://www.balbinoleiloes.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| LUCIANO SCHEID | RS | https://www.scheidleiloes.com.br | medium | 200 | static | https://leilao.scheidleiloes.com.br/assinar-newsletter | 0 | ⚠ |
| ANTONIO CARLOS PERES BERNARDINI | GO | https://www.bernardinileiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| LUANA VIDAL INEU | RS | https://www.ineuleiloes.com.br/ | medium | 200 | hybrid | nan | 0 | ⚠ |
| DEONIZIA KIRATCH | RO | https://www.deonizialeiloes.com.br | high | 200 | dynamic | https://www.deonizialeiloes.com.br/index/mapa-imoveis?exibe… | 0 | ⚠ |
| ODARLI CANEZIN | PR | http://www.odarlicanezinleiloes.com.br | medium | 200 | dynamic | https://www.odarlicanezinleiloes.com.br/leiloes | 0 | ⚠ |
| Tiago Tessler Blecher | BA | https://dearaujoleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| UNO HENRIQUE LOPES | DF | https://www.brunoleiloes.com.br | high | 200 | dynamic | https://www.brunoleiloes.com.br/index/mapa-imoveis?exibeMap… | 0 | ⚠ |
| NICOLAS TADASHI MATSUNE | PR | http://www.tadashileiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| LEONICE FIXER | PR | http://www.capitalvalorleiloes.com.br | high | 200 | static | http://www.capitalvalorleiloes.com.br/index/mapa-imoveis?ex… | 0 | ⚠ |
| ÁULIO FERREIRA NETO | DF | https://braunaleiloes.blogspot.com.br | medium | 200 | static | nan | 0 | ⚠ |
| João Paulo Mineiro Bezerra | BA | http://www.bezerraleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| JOÍO VITOR MARTINS FERREIRA | PR | https://www.jmfleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| Thiago Barros Cardoso | SE | https://www.tbaracajuleiloes.com.br | medium | 200 | static | http://www.tbaracajuleiloes.com.br/catalogo.asp?Num=59904 | 0 | ⚠ |
| JEREMY WU SANTIAGO DA COSTA E SILVA | PR | http://www.jeremyleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| Alex Willian Hope | SE | https://www.hoppeleiloes.com.br/ | high | 200 | dynamic | nan | 0 | ⚠ |
| Tábata Mineiro Bezerra | BA | https://www.bezerraleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| FLAVIA KLOCKNER RODRIGUES | PR | http://www.fkleiloes.com.br | medium | 200 | unknown | nan | 0 | ⚠ |
| JORGE SIDIRLEI DE GODOY BRASIL | RS | https://www.jorgebrasil.lel.br/index.htm | high | 200 | static | nan | 0 | ⚠ |
| Clauberto Fernandes Nascimento Jún… | BA | https://www.hatoryleiloes.com.br/extern… | medium | 200 | static | nan | 0 | ⚠ |
| Hidirlene Duszeiko | ES | https://www.hdleiloes.com.br/ | high | 200 | dynamic | https://www.hdleiloes.com.br/index/mapa-imoveis?exibeMapa=1 | 0 | ⚠ |
| Renata Murta Moreira | MG | https://www.gpleiloes.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| FERNANDA RIBEIRO | PR | http://www.ferleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| Orlando Lopes Fernandes | ES | https://www.leilobras.lel.br/ | high | 200 | static | nan | 0 | ⚠ |
| CAROLINE FERREIRA BARBOZA | PR | http://www.bzleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| Luciana Londina da Silva | MG | https://www.londinaleiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| WERNO KLÖCKNER JÚNIOR | PR | https://www.kleiloes.com.br/# | medium | 200 | static | nan | 0 | ⚠ |
| ALEXANDRE AUGUSTO DOS SANTOS SABBAG | PR | http://www.sabbagleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| JEFFERSON HORTA BARBOSA RIBEIRO ME… | RS | http://www.mendesleiloes.com.br | medium | 200 | hybrid | nan | 0 | ⚠ |
| EDUARDO HENRIQUE FIRMINO: | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| RAIMUNDO MAGALHAES DE MORAES | PR | https://www.rmmleiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| Oscar de Menezes Palmeira | BA | https://www.oscarleiloes.com.br/ | high | 200 | static | nan | 0 | ⚠ |
| SERGIO LUIZ CRUVINEL | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| JAIME LUIZ NULMAN | RS | http://www.bidgo.com.br | high | 200 | static | nan | 0 | ⚠ |
| PABLINE GOMES LIMA | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| Tânia Maria de Abreu | BA | https://leiloestaniaabreu.wixsite.com/l… | medium | 200 | static | nan | 0 | ⚠ |
| PLINIO BARROSO DE CASTRO FILHO | PR | https://www.pbcastro.com.br/ | medium | 200 | static | nan | 0 | ⚠ |
| Paulo Cézar Rocha Teixeira | BA | https://www.leiloesjudiciaisbahia.com.br | high | 200 | dynamic | https://www.leiloesjudiciaisbahia.com.br/index/mapa-imoveis… | 0 | ⚠ |
| VICTOR RENNO POLLATO VIZEU- | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| Loemí Gonçalves Santana | MT | https://www.globoleiloes.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| PEDRO LERNER KRONBERG | PR | https://www.kronberg.lel.br/ | high | 200 | static | nan | 0 | ⚠ |
| ITALO AUGUSTO SANTOS | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| PAULO ROBERTO NAKAKOGUE | PR | https://www.vardanaleiloes.com.br/varda… | medium | 200 | static | nan | 0 | ⚠ |
| FERNANDO DA SILVA COSTA | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| GUILHERME DA COSTA | RS | https://www.ckleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| PAULO ROBERTO LEAL VARDANA | PR | https://www.vardanaleiloes.com.br/varda… | medium | 200 | static | nan | 0 | ⚠ |
| Alex Willian Hoppe | BA | https://www.hoppeleiloes.com.br/ | high | 200 | dynamic | nan | 0 | ⚠ |
| URIANGELA BORGES VIEIRA | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| Franciele Aparecida da Silva | MT | https://www.dasilvaleiloes.com.br | high | 200 | hybrid | https://www.dasilvaleiloes.com.br/index/mapa-imoveis?exibeM… | 0 | ⚠ |
| AHARO ESPIRITO SANTO AQUINO | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| Alan Carlos dos Santos | MT | https://www.matogrossoleiloes.com.br | high | 200 | hybrid | https://www.matogrossoleiloes.com.br/index/mapa-imoveis?exi… | 0 | ⚠ |
| DAVI BORGES DE AQUINO | BA | https://www.alfaleiloes.com/ | high | 200 | dynamic | nan | 0 | ⚠ |
| FABIO ROBERTO SCHAFFEL TORRES | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| Raphael Perini de Souza | MT | https://www.pantanalleiloesjudiciais.co… | high | 200 | dynamic | https://www.pantanalleiloesjudiciais.com.br/index/mapa-imov… | 0 | ⚠ |
| HUGHEVA CARVALHO SANTOS | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| Valdeir Aparecido Pereira | MT | https://www.valdeirpereiraleiloeiro.com… | high | 200 | static | nan | 0 | ⚠ |
| LUIZ RAFAEL LEMUCHI DE LIMA | PR | https://www.leiloeslr.com.br | medium | 200 | static | nan | 0 | ⚠ |
| WELLINGTON LUIS DOS SANTOS JUNIOR | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| LUIZ ODAIR FAVARETO | PR | https://www.favaretoleiloes.com.br/ | medium | 200 | static | nan | 0 | ⚠ |
| RAUL HENRIQUE GALASSI PADOVAN | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| ALEX WILLIAM HOPPE | RR | https://www.hoppeleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| LUIZ FERNANDO FAVARETO | PR | https://www.favaretoleiloes.com.br/ | medium | 200 | static | nan | 0 | ⚠ |
| LUIZ CARLOS DALL’AGNOL | PR | https://www.dallagnolleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| ALBERTO JOSE MARCHI MACEDO | MT | https://www.albertomacedoleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| JOSE LUIZ MARCHIOTTO JUNIOR | PR | https://www.zemarchiottoleiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| Marco Antônio Ferreira de Menezes | TO | https://www.agilleiloes.com.br/ | high | 200 | static | nan | 0 | ⚠ |
| JOÃO VITOR MARTINS FERREIRA | PR | https://www.jmfleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| Jorge Marco Aurélio Biavati | SC | https://www.jorgemarcoleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| FELIPE ROTTA | RS | https://www.feliperottaleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| CARLA SOBREIRA UMINO | SP | https://www.lancenoleilao.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| JAQUELINE SPERANÇA | PR | https://www.sperancaleiloes.com.br | high | 200 | hybrid | nan | 0 | ⚠ |
| JONEY MARCELO LOPES FERREIRA | PR | https://jmleiloes.com.br/ | high | 200 | dynamic | nan | 0 | ⚠ |
| ISABELLA KATARINA SCHACKER PERACCHI | PR | http://www.peracchileiloes.com.br | medium | 200 | unknown | nan | 0 | ⚠ |
| HELTON ROGÉRIO VERRI VENTRILHO | PR | https://www.verrileiloes.com.br | high | 200 | dynamic | https://www.verrileiloes.com.br/index/mapa-imoveis?exibeMap… | 0 | ⚠ |
| EVA DELMINDA STANGHERLIN | RS | https://www.evaleiloes.com.br | medium | 200 | hybrid | nan | 0 | ⚠ |
| JOACIR MONZON POUEY | DF | https://www.monzonleiloes.com.br/ | high | 200 | dynamic | nan | 0 | ⚠ |
| CASSIA NEGRETE NUNES BALBINO | SP | https://www.globoleiloes.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| JULIANA CRISTINA CARREIRA GOLFETO | GO | https://www.alfaleiloes.com | high | 200 | dynamic | nan | 0 | ⚠ |
| GABRIEL BARON JUNIOR | PR | https://www.baronleiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| BRUNA HELENA VIEIRA | GO | https://www.alfaleiloes.com | high | 200 | dynamic | nan | 0 | ⚠ |
| DENILSON KIEL | RS | https://www.kielleiloes.com.br | high | 200 | hybrid | nan | 0 | ⚠ |
| BRIAN GALVÍO FROTA | AM | https://www.amazonasleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| Borges Guedes Neto | TO | https://www.mgrleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| GUILHERME DE ARAÚJO DOMINGOS | PR | https://www.gdleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| ELTON LUIZ SIMON | PR | https://www.simonleiloes.com.br/ | high | 200 | hybrid | nan | 0 | ⚠ |
| MATIAS SCHEID | RS | http://www.scheidleiloes.com.br | medium | 200 | static | https://leilao.scheidleiloes.com.br/assinar-newsletter | 0 | ⚠ |
| CLEVER ELMES MILANI | PR | https://www.milanileiloes.com.br/ | high | 200 | dynamic | nan | 0 | ⚠ |
| Mouzar Baston Filho | DF | https://www.bastonleiloes.com.br/ | high | 200 | static | nan | 0 | ⚠ |
| EVANIO ALVES PEREIRA | RJ | https://www.evanioalvesleiloeiro.com.br | medium | 200 | static | http://www.evanioalvesleiloeiro.com.br/catalogo.asp?Num=614… | 0 | ⚠ |
| APARECIDA MARIA FIXER | PR | https://www.cidafixerleiloes.com.br | high | 200 | dynamic | https://www.cidafixerleiloes.com.br/index/mapa-imoveis?exib… | 0 | ⚠ |
| ANTONIO MAGNO JACOB DA ROCHA | PR | https://rochaleiloes.com.br/ | high | 200 | dynamic | nan | 0 | ⚠ |
| LEONARDO OLIVEIRA SALGUEIRO | RS | http://www.salgueiroleiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| Francisco Jonnathan Santos Freitas… | RN | https://www.nortenordesteleiloes.com.br | high | 200 | dynamic | https://franciscofreitasleiloes.com.br/index/mapa-imoveis?e… | 0 | ⚠ |
| ANDRÉ ANTONIO FAUTH | RS | http://www.fauthleiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| LEONARDO LOPES TIRLONI | RS | http://www.tirlonileiloes.com.br | high | 200 | hybrid | nan | 0 | ⚠ |
| AFONSO MARANGONI | PR | https://www.marangonileiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| CLEBER CARDOSO PEREIRA | MT | https://www.clebercardosoleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| BRÁULIO FERREIRA NETO | DF | http://braunaleiloes.blogspot.com.br | medium | 200 | static | nan | 0 | ⚠ |
| JOSIANE NUNES SCHWEC PINOTTI | RS | http://www.npleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| MARIA APARECIDA DE FREITAS FUZO | DF | https://www.leiloescentrooeste.com.br | high | 200 | dynamic | https://www.leiloescentrooeste.com.br/index/mapa-imoveis?ex… | 0 | ⚠ |
| ANTÔNIO CARLOS FAUTH | RS | https://www.fauthleiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| MARIA APARECIDA DE FREITAR FUZO | DF | https://www.leiloescentrooeste.com.br | high | 200 | dynamic | https://www.leiloescentrooeste.com.br/index/mapa-imoveis?ex… | 0 | ⚠ |
| RODRIGO APARECIDO RIGOLON DA SILVA | DF | https://www.rigolonleiloes.com.br/ | high | 200 | dynamic | nan | 0 | ⚠ |
| BRUNO HENRIQUE LOPES | DF | https://www.brunoleiloes.com.br | high | 200 | dynamic | https://www.brunoleiloes.com.br/index/mapa-imoveis?exibeMap… | 0 | ⚠ |
| DANIEL OLIVEIRA JUNIOR | DF | https://www.danieloliveiraleiloes.com.br | high | 200 | dynamic | https://doleiloes.com.br/index/mapa-imoveis?exibeMapa=1 | 0 | ⚠ |
| FÁBIO MANOEL GUIMARÍES | DF | https://www.fabioleiloes.com.br | high | 200 | dynamic | https://www.fabioleiloes.com.br/index/mapa-imoveis?exibeMap… | 0 | ⚠ |
| LUIZ UBIRATÍ DE CARVALHO | DF | https://www.luizleiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| CELSO LUIS KOCH LAZZARI | RS | http://www.agenciadeleiloes.lel.br | high | 200 | static | nan | 0 | ⚠ |
| ANTONIO HISSAO SATO JUNIOR | DF | https://www.satoleiloes.com.br | medium | 200 | unknown | nan | 0 | ⚠ |
| João Rodrigues de Camargo Junior | SP | https://www.camargoleiloes.com.br/proxi… | high | 200 | hybrid | nan | 0 | ⚠ |
| Antônio Carlos Celso Santos Frazão | MT | https://www.sfrazao.com.br/ | high | 200 | static | nan | 0 | ⚠ |
| FERNANDO PELLONI BARROS DA SILVEINA | DF | https://www.casaamarelaleiloes.net.br | high | 200 | dynamic | http://www.casaamarelaleiloes.net.br/leilao.asp?Num=61179 | 0 | ⚠ |
| ALEXANDRE WEYH | RS | http://www.awleiloes.com.br | medium | 200 | static | http://leiloes.watchtrade.com.br/catalogo.asp?Num=61385 | 0 | ⚠ |
| EUCÉLIA MADALENA DE SOUZA | DF | https://www.upleiloes.com.br | medium | 200 | unknown | nan | 0 | ⚠ |
| ADEMIR MIGUEL CORRÊA | RS | http://www.correleiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| Victor Alberto Severino Frazão | MT | https://www.sfrazao.com.br | high | 200 | static | nan | 0 | ⚠ |
| Icaro Alexandre Felfili Jardim | MT | https://www.globoleiloes.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| LUIZ EDUARDO GOMES: | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| PAULO ALEXANDRE HEISLER | DF | https://www.bidgo.com.br | high | 200 | static | nan | 0 | ⚠ |
| RAFAEL BRAMBILA PEIXOTO | SP | https://www.peixotoleiloes.com.br/ | high | 200 | dynamic | nan | 0 | ⚠ |
| JORGE VINÍCIUS DE MOURA CORRÊA: | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| Luiz Balbino da Silva | MT | https://www.balbinoleiloes.com.br | medium | 200 | dynamic | nan | 0 | ⚠ |
| FERNANDO RODRIGUES BENVENHO: | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| FABIO PRANDO FAGUNDES GOES | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| VALDOMIRO BIS | RS | http://www.bisleiloeiro.com.br | high | 200 | static | nan | 0 | ⚠ |
| IRANI FLORES | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| Marciano Mauro Pagliarini | SC | https://www.eckertleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| ADRIANO DE SOUZA CARDOSO | DF | https://www.capitalleiloes.com.br/ | medium | 200 | static | nan | 0 | ⚠ |
| RODRIGO APARECIDO RIGOLON DA SILVA | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| BRUNO FERNANDO MEIRELES CARDOSO | RS | http://www.meirelesleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| José Gonçalves Abrantes Filho | PB | https://www.abrantesleiloes.com | medium | 200 | static | nan | 0 | ⚠ |
| Renato Guedes Rocha | MG | https://www.rioleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| EDUARDO SCHMITZ | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| William Wellington Pimenta | MG | https://www.williamleiloeiro.com.br | medium | 200 | static | nan | 0 | ⚠ |
| ARTHUR FERREIRA DE OLIVEIRA | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| DENISE ARAÚJO DOS SANTOS | DF | https://dearaujoleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| OTAVIO LAURO SODRE SANTORO | DF | https://www.sodresantoro.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| Wellington de Matos Silva | MG | https://www.wsleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| Giovana Norma Bólico ( MATRÍCULA S… | MG | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| MARCO TULIO MONTENEGRO CAVALCANTI … | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| Paulo Cezar Rocha Texeira | SE | https://www.leiloesjudiciaisbahia.com.b… | high | 200 | dynamic | https://www.leiloesjudiciaisbahia.com.br/index/mapa-imoveis… | 0 | ⚠ |
| Vítor Calab Nunes | MG | https://www.vitorcalableiloeiro.com.br | medium | 200 | static | nan | 0 | ⚠ |
| WESLEY OLIVEIRA ASCANIO | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| FERNANDO GUSTAVO ALENCAR DE ALBUQU… | AL | http://www.albuquerquelins.com.br | medium | 200 | static | nan | 0 | ⚠ |
| ANTONIO CARLOS CELSO SANTOS FRAZAO | MT | https://www.sfrazao.com.br/ | high | 200 | static | nan | 0 | ⚠ |
| ROBERTA CRISTINA REZENDE DE ALBUQU… | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| GUSTAVO BOLZAN | ES | https://www.gbleiloes.com.br/ | high | 200 | hybrid | nan | 0 | ⚠ |
| MAYSALA SOARES DE SOUZA PEIXOTO | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| Bruno Barreto Sanches | MT | https://www.barretoleiloes.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| VILMAR BERTONCELLO | RS | https://www.agenciadeleiloes.lel.br | high | 200 | static | nan | 0 | ⚠ |
| ULISSES DONIZETE RAMOS | GO | https://www.casamartillo.com.br | high | 200 | static | nan | 0 | ⚠ |
| Rafael Araújo Gomes | MG | https://www.rafaelleiloeiro.com.br | medium | 200 | static | https://comprei.pgfn.gov.br/anuncio/detalhe/46480 | 0 | ⚠ |
| Vinicius Santos Ciriaco | MT | https://www.vincileiloes.com.br/ | medium | 200 | static | nan | 0 | ⚠ |
| VERÔNICA TELLES ARAÚJO SILVA SOARES | RS | https://veronicaleiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| DJANIR DA RÓS | ES | https://www.djanirleiloes.com.br | medium | 200 | static | nan | 0 | ⚠ |
| Vanderlia de Assis Carvalho Freitas | MG | https://www.globoleiloes.com.br/ | medium | 200 | dynamic | nan | 0 | ⚠ |
| Patricia Graciele de Andrade Sousa | MG | https://www.patricialeiloeira.com.br | high | 200 | dynamic | nan | 0 | ⚠ |
| Joabe Balbino da Silva | MT | https://www.balbinoleiloes.com.br/ | medium | 200 | dynamic | nan | 0 | ⚠ |
| EDUARDO CONSENTINO | SP | https://www.biasileiloes.com.br | high | 200 | static | nan | 0 | ⚠ |
| Mozar Miranda Almeida | MG | https://www.mozarleiloeseimoveis.com.br | high | 200 | static | nan | 0 | ⚠ |
| Adilson Bento de Araújo | SE | https://www.abaleiloes.com.br/ | medium | 500 | dynamic | nan | 0 | ⚠ |

</details>
