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

# UA realista — Chromium do scrapy-playwright e Radware esperam mesmo
# UA do navegador automatizado, senão fingerprint diverge dos cookies.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


class CaixaSpider(ProviderSpider):
    name = "caixa"
    provider_slug = "caixa"
    auctioneer_slug = "caixa"
    requires_playwright = True

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "DOWNLOAD_DELAY": 1.0,
        "PLAYWRIGHT_MAX_PAGES_PER_CONTEXT": 4,
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 60_000,
        "USER_AGENT": _BROWSER_UA,
    }

    MAX_LOTS_PER_RUN = 1500

    def __init__(self, *args, estados: str | None = None,
                 modalidades: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._yielded = 0
        self._seen_lot_ids: set[str] = set()
        # Estados (CSV ou default).
        self._estados: list[str] = []
        if estados:
            self._estados = [s.strip().upper() for s in estados.split(",") if s.strip()]
        if not self._estados:
            self._estados = list(_DEFAULT_STATES)
        # Modalidades.
        self._modalidades: list[tuple[str, str]] = []
        if modalidades:
            wanted = {s.strip() for s in modalidades.split(",") if s.strip()}
            self._modalidades = [(v, lbl) for v, lbl in _DEFAULT_MODALIDADES if v in wanted]
        if not self._modalidades:
            self._modalidades = list(_DEFAULT_MODALIDADES)
        self.logger.info(
            f"Caixa: estados={self._estados} modalidades={[v for v,_ in self._modalidades]}"
        )

    # ------------------------------------------------------------------
    # Nível 1: Playwright bootstrap por (UF × modalidade)
    # ------------------------------------------------------------------
    def start_requests(self) -> Iterable[Any]:
        for uf in self._estados:
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
                        "playwright_page_methods": [
                            PageMethod("wait_for_selector", "select#cmb_estado",
                                       timeout=30_000),
                            PageMethod("wait_for_timeout", 5000),  # Radware
                        ],
                    },
                    dont_filter=True,
                )

    async def parse_search_bootstrap(self, response: scrapy.http.Response):
        """Roda no Playwright. Seta UF + Modalidade, chama
        carregaPesquisaImoveis() via evaluate, captura HTML do response
        XHR (com hdnImov<N>). Encerra Playwright, persiste cookies em
        meta para os próximos requests Scrapy."""
        page = response.meta.get("playwright_page")
        uf = response.meta["estado_uf"]
        mod_val = response.meta["modalidade_val"]
        mod_label = response.meta["modalidade_label"]

        if page is None:
            self.logger.warning("Caixa: Playwright page indisponível")
            return

        try:
            # Captura a resposta XHR do carregaPesquisaImoveis.asp.
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

            # Configura form + dispara carregaPesquisaImoveis().
            await page.select_option("select[name='cmb_estado']", uf)
            await page.wait_for_timeout(1500)
            await page.select_option("select[name='cmb_modalidade']", mod_val)
            await page.wait_for_timeout(1000)
            await page.evaluate(
                "() => { $('#hdn_estado').val($('#cmb_estado :selected').val());"
                "  carregaPesquisaImoveis('', [], $('#cmb_modalidade :selected').val()); }"
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
                status=search_html_holder.get("status"),
                preview=body[:200],
            )
            return

        # Parse páginas de IDs.
        pages = list(_HDN_IMOV_RE.finditer(body))
        self.log_event(
            "caixa_search_done", uf=uf, modalidade=mod_label,
            pages=len(pages),
            total_ids=sum(len(m.group(2).split("||")) for m in pages),
        )
        for m in pages:
            page_num = m.group(1)
            ids_str = m.group(2).strip().strip("|")
            if not ids_str:
                continue
            # POST direto a carregaListaImoveis.asp (sem Playwright)
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

        # Descrição
        desc_parts = response.css(
            "div.content-info *::text, "
            "div.detalhes-imovel *::text, "
            "div.descricao *::text, "
            "div.fotoimovel *::text"
        ).getall()
        desc = _normalize_text(" ".join(desc_parts))
        if not desc or len(desc) < 50:
            desc = body_text[:6000]
        if desc:
            # Adiciona "Comitente: Caixa Econômica Federal" no início da
            # description para que o trigger SQL extract_creditors capture.
            if "caixa econômica federal" not in desc.lower():
                desc = f"Comitente: Caixa Econômica Federal. {desc}"
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

        m_min = (
            re.search(
                r"Valor\s+m[íi]nimo\s+(?:de\s+venda|do\s+\d+[º°ª][^R]{0,30})?[:\s]*R\$\s*([\d.,]+)",
                body_text, re.I,
            )
            or re.search(r"Valor\s+para\s+venda[:\s]*R\$\s*([\d.,]+)", body_text, re.I)
            or re.search(r"Pelo\s+valor\s+de[:\s]*R\$\s*([\d.,]+)", body_text, re.I)
            or re.search(r"Preço[:\s]*R\$\s*([\d.,]+)", body_text, re.I)
        )
        if m_min:
            try:
                v = _brl_to_decimal(m_min.group(1))
                if v and v > 0:
                    loader.add_value("minimum_bid", str(v))
            except Exception:
                pass

        # Endereço
        addr: dict[str, Any] = {"raw_text": title_text[:300]}
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
        if "uf" not in addr:
            uf_meta = response.meta.get("estado_uf")
            if uf_meta:
                addr["uf"] = uf_meta
        m_matr = _MATRICULA_RE.search(body_text)
        if m_matr:
            addr["registry_matricula"] = m_matr.group(1)
        if any(v for v in addr.values()):
            loader.add_value("address", addr)

        # Imagens
        img_urls = response.css(
            "img[src*='/sistema/galeria/']::attr(src), "
            "img[src*='/sistema/imagens/']::attr(src), "
            "img[src*='/sistema/fotos/']::attr(src)"
        ).getall()
        seen_imgs: set[str] = set()
        unique_imgs: list[str] = []
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

        # Documentos
        docs: list[dict] = []
        seen_docs: set[str] = set()
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
