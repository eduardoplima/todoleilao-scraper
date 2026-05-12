"""Spider para o portal oficial Caixa Econômica Federal.

**Status: `requires_followup`.** Implementação scaffold pronta para
extração quando o fluxo de submissão multi-passo for resolvido.

Cobre o portal `venda-imoveis.caixa.gov.br/sistema/busca-imovel.asp`, que
unifica três modalidades:

  1. **Leilão SFI** — 1ª e 2ª praça (alienação fiduciária Lei 9.514).
  2. **Licitação Aberta** — após 2ª praça frustrada.
  3. **Venda Online / Venda Direta Online** — BNDU/BNDI (preço fixo).

Bloqueios técnicos identificados:
  - Radware Bot Manager (`validate.perfdrive.com`): bypassed com UA
    Chrome realista (Playwright headless basta).
  - Form é wizard multi-step (Localização → Característica → Pagamento
    → Resultados) com 3+ clicks de "Próximo" entre passos; cada click
    dispara XHR a `carregaListaCidades.asp` / `carregaListaBairros.asp`.
  - `buscarPesquisa()` sem argumentos no contexto global navega para o
    header search (`caixa.gov.br/site/Paginas/Pesquisa.aspx`) em vez de
    submeter o form interno — precisa chamar com handler do wizard.
  - Calendário oficial (PDF) tem cookie/Azion challenge separado, em loop
    de redirect (`security=true`) — pode ser fonte alternativa quando
    quebrar.

Listagens de resultado vivem em `busca-imovel-resultado.asp` e detalhes
em `detalhe-imovel.asp?hdnimovel=N` — o parser de detalhe (`parse_property`)
já está completo. O que falta é o orquestrador do wizard.

Cap defensivo: `MAX_LOTS_PER_RUN = 1000` por execução.

Provider slug: `caixa`. Estados são amostrados se `urls` não vem com
parâmetro `?estado=SP` etc. — default samplea SP, RJ, MG, RS, DF.

Uso:
    scrapy crawl caixa -a urls="https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.asp?estado=SP"
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urlparse, parse_qs

import scrapy
from scrapy_playwright.page import PageMethod

from leilao_scraper.spiders._provider_base import ProviderSpider
from leilao_scraper.spiders.soleon import (
    _brl_to_decimal,
    _detail_is_imovel,
    _normalize_text,
    _parse_auction_clauses,
)


_DEFAULT_STATES = ("SP", "RJ", "MG", "RS", "DF")

# Detail URL pattern: detalhe-imovel.asp?hdnimovel=NUMERO
_DETAIL_HREF_RE = re.compile(
    r"/sistema/detalhe-imovel\.asp\?hdnimovel=(\d+)", re.I
)

# Modalidade textual no detail mapped to modality enum
_MODALIDADE_TO_KIND = {
    "leilão sfi": "extrajudicial_lei_9514",
    "leilao sfi": "extrajudicial_lei_9514",
    "licitação aberta": "extrajudicial_outro",
    "licitacao aberta": "extrajudicial_outro",
    "venda online": "extrajudicial_outro",
    "venda direta": "extrajudicial_outro",
    "venda direta online": "extrajudicial_outro",
}

_MATRICULA_RE = re.compile(
    r"matr[íi]cula\s*(?:n[º°.]?\s*)?(\d{1,7})", re.I
)


# JS injetado no form pra:
#   1. selecionar Estado
#   2. aguardar XHR de cidades terminar
#   3. clicar Buscar (botão "Próximo" com onclick=buscarPesquisa() ou
#      o submit-handler global)
_FORM_SUBMIT_JS = """
async ({estado}) => {
    function wait(ms) { return new Promise(r => setTimeout(r, ms)); }
    const sel = document.getElementById('cmb_estado');
    if (!sel) return {ok: false, msg: 'cmb_estado missing'};
    sel.value = estado;
    sel.dispatchEvent(new Event('change', {bubbles:true}));
    // Espera carregaListaCidades.asp completar; flag fica em jQuery.active
    let tries = 0;
    while (tries < 30) {
        await wait(500);
        if (typeof jQuery !== 'undefined' && jQuery.active === 0) break;
        tries++;
    }
    // Marca o checkbox de autorização do termo de uso
    const auth = document.getElementById('chkAutoriza');
    if (auth && !auth.checked) auth.click();
    // Submit: chama buscarPesquisa() global se existe
    if (typeof buscarPesquisa === 'function') {
        buscarPesquisa();
        return {ok: true, msg: 'buscarPesquisa called'};
    }
    // Fallback: clicar primeiro botão Próximo visível
    const btns = Array.from(document.querySelectorAll('button')).filter(
        b => /(próximo|proximo|buscar)/i.test(b.innerText) && b.offsetParent
    );
    if (btns[0]) {
        btns[0].click();
        return {ok: true, msg: 'clicked: ' + btns[0].innerText};
    }
    return {ok: false, msg: 'no submit handler found'};
}
"""


class CaixaSpider(ProviderSpider):
    name = "caixa"
    provider_slug = "caixa"
    auctioneer_slug = "caixa"
    requires_playwright = True

    custom_settings = {
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "DOWNLOAD_DELAY": 2.0,
        "PLAYWRIGHT_MAX_PAGES_PER_CONTEXT": 4,
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 60_000,
        "USER_AGENT": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    MAX_LOTS_PER_RUN = 1000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._yielded = 0
        self._seen: set[str] = set()
        # Lista de estados a varrer — derivada de start_urls (?estado=XX)
        # ou default.
        self._states_to_scan: list[str] = []
        for url in self.start_urls:
            q = parse_qs(urlparse(url).query)
            uf = (q.get("estado") or [""])[0].upper()
            if uf and len(uf) == 2:
                self._states_to_scan.append(uf)
        if not self._states_to_scan:
            self._states_to_scan = list(_DEFAULT_STATES)

    def start_requests(self) -> Iterable[Any]:
        # Para cada estado, abre busca-imovel.asp via Playwright e
        # submete o form. A página de resultado é renderizada dentro do
        # mesmo Playwright page; capturamos via callback.
        for uf in self._states_to_scan:
            url = "https://venda-imoveis.caixa.gov.br/sistema/busca-imovel.asp"
            yield self.make_request(
                url,
                callback=self.parse_results,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "estado_uf": uf,
                    "playwright_page_methods": [
                        PageMethod("wait_for_selector", "select#cmb_estado", timeout=30_000),
                        PageMethod("wait_for_timeout", 3000),
                        PageMethod("evaluate", _FORM_SUBMIT_JS, {"estado": uf}),
                        # Aguarda o resultado: pode redirecionar para
                        # busca-imovel-resultado.asp OU substituir o DOM.
                        PageMethod("wait_for_timeout", 8000),
                    ],
                },
                dont_filter=True,
            )

    async def parse_results(self, response: scrapy.http.Response) -> Iterable[Any]:
        """Coleta hrefs de `detalhe-imovel.asp?hdnimovel=N` da página de
        resultado renderizada. Caixa pagina via querystring `pagina=N`
        ou via paginador AJAX; v1 captura só a primeira página."""
        page = response.meta.get("playwright_page")
        uf = response.meta.get("estado_uf")

        # Body atual do Playwright; pode ter mudado para resultado
        # após o submit JS.
        try:
            current_url = page.url if page else response.url
            html = await page.content() if page else response.text
        except Exception:
            current_url = response.url
            html = response.text

        # Procura hrefs detalhe-imovel
        seen_ids: set[str] = set()
        kept = 0
        for m in _DETAIL_HREF_RE.finditer(html):
            lot_id = m.group(1)
            if lot_id in seen_ids:
                continue
            seen_ids.add(lot_id)
            detail_url = (
                f"https://venda-imoveis.caixa.gov.br/sistema/"
                f"detalhe-imovel.asp?hdnimovel={lot_id}"
            )
            if detail_url in self._seen:
                continue
            self._seen.add(detail_url)
            if self._yielded >= self.MAX_LOTS_PER_RUN:
                break
            self._yielded += 1
            kept += 1
            yield self.make_request(
                detail_url,
                callback=self.parse_property,
                meta={
                    "source_listing_url": current_url,
                    "estado_uf": uf,
                    "source_lot_code": f"caixa-{lot_id}",
                },
                wait_for_selector="body",
                wait_timeout_ms=20_000,
            )

        self.log_event(
            "caixa_results_done",
            url=current_url,
            uf=uf,
            kept=kept,
            distinct_ids=len(seen_ids),
        )
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass

    def parse_property(self, response: scrapy.http.Response):
        body_text = _normalize_text(" ".join(response.css("body *::text").getall()))
        h1 = (response.css("h1::text").get() or "").strip()
        og_title = response.css("meta[property='og:title']::attr(content)").get() or h1

        sample = h1 + " " + body_text[:3000]
        # Caixa quase sempre é imóvel; ainda assim filtramos defensivamente.
        if not _detail_is_imovel(og_title or h1 or "imóvel Caixa", sample):
            self.log_event("caixa_lote_dropped_non_imovel", url=response.url)
            return

        loader = self.new_loader(response)
        loader.replace_value("auctioneer", "caixa")
        loader.add_value("source_lot_code", response.meta.get("source_lot_code"))

        title_text = h1 or og_title or ""
        # Caixa título típico: "ITAQUERA - SAO PAULO/SP" ou similar
        if not title_text:
            # Tenta pegar do bloco "Endereço"
            title_text = (
                response.css("h3::text, .titulo::text, h5::text").get() or ""
            ).strip()
        if title_text:
            loader.add_value("title", title_text[:300])

        # Descrição — múltiplos blocos no detalhe Caixa
        desc_parts = response.css(
            "div.content-info *::text, "
            "div.detalhes-imovel *::text, "
            "div.descricao *::text"
        ).getall()
        desc = _normalize_text(" ".join(desc_parts))
        if desc:
            loader.add_value("description", desc[:10000])

        # Status — modalidade da venda
        modalidade_raw = ""
        for label in ("Modalidade de venda", "Tipo de leilão", "Tipo de venda", "Situação"):
            m = re.search(rf"{re.escape(label)}\s*:?\s*([A-Za-zÀ-ú0-9°º\s/-]+?)(?:\n|<|R\$|$)",
                          body_text, re.I)
            if m:
                modalidade_raw = m.group(1).strip()
                break

        modalidade_lower = modalidade_raw.lower()
        if any(k in modalidade_lower for k in ("encerrad", "finalizad", "vendido")):
            status = "desconhecido"
        else:
            status = "aberto"
        loader.add_value("status", status)

        # auction_phase / modalidade
        if "1º" in modalidade_raw or "1°" in modalidade_raw or "1 leilão" in modalidade_lower:
            loader.add_value("auction_phase", "1a_praca")
        elif "2º" in modalidade_raw or "2°" in modalidade_raw or "2 leilão" in modalidade_lower:
            loader.add_value("auction_phase", "2a_praca")

        # Preço — Caixa exibe:
        #   "Valor de avaliação: R$ XX"
        #   "Valor mínimo de venda: R$ XX"  (1º/2º leilão SFI)
        #   "Valor para venda: R$ XX"  (venda direta)
        m_av = re.search(r"Valor\s+de\s+avalia[çc][ãa]o[:\s]*R\$\s*([\d.,]+)", body_text, re.I)
        if m_av:
            try:
                v = _brl_to_decimal(m_av.group(1))
                if v and v > 0:
                    loader.add_value("market_value", str(v))
            except Exception:
                pass

        m_min = (
            re.search(r"Valor\s+m[íi]nimo\s+(?:de\s+venda|do\s+\d+[º°ª][^R]{0,30})?[:\s]*R\$\s*([\d.,]+)", body_text, re.I)
            or re.search(r"Valor\s+para\s+venda[:\s]*R\$\s*([\d.,]+)", body_text, re.I)
            or re.search(r"Pelo\s+valor\s+de[:\s]*R\$\s*([\d.,]+)", body_text, re.I)
        )
        if m_min:
            try:
                v = _brl_to_decimal(m_min.group(1))
                if v and v > 0:
                    loader.add_value("minimum_bid", str(v))
            except Exception:
                pass

        # Endereço — campos típicos: Endereço, Bairro, Cidade, UF
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

        # Documentos: edital, matrícula, laudo — PDFs linkados em divs
        # com classe "documentos" / "anexos".
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
            modalidade=modalidade_raw[:40],
            status=item.get("status"),
            min_bid=item.get("minimum_bid"),
            mkt=item.get("market_value"),
            matr=(item.get("address") or {}).get("registry_matricula"),
        )
        yield item
