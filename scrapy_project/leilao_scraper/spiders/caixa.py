"""Spider para o portal oficial Caixa Econômica Federal.

Cobre `venda-imoveis.caixa.gov.br/sistema/busca-imovel.asp`. Após recon
do fluxo XHR real, descobrimos que o form multi-step do site é apenas
gating de UI — os endpoints internos aceitam POST direto desde que
tenham cookies de sessão válidos (SIMOV + ASPSESSION + __uzm*).

Fluxo:
  1. **Sessão Playwright (1× por UF × modalidade)**: navega para
     `busca-imovel.asp`, aguarda Radware liberar (cookies SIMOV +
     __uzm* ficam armazenados), depois chama `carregaPesquisaImoveis`
     diretamente via `page.evaluate()` — bypassa o wizard step 3
     (CPF/LGPD, que é só pra cadastro de arrematante).
  2. **Resposta de carregaPesquisaImoveis.asp**: HTML com hidden inputs
     `<input id='hdnImov1' value='ID||ID||...||ID'>` agrupando IDs por
     página (10 imóveis cada).
  3. **Para cada hdnImov<N>**: POST direto a `carregaListaImoveis.asp`
     com `hdnImov=ID||ID||...` → HTML com cards
     `<a href='detalhe-imovel.asp?hdnimovel=N'>`.
  4. **Para cada `hdnimovel`**: GET `detalhe-imovel.asp?hdnimovel=N` →
     parse_property (existente).

Modalidades cobertas (cmb_modalidade value → descrição):
  14 — Leilão SFI - Edital Único        (extrajudicial_lei_9514, 1ª/2ª)
  21 — Licitação Aberta                  (extrajudicial_outro)
  30 — Exercício de Direito de Preferência (extrajudicial_outro)
  33 — Venda Online                      (extrajudicial_outro / venda direta)
  34 — Venda Direta Online               (extrajudicial_outro / venda direta)

Default: varre TODAS modalidades em SP, RJ, MG, RS, DF. Override:
`scrapy crawl caixa -a estados=SP,RJ -a modalidades=14`.

Provider slug: `caixa`. Pipeline classifica `source_kind='bank'` (ver
`pipelines_supabase.BANK_PROVIDERS`).
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import scrapy
from scrapy_playwright.page import PageMethod

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders._playwright_settings import PLAYWRIGHT_CUSTOM_SETTINGS
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _detail_is_imovel,
    _normalize_text,
    _parse_auction_clauses,
)


_BASE = "https://venda-imoveis.caixa.gov.br/sistema"
_BUSCA_URL = f"{_BASE}/busca-imovel.asp?sltTipoBusca=imoveis"
_DEFAULT_STATES = ("SP", "RJ", "MG", "RS", "DF")
_DEFAULT_MODALIDADES = (
    ("14", "Leilão SFI - Edital Único"),
    ("21", "Licitação Aberta"),
    ("33", "Venda Online"),
    ("34", "Venda Direta Online"),
)

# Detail link no card vem como onclick='detalhe_imovel(NNN)' (não href direto).
# Aceitamos ambos os formatos pra cobrir variações futuras.
_DETAIL_HREF_RE = re.compile(
    r"(?:detalhe_imovel\(|detalhe-imovel\.asp\?hdnimovel=)(\d+)", re.I
)
_HDN_IMOV_RE = re.compile(
    r"id=['\"]hdnImov(\d+)['\"]\s+value=['\"]([^'\"]+)['\"]", re.I
)
_MATRICULA_RE = re.compile(r"matr[íi]cula\s*(?:n[º°.]?\s*)?(\d{1,7})", re.I)

# Endereço composto Caixa: "RUA NOME,N. 236 APTO. 03 TR 01, BAIRRO - CEP: 05731-370, CIDADE - ESTADO"
_ADDRESS_FULL_RE = re.compile(
    r"([A-ZÀ-Ú][A-ZÀ-Ú0-9.\s]+?)\s*,\s*N[.°º]?\s*(\d+)\s*([^,]*?),\s*"
    r"([A-ZÀ-Ú][A-ZÀ-Ú0-9\s.]+?)\s*-\s*CEP:\s*(\d{5}-?\d{3})\s*,\s*"
    r"([A-ZÀ-Ú][A-ZÀ-Ú\s]+?)\s*-\s*([A-ZÀ-Ú\s]+?)(?:\s|$)",
    re.I,
)

# Caixa hospeda fotos em URL determinística:
#   https://venda-imoveis.caixa.gov.br/fotos/F<lot_id><NN>.jpg
# onde lot_id é o hdnimovel (14 dígitos) e NN começa em 21 para a 1ª foto.
_PHOTO_BASE = "https://venda-imoveis.caixa.gov.br/fotos"
_PHOTO_MAX_PROBE = 50   # NN máximo a sondar (21..70 — corte em 50 absoluto)
_PHOTO_FAIL_STOP = 5    # para após N falhas consecutivas

# PDFs determinísticos (matrícula, edital, laudo)
_PDF_BASE = "https://venda-imoveis.caixa.gov.br/editais"


def _caixa_probe_images(lot_id: str, cookie_dict: dict, ua: str,
                         max_probe: int = _PHOTO_MAX_PROBE) -> list[str]:
    """Sonda URLs F<lot_id>NN.jpg começando em NN=21 até max_probe.
    Para após `_PHOTO_FAIL_STOP` falhas consecutivas. Retorna URLs que
    responderam HTTP 200."""
    import httpx
    urls: list[str] = []
    fails = 0
    headers = {
        "User-Agent": ua,
        "Referer": "https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.asp",
        "Accept": "image/avif,image/webp,*/*",
    }
    with httpx.Client(cookies=cookie_dict, headers=headers, timeout=10) as cli:
        for nn in range(21, 21 + max_probe):
            url = f"{_PHOTO_BASE}/F{lot_id}{nn}.jpg"
            try:
                r = cli.head(url, follow_redirects=False)
            except Exception:
                fails += 1
                if fails >= _PHOTO_FAIL_STOP:
                    break
                continue
            if r.status_code == 200:
                urls.append(url)
                fails = 0
            else:
                fails += 1
                if fails >= _PHOTO_FAIL_STOP:
                    break
    return urls


def _norm_city(s: str) -> str:
    """Normaliza nome de cidade para match no dropdown Caixa:
    uppercase, sem acentos, sem espaços extras. 'São Paulo' → 'SAO PAULO'."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s.strip().upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


