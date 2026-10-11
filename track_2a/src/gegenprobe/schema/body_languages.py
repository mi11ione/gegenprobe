"""Body.languages for v0.2 records: the parliament's official languages, not one language per body.

OPD's body export (data/census/bodies.tsv.gz, column `lang`) carries one language per body. The bilingual and trilingual
cantons are listed with every official language from their constitutions; every other body keeps OPD's single language.
No network, no model.
"""
from __future__ import annotations

import csv
import gzip
from functools import lru_cache

from ..paths import ROOT

# canton (body key) -> official languages, in the constitution's order, with the article that fixes them
MULTILINGUAL = {
    "BE": (["de", "fr"], "Constitution of the Canton of Bern (KV BE, BSG 101.1) Art. 6"),
    "FR": (["fr", "de"], "Constitution of the Canton of Fribourg (Cst. FR, RSF 10.1) Art. 6"),
    "VS": (["fr", "de"], "Constitution of the Canton of Valais (Cst. VS, RS/VS 101.1) Art. 12"),
    "GR": (["de", "rm", "it"], "Constitution of the Canton of Graubünden (KV GR, BR 110.100) Art. 3"),
}
SOURCE_OPD = "OPD body export (data/census/bodies.tsv.gz, column lang)"


@lru_cache(maxsize=1)
def _opd() -> dict[str, str]:
    with gzip.open(ROOT / "data" / "census" / "bodies.tsv.gz", "rt", encoding="utf-8") as f:
        return {r["key"]: (r.get("lang") or "").strip().lower() for r in csv.DictReader(f, delimiter="\t")}


def languages(body_key: str) -> tuple[list[str], str]:
    """(official languages, source); ([], why) when neither the table nor OPD gives one."""
    if body_key in MULTILINGUAL:
        langs, src = MULTILINGUAL[body_key]
        return list(langs), src
    lg = _opd().get(body_key, "")
    if lg in ("de", "fr", "it", "rm"):
        return [lg], SOURCE_OPD
    return [], f"{SOURCE_OPD}: no language recorded for body {body_key}"
