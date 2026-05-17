"""Constantes de User-Agent compartilhadas entre spiders Scrapy.

Pra discovery (`discovery/*`), há módulo paralelo `discovery/_common_ua.py`
com as mesmas constantes — evita import cross-package.

Atualize ambos juntos. Chrome version recomendado: estável trimestral.
"""
from __future__ import annotations

# Chrome 122 (estável Feb 2025). Atualizar quando major version subir 4+.
# Sites com WAF (nginx default, Cloudflare, Akamai) bloqueiam UAs minimal
# tipo "Mozilla/5.0" puro ou "TodoLeilaoBot/0.1" — esse UA simula browser
# real e passa pela maioria das defesas. Caso documentado: fidelisleiloes
# .com.br retorna 116KB com este UA, 612 bytes ("Welcome to nginx!") com
# o anterior.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# Bot identificável — usar SÓ pra APIs públicas que aceitam UA bot:
#   - Nominatim/OSM (TOS exige UA identificável)
#   - INNLEI API pública
# NÃO usar pra fetch de sites de leiloeiros — WAF bloqueia.
BOT_USER_AGENT = "TodoLeilaoBot/0.1 (+contato: eplima.cc@gmail.com)"