# Estado por extenso → sigla UF (Caixa publica "SAO PAULO - SAO PAULO" no
# endereço; o último é o estado por extenso). Match case-insensitive +
# sem acentos via _norm_city.
_NOME_TO_UF: dict[str, str] = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM",
    "BAHIA": "BA", "CEARA": "CE", "DISTRITO FEDERAL": "DF",
    "ESPIRITO SANTO": "ES", "GOIAS": "GO", "MARANHAO": "MA",
    "MATO GROSSO": "MT", "MATO GROSSO DO SUL": "MS", "MINAS GERAIS": "MG",
    "PARA": "PA", "PARAIBA": "PB", "PARANA": "PR", "PERNAMBUCO": "PE",
    "PIAUI": "PI", "RIO DE JANEIRO": "RJ", "RIO GRANDE DO NORTE": "RN",
    "RIO GRANDE DO SUL": "RS", "RONDONIA": "RO", "RORAIMA": "RR",
    "SANTA CATARINA": "SC", "SAO PAULO": "SP", "SERGIPE": "SE",
    "TOCANTINS": "TO",
}

# UA realista — Chromium do scrapy-playwright e Radware esperam mesmo
# UA do navegador automatizado, senão fingerprint diverge dos cookies.
# Versão unificada em _common_ua.py (Chrome 122 estável).
from leilao_scraper.spiders._common_ua import BROWSER_USER_AGENT as _BROWSER_UA


