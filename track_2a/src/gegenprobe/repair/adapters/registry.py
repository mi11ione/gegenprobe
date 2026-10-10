"""Adapters by OPD body key. Parliaments with a source route have their own module; every other parliament with target
affairs gets the generic in-OPD adapter (inopd.InOPD), which reads OPD's own documents on the affair."""
from __future__ import annotations

import csv
import importlib
import re
from functools import lru_cache

from ...paths import ROOT
from .base import Adapter

MODULES = {
    "ZH": "zh",
    "261": "zurich_city",
    "SG": "ris4tw",
    "SO": "ris4tw",
    "VS": "vs",
    "LU": "lu",
    "4001": "aarau",
}


def _ju_numbers(number: str) -> list[str]:
    m = re.match(r"^(QE|INT|MO|PO)\s*(\d+)$", number or "")
    if not m:
        return [re.escape(number or "")]
    n = m.group(2)
    return [rf"\(\s*(?:n[°o]\s*)?{n}\s*\)", rf"n[°o]\s*{n}\b", rf"{m.group(1)}\s*{n}\b"]


# Per-body date rules (event - document date, days), each from the parliament's own practice (docs/adapters.md):
#  NE   the answer is "transmise aux membres du Grand Conseil le <date>"; OPD's event is that day or the next
#  4566 Frauenfeld: the answer is signed a few days around OPD's answer event
#  1059 Kriens: OPD's answer event carries the submission date; the Stadtrat's position follows within ~8 weeks
# Locarno: the answer is a letter on the Municipio's letterhead that cites the interrogation; the question is written
# by councillors on their group's paper and addressed to the Municipio
LOCARNO = re.compile(r"Citt[àaä]\W*\s*di\s+Locarno\W{0,6}\s*Municipio[\s\S]{0,700}?Interrogazione", re.I)

# Ticino: the Consiglio di Stato answers by letter to the deputies, citing the interrogation; the question is the
# deputies' text addressed to the government ("TESTO DELL'INTERROGAZIONE")
TICINO = re.compile(r"Il Consiglio di Stato[\s\S]{0,400}?(?:Deputat[oiae]|Signor[ae]?)[\s\S]{0,500}?"
                    r"(?:Interrogazione|Interpellanza)\b", re.I)


def _with(rx: re.Pattern) -> re.Pattern:
    from .inopd import HEADING
    return re.compile(HEADING.pattern + "|" + rx.pattern, re.I)


INOPD = {
    "JU": dict(number_rx=_ju_numbers),
    "5113": dict(heading=_with(LOCARNO)),
    "TI": dict(heading=_with(TICINO)),
    "NE": dict(window=(-1, 1)),
    "4566": dict(window=(-3, 3), all_docs=True),
    "1059": dict(window=(-70, 0)),
    "351": dict(number_shape=re.compile(r"\b(\d{4}\.(?:SR|GR)\.\d{6})\b")),  # Bern city: "2014.SR.000106" heads the Vortrag
}


@lru_cache(maxsize=1)
def labels() -> dict[str, str]:
    p = ROOT / "site" / "parliaments.csv"
    return {r["key"]: r["label"] for r in csv.DictReader(open(p, encoding="utf-8"))} if p.exists() else {}


@lru_cache(maxsize=None)
def get(body: str) -> Adapter:
    if body in MODULES:
        mod = importlib.import_module(f".{MODULES[body]}", __package__)
        return mod.adapter(body) if hasattr(mod, "adapter") else mod.ADAPTER
    from .inopd import InOPD
    return InOPD(body, label=labels().get(body, body), **INOPD.get(body, {}))


def all() -> dict[str, Adapter]:  # noqa: A001
    from . import targets
    bodies = list(MODULES) + sorted({x["body"] for x in targets.load()} - set(MODULES))
    return {b: get(b) for b in bodies}
