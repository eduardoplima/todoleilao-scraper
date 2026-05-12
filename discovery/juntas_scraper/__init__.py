"""Pacote de scrapers para as 27 Juntas Comerciais (26 estados + DF).

Cada Junta tem seu próprio módulo (`jucepar.py`, `jucesp.py`, …) com uma
subclasse de `JuntaScraper`. O dict `REGISTRY` mapeia a sigla canônica para
a classe — usado pelo `__main__.py` para iterar sobre todas as Juntas.

Status atual:
- Implementadas: JUCEPAR, JUCERJA, JUCEMG, JUCEC, JUCEG, JUCEES.
- Stub (requires_manual_request): demais 21 — vide razão em cada módulo.
"""

from __future__ import annotations

from .base import CSV_COLUMNS, JuntaScraper, StubJuntaScraper
from .jcdf import Jcdf
from .jucap import Jucap
from .jucea import Jucea
from .juceac import Juceac
from .juceal import Juceal
from .juceb import Juceb
from .jucec import Jucec
from .jucees import Jucees
from .juceg import Juceg
from .jucema import Jucema
from .jucemat import Jucemat
from .jucemg import Jucemg
from .jucems import Jucems
from .jucep import Jucep
from .jucepa import Jucepa
from .jucepar import JucepaR
from .jucepe import Jucepe
from .jucepi import Jucepi
from .jucer import Jucer
from .jucerja import Jucerja
from .jucern import Jucern
from .jucerr import Jucerr
from .jucesc import Jucesc
from .jucese import Jucese
from .jucesp import Jucesp
from .jucetins import Jucetins
from .jucisrs import Jucisrs

REGISTRY: dict[str, type[JuntaScraper]] = {
    "JUCEAC": Juceac,
    "JUCEAL": Juceal,
    "JUCEA": Jucea,
    "JUCAP": Jucap,
    "JUCEB": Juceb,
    "JUCEC": Jucec,
    "JCDF": Jcdf,
    "JUCEES": Jucees,
    "JUCEG": Juceg,
    "JUCEMA": Jucema,
    "JUCEMG": Jucemg,
    "JUCEMS": Jucems,
    "JUCEMAT": Jucemat,
    "JUCEPA": Jucepa,
    "JUCEP": Jucep,
    "JUCEPE": Jucepe,
    "JUCEPI": Jucepi,
    "JUCEPAR": JucepaR,
    "JUCERJA": Jucerja,
    "JUCERN": Jucern,
    "JUCER": Jucer,
    "JUCERR": Jucerr,
    "JUCISRS": Jucisrs,
    "JUCESC": Jucesc,
    "JUCESE": Jucese,
    "JUCESP": Jucesp,
    "JUCETINS": Jucetins,
}

assert len(REGISTRY) == 27, f"esperava 27 Juntas, registry tem {len(REGISTRY)}"

__all__ = [
    "CSV_COLUMNS",
    "REGISTRY",
    "JuntaScraper",
    "StubJuntaScraper",
]