class CaixaSpider(ProviderSpider):
    name = "caixa"
    provider_slug = "caixa"
    auctioneer_slug = "caixa"
    requires_playwright = True

    custom_settings = {
        **PLAYWRIGHT_CUSTOM_SETTINGS,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
        "DOWNLOAD_DELAY": 0.5,
        "PLAYWRIGHT_MAX_PAGES_PER_CONTEXT": 6,
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 60_000,
        "USER_AGENT": _BROWSER_UA,
    }

    MAX_LOTS_PER_RUN = 50000

    def __init__(self, *args, estados: str | None = None,
                 modalidades: str | None = None,
                 cidades: str | None = None,
                 auto_cidades: str | None = None,
                 refazer_sem_data: str | None = None, **kwargs):
        """Argumentos:
          estados      CSV de UFs (default: 5 maiores).
          modalidades  CSV de cmb_modalidade values (default: as 4 ativas).
          cidades      CSV de NOMES de cidades (ex: 'SAO PAULO,RIO DE JANEIRO').
                       Match case-insensitive sem acentos contra textContent
                       de <option> no select cmb_cidade. Quando fornecido,
                       segmenta a busca por cidade — supera o cap servidor
                       de ~1410 IDs por (UF × mod) e popula municipality_name
                       direto no address. Sem ele, busca a UF inteira sem
                       segmentação.

                       Nota: o site Caixa usa código interno (ex: '9859'
                       p/ SP capital), NÃO o IBGE. Resolvemos no spider
                       por lookup do label. O IBGE 7-dígitos pode ser
                       preenchido depois via match em core.municipality
                       (name+uf).
        """
        super().__init__(*args, **kwargs)
        self._yielded = 0
        self._seen_lot_ids: set[str] = set()
        self._estados: list[str] = []
        if estados:
            self._estados = [s.strip().upper() for s in estados.split(",") if s.strip()]
        if not self._estados:
            self._estados = list(_DEFAULT_STATES)
        self._modalidades: list[tuple[str, str]] = []
        if modalidades:
            wanted = {s.strip() for s in modalidades.split(",") if s.strip()}
            self._modalidades = [(v, lbl) for v, lbl in _DEFAULT_MODALIDADES if v in wanted]
        if not self._modalidades:
            self._modalidades = list(_DEFAULT_MODALIDADES)
        # Cidades opcionais — nomes (lookup do CEF code dinamicamente no spider).
        self._cidades_nomes: list[str] = []
        if cidades:
            self._cidades_nomes = [_norm_city(c) for c in cidades.split(",") if c.strip()]
        # auto_cidades: quando true, descobre todas as cidades por UF via
        # dropdown carregaListaCidades.asp e itera. Cuidado: pode gerar
        # milhares de buscas (1000+ cidades × N modalidades).
        self._auto_cidades = (auto_cidades or "").lower() in {"1", "true", "yes"}
        if self._auto_cidades and self._cidades_nomes:
            self.logger.warning(
                "Caixa: auto_cidades=true ignora arg cidades (mutuamente exclusivos)."
            )
            self._cidades_nomes = []
        self._refazer_sem_data = (refazer_sem_data or "").lower() in {"1", "true", "yes"}
        self.logger.info(
            f"Caixa: estados={self._estados} "
            f"modalidades={[v for v,_ in self._modalidades]} "
            f"cidades={self._cidades_nomes or ('AUTO' if self._auto_cidades else '<UF inteira>')} "
            f"refazer_sem_data={self._refazer_sem_data}"
        )

    # ------------------------------------------------------------------
    # Nível 1: Playwright bootstrap por (UF × modalidade × cidade?)
    # ------------------------------------------------------------------
    def start_requests(self) -> Iterable[Any]:
        # Modo 0: refazer_sem_data=true → query DB pra lots Caixa sem
        # auction_round, GET direto em cada detail URL via Playwright.
        if self._refazer_sem_data:
            yield from self._start_refazer()
            return

        # Modo 1: auto_cidades=true → primeira passada descobre cidades por
        # UF via dropdown; depois enfileira (UF × cidade × modalidade).
        if self._auto_cidades:
            for uf in self._estados:
                yield scrapy.Request(
                    _BUSCA_URL,
                    callback=self.parse_cidades_discover,
                    meta={
                        "playwright": True,
                        "playwright_include_page": True,
                        "estado_uf": uf,
                        "playwright_page_methods": [
                            PageMethod("wait_for_selector", "select#cmb_estado",
                                       timeout=30_000),
                            PageMethod("wait_for_timeout", 5000),  # Radware
                        ],
                    },
                    dont_filter=True,
                )
            return

        # Modo 2: cidades explícitas (passadas via -a) OU UF inteira (default).
        cidades = self._cidades_nomes or [""]
        for uf in self._estados:
            for mod_val, mod_label in self._modalidades:
                for cidade_nome_norm in cidades:
                    yield scrapy.Request(
                        _BUSCA_URL,
                        callback=self.parse_search_bootstrap,
                        meta={
                            "playwright": True,
                            "playwright_include_page": True,
                            "estado_uf": uf,
                            "modalidade_val": mod_val,
                            "modalidade_label": mod_label,
                            "cidade_nome_norm": cidade_nome_norm,
                            "playwright_page_methods": [
                                PageMethod("wait_for_selector", "select#cmb_estado",
                                           timeout=30_000),
                                PageMethod("wait_for_timeout", 5000),  # Radware
                            ],
                        },
                        dont_filter=True,
                    )

    async def parse_cidades_discover(self, response: scrapy.http.Response):
        """Descobre todas as cidades da UF lendo o dropdown carregaListaCidades.
        Para cada cidade, enfileira parse_search_bootstrap em todas as modalidades."""
        page = response.meta.get("playwright_page")
        uf = response.meta["estado_uf"]
        if page is None:
            return
        try:
            await page.select_option("select[name='cmb_estado']", uf)
            await page.wait_for_timeout(4000)
            await page.wait_for_function(
                "() => document.querySelector('select[name=cmb_cidade]').options.length > 1",
                timeout=15000,
            )
            cidades = await page.eval_on_selector_all(
                "select[name='cmb_cidade'] option",
                "els => els.filter(o => o.value && o.value !== '0' && o.value !== '')"
                ".map(o => o.textContent.trim())",
            )
        finally:
            try:
                await page.close()
            except Exception:
                pass
        cidades_norm = [_norm_city(c) for c in cidades if c]
        self.log_event("caixa_cidades_discovered", uf=uf, total=len(cidades_norm))
        for cidade_nome_norm in cidades_norm:
            for mod_val, mod_label in self._modalidades:
                yield scrapy.Request(
                    _BUSCA_URL,
                    callback=self.parse_search_bootstrap,
                    meta={
                        "playwright": True,
                        "playwright_include_page": True,
                        "estado_uf": uf,
                        "modalidade_val": mod_val,
                        "modalidade_label": mod_label,
                        "cidade_nome_norm": cidade_nome_norm,
                        "playwright_page_methods": [
                            PageMethod("wait_for_selector", "select#cmb_estado",
                                       timeout=30_000),
                            PageMethod("wait_for_timeout", 5000),
                        ],
                    },
                    dont_filter=True,
                )

    def _start_refazer(self) -> Iterable[Any]:
        """Modo refazer_sem_data: query DB pra lots Caixa sem
        auction_round, dispatcha Playwright GET direto em cada detail
        URL. parse_property já corrigido extrai datas+min_bid; pipeline
        _insert_round persiste o round faltante.
        """
        import os
        import psycopg

        db_url = os.environ.get("SUPABASE_DB_URL")
        if not db_url:
            self.logger.error("SUPABASE_DB_URL não definida")
            return
        urls: list[str] = []
        with psycopg.connect(db_url, sslmode="require") as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT al.source_url
                FROM core.auction_lot al
                JOIN core.source s ON s.id = al.source_id
                WHERE s.short_name LIKE %s
                  AND NOT EXISTS (SELECT 1 FROM core.auction_round r WHERE r.lot_id = al.id)
                ORDER BY al.created_at
                LIMIT %s
                """,
                ("%caixa%", self.MAX_LOTS_PER_RUN),
            )
            urls = [r[0] for r in cur.fetchall() if r[0]]
        self.logger.info(f"Caixa refazer_sem_data: {len(urls)} lots a re-extrair")
        self.log_event("caixa_refazer_inicio", total=len(urls))

        lot_id_re = re.compile(r"hdnimovel=(\d+)")
        for u in urls:
            m = lot_id_re.search(u)
            lot_id = m.group(1) if m else u.rsplit("=", 1)[-1]
            yield scrapy.Request(
                u,
                callback=self.parse_property,
                meta={
                    "playwright": True,
                    "playwright_page_methods": [
                        PageMethod("wait_for_selector", "body", timeout=30_000),
                        PageMethod("wait_for_timeout", 4000),
                    ],
                    "estado_uf": None,
                    "cidade_nome": None,
                    "modalidade_label": "",
                    "source_lot_code": f"caixa-{lot_id}",
                    "source_listing_url": "refazer-sem-data",
                    "cookie_dict": {},
                    "dont_obey_robotstxt": True,
                },
                dont_filter=True,
            )

    async def parse_search_bootstrap(self, response: scrapy.http.Response):
        """Roda no Playwright. Seta UF + Modalidade (+ Cidade quando
        meta tem cidade_ibge), chama carregaPesquisaImoveis() via
        evaluate, captura HTML do response XHR (com hdnImov<N>).
        Encerra Playwright, persiste cookies em meta para próximos
        requests Scrapy.

        Quando cidade_ibge != "":
          1. Seleciona UF → site dispara carregaListaCidades.asp
             automaticamente (popular dropdown cmb_cidade)
          2. Aguarda o select cmb_cidade ter options da UF
          3. Seleciona cidade pelo IBGE code (value do <option>)
          4. Chama carregaPesquisaImoveis(cidade_ibge, [], modalidade)
        """
        page = response.meta.get("playwright_page")
        uf = response.meta["estado_uf"]
        mod_val = response.meta["modalidade_val"]
        mod_label = response.meta["modalidade_label"]
        cidade_nome_norm = response.meta.get("cidade_nome_norm", "") or ""
        cidade_cef: str = ""    # código interno do site
        cidade_nome: str | None = None

        if page is None:
            self.logger.warning("Caixa: Playwright page indisponível")
            return

        try:
            search_html_holder: dict[str, str] = {}

            async def on_response(resp):
                if "carregaPesquisaImoveis.asp" in resp.url:
                    try:
                        text = await resp.text()
                        search_html_holder["body"] = text
                        search_html_holder["status"] = str(resp.status)
                    except Exception as e:
                        self.logger.warning(f"Caixa: capture XHR err: {e}")

            page.on("response", on_response)

            await page.select_option("select[name='cmb_estado']", uf)
            await page.wait_for_timeout(2500)  # site dispara carregaListaCidades
            await page.select_option("select[name='cmb_modalidade']", mod_val)
            await page.wait_for_timeout(1000)

            if cidade_nome_norm:
                # Aguarda o select cmb_cidade ter options da UF, então
                # match pelo texto normalizado pra obter o CEF code.
                try:
                    await page.wait_for_function(
                        "() => document.querySelector('select[name=cmb_cidade]')"
                        ".options.length > 1",
                        timeout=15000,
                    )
                    # Resolve nome → CEF code via JS no contexto da página.
                    cef_info = await page.evaluate(
                        """(target) => {
                          const norm = (s) => s.normalize('NFKD').replace(/[\\u0300-\\u036f]/g, '').toUpperCase().trim();
                          const sel = document.querySelector('select[name=cmb_cidade]');
                          for (const o of sel.options) {
                            if (norm(o.textContent) === target) {
                              return { val: o.value, txt: o.textContent.trim() };
                            }
                          }
                          return null;
                        }""",
                        cidade_nome_norm,
                    )
                    if cef_info:
                        cidade_cef = cef_info["val"]
                        cidade_nome = cef_info["txt"]
                        await page.select_option("select[name='cmb_cidade']", cidade_cef)
                        await page.wait_for_timeout(1500)
                    else:
                        self.logger.warning(
                            f"Caixa: cidade '{cidade_nome_norm}' não está no dropdown de UF={uf}"
                        )
                        return  # skip esse (UF, cidade, mod)
                except Exception as e:
                    self.logger.warning(
                        f"Caixa: erro ao buscar cidade '{cidade_nome_norm}' em UF={uf}: {e}"
                    )
                    return

            await page.evaluate(
                "(cidade) => { $('#hdn_estado').val($('#cmb_estado :selected').val());"
                "  carregaPesquisaImoveis(cidade, [], $('#cmb_modalidade :selected').val()); }",
                cidade_cef,
            )
            # Aguarda XHR retornar (até 20s).
            for _ in range(40):
                if "body" in search_html_holder:
                    break
                await page.wait_for_timeout(500)

            # Extrai cookies do contexto.
            cookies = await page.context.cookies()
            cookie_dict = {
                c["name"]: c["value"]
                for c in cookies
                if "caixa.gov.br" in c.get("domain", "")
            }
        finally:
            try:
                await page.close()
            except Exception:
                pass

        body = search_html_holder.get("body", "")
        if not body or "hdnImov" not in body:
            self.log_event(
                "caixa_search_empty",
                uf=uf, modalidade=mod_label,
                cidade_cef=cidade_cef, cidade_nome=cidade_nome,
                status=search_html_holder.get("status"),
                preview=body[:200],
            )
            return

        # Parse páginas de IDs.
        pages = list(_HDN_IMOV_RE.finditer(body))
        self.log_event(
            "caixa_search_done", uf=uf, modalidade=mod_label,
            cidade_cef=cidade_cef, cidade_nome=cidade_nome,
            pages=len(pages),
            total_ids=sum(len(m.group(2).split("||")) for m in pages),
        )
        for m in pages:
            page_num = m.group(1)
            ids_str = m.group(2).strip().strip("|")
            if not ids_str:
                continue
            yield scrapy.FormRequest(
                f"{_BASE}/carregaListaImoveis.asp",
                formdata={"hdnImov": ids_str},
                callback=self.parse_lista_imoveis,
                cookies=cookie_dict,
                headers={
                    "User-Agent": _BROWSER_UA,
                    "Origin": "https://venda-imoveis.caixa.gov.br",
                    "Referer": _BUSCA_URL,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "*/*",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                },
                meta={
                    "playwright": False,
                    "estado_uf": uf,
                    "modalidade_label": mod_label,
                    "cidade_cef": cidade_cef,
                    "cidade_nome": cidade_nome,
                    "page_num": page_num,
                    "cookie_dict": cookie_dict,
                    "dont_obey_robotstxt": True,
                },
                dont_filter=True,
            )

    # ------------------------------------------------------------------
    # Nível 2: parse cards de uma página de listagem
    # ------------------------------------------------------------------
    def parse_lista_imoveis(self, response: scrapy.http.Response) -> Iterable[Any]:
        uf = response.meta["estado_uf"]
        mod_label = response.meta["modalidade_label"]
        page_num = response.meta["page_num"]
        cookie_dict = response.meta["cookie_dict"]
        body = response.text

        kept = 0
        for m in _DETAIL_HREF_RE.finditer(body):
            lot_id = m.group(1)
            if lot_id in self._seen_lot_ids:
                continue
            self._seen_lot_ids.add(lot_id)
            if self._yielded >= self.MAX_LOTS_PER_RUN:
                self.log_event("caixa_max_lots_hit", yielded=self._yielded)
                return
            self._yielded += 1
            kept += 1
            detail_url = f"{_BASE}/detalhe-imovel.asp?hdnimovel={lot_id}"
            # Radware bloqueia GET direto mesmo com cookies SIMOV. Tem
            # que ir via Playwright (cada request resolve o challenge
            # sozinho — overhead ~3-5s por lote).
            yield scrapy.Request(
                detail_url,
                callback=self.parse_property,
                cookies=cookie_dict,
                headers={
                    "User-Agent": _BROWSER_UA,
                    "Referer": _BUSCA_URL,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                },
                meta={
                    "playwright": True,
                    "playwright_page_methods": [
                        PageMethod("wait_for_selector", "body", timeout=30_000),
                        PageMethod("wait_for_timeout", 4000),
                    ],
                    "estado_uf": uf,
                    "modalidade_label": mod_label,
                    "cidade_cef": response.meta.get("cidade_cef", ""),
                    "cidade_nome": response.meta.get("cidade_nome"),
                    "source_lot_code": f"caixa-{lot_id}",
                    "source_listing_url": response.url,
                    "dont_obey_robotstxt": True,
                },
            )
        self.log_event(
            "caixa_lista_done", uf=uf, modalidade=mod_label,
            page=page_num, kept=kept,
        )

    # ------------------------------------------------------------------
    # Nível 3: parse do detalhe (mantido do scaffold original)
    # ------------------------------------------------------------------
    def parse_property(self, response: scrapy.http.Response):
        body_text = _normalize_text(" ".join(response.css("body *::text").getall()))
        h1 = (response.css("h1::text").get() or "").strip()
        og_title = response.css("meta[property='og:title']::attr(content)").get() or h1

        sample = h1 + " " + body_text[:3000]
        if not _detail_is_imovel(og_title or h1 or "imóvel Caixa", sample):
            self.log_event("caixa_lote_dropped_non_imovel", url=response.url)
            return

        loader = self.new_loader(response)
        loader.replace_value("auctioneer", "caixa")
        loader.add_value("source_lot_code", response.meta.get("source_lot_code"))

        title_text = h1 or og_title or ""
        if not title_text:
            title_text = (
                response.css("h3::text, .titulo::text, h5::text").get() or ""
            ).strip()
        if title_text:
            loader.add_value("title", title_text[:300])

        # Descrição — Caixa serve o trecho real dentro de
        # "<strong>Descrição:</strong> ... </p>", entre o label e o fim
        # do parágrafo. Os selectors antigos pegavam o body inteiro
        # (menu+footer+scripts), poluindo description e inflando
        # falsamente o trigger SQL extract_creditors.
        raw_html = response.text
        m_desc = re.search(
            r"<strong>\s*Descri[çc][ãa]o\s*:?\s*</strong>(.*?)</p>",
            raw_html, re.S | re.I,
        )
        desc = ""
        if m_desc:
            # Remove tags HTML residuais (<br>, <i>, &nbsp;, etc.)
            inner = re.sub(r"<[^>]+>", " ", m_desc.group(1))
            inner = inner.replace("&nbsp;", " ").replace("\xa0", " ")
            desc = _normalize_text(inner)
        # Sempre prefixa "Comitente: Caixa Econômica Federal." para que o
        # trigger SQL extract_creditors popule core.party_role_in_auction
        # — mesmo quando a description original é vazia.
        if desc:
            desc = f"Comitente: Caixa Econômica Federal. {desc}"
        else:
            desc = "Comitente: Caixa Econômica Federal."
        loader.add_value("description", desc[:10000])

        # Modalidade textual no body
        modalidade_raw = response.meta.get("modalidade_label", "") or ""
        for label in ("Modalidade de venda", "Tipo de leilão", "Tipo de venda", "Situação"):
            m = re.search(rf"{re.escape(label)}\s*:?\s*([A-Za-zÀ-ú0-9°º\s/-]+?)(?:\n|<|R\$|$)",
                          body_text, re.I)
            if m and not modalidade_raw:
                modalidade_raw = m.group(1).strip()
                break

        modalidade_lower = modalidade_raw.lower()
        if any(k in modalidade_lower for k in ("encerrad", "finalizad", "vendido")):
            status = "desconhecido"
        else:
            status = "aberto"
        loader.add_value("status", status)

        if "1º" in modalidade_raw or "1°" in modalidade_raw or "1 leilão" in modalidade_lower:
            loader.add_value("auction_phase", "1a_praca")
        elif "2º" in modalidade_raw or "2°" in modalidade_raw or "2 leilão" in modalidade_lower:
            loader.add_value("auction_phase", "2a_praca")
        elif "venda" in modalidade_lower:
            loader.add_value("auction_phase", "unica")

        # Datas das praças — Caixa serve em "Data do 1º Leilão - DD/MM/YYYY - HHhMM".
        # O `h` em HHhMM é literal (não dois-pontos). Normalizamos para HH:MM.
        m_1a = re.search(
            r"Data\s+do\s+1[ºoº°ª]\s*Leil[ãa]o\s*[-–]\s*"
            r"(\d{2}/\d{2}/\d{4})\s*[-–]\s*(\d{1,2})h(\d{2})",
            body_text, re.I,
        )
        if m_1a:
            loader.add_value(
                "first_auction_date",
                f"{m_1a.group(1)} {m_1a.group(2).zfill(2)}:{m_1a.group(3)}",
            )
        m_2a = re.search(
            r"Data\s+do\s+2[ºoº°ª]\s*Leil[ãa]o\s*[-–]\s*"
            r"(\d{2}/\d{2}/\d{4})\s*[-–]\s*(\d{1,2})h(\d{2})",
            body_text, re.I,
        )
        if m_2a:
            loader.add_value(
                "second_auction_date",
                f"{m_2a.group(1)} {m_2a.group(2).zfill(2)}:{m_2a.group(3)}",
            )

        # Preço — Caixa exibe múltiplas estruturas
        m_av = re.search(
            r"(?:Valor\s+de\s+avalia[çc][ãa]o|Avalia[çc][ãa]o)[:\s]*R\$\s*([\d.,]+)",
            body_text, re.I,
        )
        if m_av:
            try:
                v = _brl_to_decimal(m_av.group(1))
                if v and v > 0:
                    loader.add_value("market_value", str(v))
            except Exception:
                pass

        # Lance mínimo — Caixa serve em 3 padrões distintos:
        #   "Valor mínimo de venda 1º Leilão: R$ 292.000,00"
        #   "Valor mínimo de venda 2º Leilão: R$ 175.200,00"
        #   "Valor para venda: R$ N" (venda direta — preço fixo único)
        # Preferimos 2º Leilão (menor; quando lote está em fase 2), depois
        # 1º Leilão, depois Venda Direta.
        m_min_2 = re.search(
            r"Valor\s+m[íi]nimo\s+de\s+venda\s+2[ºoº°ª]\s*Leil[ãa]o\s*:\s*R\$\s*([\d.,]+)",
            body_text, re.I,
        )
        m_min_1 = re.search(
            r"Valor\s+m[íi]nimo\s+de\s+venda\s+1[ºoº°ª]\s*Leil[ãa]o\s*:\s*R\$\s*([\d.,]+)",
            body_text, re.I,
        )
        m_min = (
            m_min_2
            or m_min_1
            or re.search(r"Valor\s+para\s+venda\s*:\s*R\$\s*([\d.,]+)", body_text, re.I)
            or re.search(r"Pelo\s+valor\s+de\s*:?\s*R\$\s*([\d.,]+)", body_text, re.I)
            or re.search(r"Pre[çc]o\s*:\s*R\$\s*([\d.,]+)", body_text, re.I)
        )
        if m_min:
            try:
                v = _brl_to_decimal(m_min.group(1))
                if v and v > 0:
                    loader.add_value("minimum_bid", str(v))
            except Exception:
                pass

        # auction_phase: refina baseado em quais valores estão presentes.
        # Se 2º Leilão tem valor, é 2ª praça; se só 1º, é 1ª praça.
        if m_min_2:
            loader.replace_value("auction_phase", "2a_praca")
        elif m_min_1 and not m_min_2:
            loader.replace_value("auction_phase", "1a_praca")

        # Endereço — Caixa serve uma linha composta:
        #   "RUA NOME,N. 236 APTO. 03 TR 01, BAIRRO - CEP: NNNNN-NNN, CIDADE - ESTADO"
        addr: dict[str, Any] = {"raw_text": title_text[:300]}
        uf_meta = response.meta.get("estado_uf")
        m_full = _ADDRESS_FULL_RE.search(body_text)
        if m_full:
            addr["street"] = m_full.group(1).strip()
            addr["number"] = m_full.group(2).strip()
            compl = m_full.group(3).strip()
            if compl:
                addr["complement"] = compl
            addr["neighborhood"] = m_full.group(4).strip()
            addr["zip"] = m_full.group(5)
            addr["municipality_name"] = m_full.group(6).strip().title()
            # group(7) é estado por extenso ("SAO PAULO"); use como fallback
            # de uf_meta quando não temos no meta (modo refazer_sem_data).
            if not uf_meta:
                uf_meta = _NOME_TO_UF.get(_norm_city(m_full.group(7)))
        else:
            # Fallback antigo regex linha-a-linha
            for label, key in (
                ("Endereço", "street"),
                ("Bairro", "neighborhood"),
                ("Cidade", "city"),
                ("UF", "uf"),
                ("CEP", "zip"),
            ):
                m = re.search(
                    rf"{label}\s*:?\s*([A-Za-zÀ-ú0-9°,.\s/-]+?)(?:\n|<|UF\s*:|CEP\s*:|Cidade\s*:|Bairro\s*:|$)",
                    body_text, re.I,
                )
                if m:
                    val = m.group(1).strip()
                    if val and len(val) < 200:
                        addr[key] = val
            if "city" in addr and "municipality_name" not in addr:
                addr["municipality_name"] = addr["city"]

        # Município/UF do meta tem prioridade sobre regex
        cidade_nome_meta = response.meta.get("cidade_nome") or ""
        if cidade_nome_meta:
            addr["municipality_name"] = cidade_nome_meta.title()
        if uf_meta:
            addr["uf"] = uf_meta
        elif not addr.get("uf"):
            # Fallback: tenta extrair UF/estado do body inteiro quando tudo falhou.
            # Caso comum: lotes do modo refazer_sem_data sem estado_uf no meta.
            for nome_estado, sigla in _NOME_TO_UF.items():
                if re.search(rf"\b{re.escape(nome_estado)}\b", _norm_city(body_text)):
                    uf_meta = sigla
                    addr["uf"] = sigla
                    break
            # Fallback adicional: CEP da página → UF pelo prefixo
            if not uf_meta:
                m_cep = re.search(r"CEP\s*:?\s*(\d{5}[-.]?\d{3})", body_text, re.I)
                if m_cep:
                    cep_num = re.sub(r"\D", "", m_cep.group(1))
                    prefix = cep_num[:2]
                    _CEP_UF_MAP = {
                        "01": "SP", "02": "SP", "03": "SP", "04": "SP", "05": "SP",
                        "06": "SP", "07": "SP", "08": "SP", "09": "SP", "10": "SP",
                        "11": "SP", "12": "SP", "13": "SP", "14": "SP", "15": "SP",
                        "16": "SP", "17": "SP", "18": "SP", "19": "SP",
                        "20": "RJ", "21": "RJ", "22": "RJ", "23": "RJ", "24": "RJ",
                        "25": "RJ", "26": "RJ", "27": "RJ", "28": "RJ", "29": "ES",
                        "30": "MG", "31": "MG", "32": "MG", "33": "MG", "34": "MG",
                        "35": "MG", "36": "MG", "37": "MG", "38": "MG", "39": "MG",
                        "40": "BA", "41": "BA", "42": "BA", "43": "BA", "44": "BA",
                        "45": "BA", "46": "BA", "47": "BA", "48": "BA", "49": "SE",
                        "50": "PE", "51": "PE", "52": "PE", "53": "PE", "54": "PE",
                        "55": "PE", "56": "PE", "57": "AL", "58": "PB", "59": "RN",
                        "60": "CE", "61": "CE", "62": "CE", "63": "CE", "64": "PI",
                        "65": "MA", "66": "PA", "67": "PA", "68": "PA", "69": "AM",
                        "70": "DF", "71": "DF", "72": "DF", "73": "DF",
                        "74": "GO", "75": "GO", "76": "GO", "77": "TO",
                        "78": "MT", "79": "MS",
                        "80": "PR", "81": "PR", "82": "PR", "83": "PR", "84": "PR",
                        "85": "PR", "86": "PR", "87": "PR", "88": "SC", "89": "SC",
                        "90": "RS", "91": "RS", "92": "RS", "93": "RS", "94": "RS",
                        "95": "RS", "96": "RS", "97": "RS", "98": "RS", "99": "RS",
                    }
                    uf_from_cep = _CEP_UF_MAP.get(prefix)
                    if uf_from_cep:
                        addr["uf"] = uf_from_cep
                        addr["zip"] = cep_num

        m_matr = _MATRICULA_RE.search(body_text)
        if m_matr:
            addr["registry_matricula"] = m_matr.group(1)
        if any(v for v in addr.values()):
            loader.add_value("address", addr)

        # ID real do lote (sem prefixo "caixa-")
        lot_id_real = (response.meta.get("source_lot_code") or "").replace("caixa-", "")

        # Imagens — Caixa hospeda em URL determinística F<lot_id>NN.jpg.
        # NN começa em 21 (1ª foto) e aumenta. Probe HEAD via cookies da
        # sessão (Radware só bloqueia GET HTML, não recursos estáticos).
        cookie_dict = response.meta.get("cookie_dict") or {}
        unique_imgs: list[str] = []
        if lot_id_real and cookie_dict:
            try:
                unique_imgs = _caixa_probe_images(lot_id_real, cookie_dict, _BROWSER_UA)
            except Exception as e:
                self.logger.warning(f"Caixa: probe images falhou {lot_id_real}: {e}")
        # Fallback: scrape <img> tags caso o probe falhe
        if not unique_imgs:
            img_urls = response.css(
                "img[src*='/fotos/F']::attr(src), "
                "img[src*='/sistema/galeria/']::attr(src), "
                "img[src*='/sistema/imagens/']::attr(src), "
                "img[src*='/sistema/fotos/']::attr(src)"
            ).getall()
            seen_imgs: set[str] = set()
            for u in img_urls:
                if not u or "data:image" in u:
                    continue
                absolute = response.urljoin(u)
                if absolute in seen_imgs:
                    continue
                seen_imgs.add(absolute)
                unique_imgs.append(absolute)
        if unique_imgs:
            loader.add_value("images", unique_imgs[:20])

        # Documentos — Caixa hospeda em URL determinística:
        #   /editais/{kind}/{UF}/{lot_id}.pdf  (kind ∈ matricula, edital, laudo)
        docs: list[dict] = []
        seen_docs: set[str] = set()
        if lot_id_real and uf_meta:
            for kind, name in (("matricula", "Matrícula"),
                               ("edital", "Edital"),
                               ("laudo", "Laudo")):
                url = f"{_PDF_BASE}/{kind}/{uf_meta}/{lot_id_real}.pdf"
                seen_docs.add(url)
                docs.append({"name": name, "url": url})
        # Scrape <a> PDFs adicionais
        for a in response.css("a[href$='.pdf'], a[href*='.pdf?']"):
            url = a.css("::attr(href)").get()
            if not url:
                continue
            absolute = response.urljoin(url)
            if absolute in seen_docs:
                continue
            seen_docs.add(absolute)
            label = _normalize_text(" ".join(a.css("*::text").getall())) or "documento"
            docs.append({"name": label, "url": absolute})
        if docs:
            loader.add_value("documents", docs)

        payment_options, encumbrances = _parse_auction_clauses(body_text)
        if payment_options:
            loader.add_value("payment_options", payment_options)
        if encumbrances:
            loader.add_value("encumbrances", encumbrances)

        loader.add_value("scraped_at", self.now_iso())
        item = loader.load_item()
        self.log_event(
            "caixa_lote_extracted",
            url=response.url,
            modalidade=(response.meta.get("modalidade_label") or "")[:40],
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            mkt=item.get("market_value"),
            matr=(item.get("address") or {}).get("registry_matricula"),
        )
        yield item
