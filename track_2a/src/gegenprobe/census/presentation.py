"""Presentation rules shared by the census outputs, the generated docs and the site (no computation of census numbers).

  CANTON_NAME / site_name   cantons by their official name in the language of their majority (OPD labels every canton in
                            German: 'Tessin', 'Waadt', 'Wallis' ...); cities and communes keep OPD's name (already local)
  answer_date_caveat        what is known about OPD's answer date, with the current verification counts read from the
                            committed results (Bern: results/repair/be_verify_all.json; Ticino: results/census/date_trust.json)
"""

from __future__ import annotations

import json

from ..paths import RESULTS

CANTON_NAME = {
    "ZH": "Zürich", "BE": "Bern", "LU": "Luzern", "UR": "Uri", "SZ": "Schwyz", "OW": "Obwalden", "NW": "Nidwalden",
    "GL": "Glarus", "ZG": "Zug", "FR": "Fribourg", "SO": "Solothurn", "BS": "Basel-Stadt", "BL": "Basel-Landschaft",
    "SH": "Schaffhausen", "AR": "Appenzell Ausserrhoden", "AI": "Appenzell Innerrhoden", "SG": "St. Gallen",
    "GR": "Graubünden", "AG": "Aargau", "TG": "Thurgau", "TI": "Ticino", "VD": "Vaud", "VS": "Valais", "NE": "Neuchâtel",
    "GE": "Genève", "JU": "Jura",
}
CANTON_RULE = ("Cantons are named by their official name in the language of the majority of their population (Ticino, "
               "Vaud, Genève, Valais, Fribourg; Graubünden, Bern, Luzern); cities and communes by OPD's name, which is the "
               "local one. OPD's German names (Tessin, Waadt, Genf, Wallis, Freiburg) still find the row.")


def site_name(key: str, opd_name: str | None, btype: str | None = None) -> str | None:
    """The body's name under the site's naming rule (cantons: CANTON_NAME; everything else: OPD's name)."""
    if btype in (None, "canton") and key in CANTON_NAME:
        return CANTON_NAME[key]
    return opd_name


def _load(p):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def bern_verified() -> dict | None:
    """Bern relink answers whose OPD answer date equals the decision (RRB) date printed in the answer (parser v2)."""
    v = _load(RESULTS / "repair" / "be_verify_all.json")
    if not v:
        return None
    r = v["by_action"]["relink"]["v2"]
    return dict(date_equal=r["date_eq_event"], n=r["n"], review=r["n"] - r["date_eq_event"])


def answer_date_caveat(short: bool = False) -> str:
    """One sentence on what OPD's answer date is, with the current verification counts (never a typed number)."""
    be = bern_verified()
    t = (_load(RESULTS / "census" / "date_trust.json") or {}).get("title_verified", {}).get("TI")
    parts = []
    if be:
        parts.append(f"Bern (the RRB decision date printed in the answer: {be['date_equal']:,} of {be['n']:,} relink answers, "
                     f"the other {be['review']} go to review; results/repair/be_verify_all.json)")
    if t:
        parts.append(f"Ticino (the date in the publisher's answer title 'Risposta del CdS del …': {t['title_equal']:,} of "
                     f"{t['title_dated']:,} dated answers that carry one; results/census/date_trust.json)")
    where = " and ".join(parts) if parts else "no parliament"
    if short:
        return f"checked against the source as the government's decision date only in {where}"
    return (f"the answer date is the OPD event date; it is verified as the government's decision date in {where}, and "
            "unverified elsewhere (it may be a registration or publication date; per-body date-trust tiers in "
            "results/census/date_trust.json).")
