"""The affairs the source adapters work on, with the OPD facts every check needs.

Two gap causes (census answer-link status, `census.funnel`):
  absent      a written answer is recorded (answer event) and OPD holds no answer document for the affair: the
              10,800 "needs a per-parliament source adapter" of the funnel (BE and CHE have their own routes and are
              excluded; question time is typed oral by the census and is not in this set)
  image_only  an answer document is attached but OPD holds no usable text (the `ocr` rows of repair.run); the adapters
              look for a copy with a text layer before anyone OCRs it

Per affair: OPD id, body, number, type, year, titles, the parliament's own URL (url_external_*), external id, and the
dates of OPD's written-answer events, of other events whose actor is the executive (gov_dates), and of submission
events (the date check compares the document against these).

usage: python -m gegenprobe.repair.adapters.targets      -> WORK/adapters/targets.json.gz + per-body counts
"""
from __future__ import annotations

import collections
import gzip
import json
import re
import sys

from ...census import defs
from ...census.funnel import compute
from ...census.tables import i, rows
from ...paths import WORK
from ..common import iter_ndjson

ADIR = WORK / "adapters"
TARGETS = ADIR / "targets.json.gz"
EXCLUDE = ("BE", "CHE")  # own routes: repair.be (canton OGD), repair.che (Curia Vista / Fedlex)
# events whose actor is the executive (e.g. Solothurn: the government's "Antrag: Ablehnen" on a motion, while OPD's
# "Beantwortet" event is the committee's); used as a second reference date, reported separately (date_match eq_gov)
GOV_ACTOR = re.compile(r"^(Regierung|Regierungsrat|Stadtrat|Gemeinderat|Conseil d.[ÉE]tat|Conseil communal|Municipalit|"
                       r"Gouvernement|Consiglio di Stato|Municipio|Kleiner Rat|Staatsrat)", re.I)


def build() -> dict[int, dict]:
    _, aff = compute()
    tg: dict[int, dict] = {}
    for aid, x in aff.items():
        if x["b"] in EXCLUDE or not x["ev_w"]:
            continue
        if x["link"] == "absent":
            cause = "absent"
        elif x["link"] == "image_only" and not x["vs_stub"]:
            cause = "image_only"
        else:
            continue
        tg[aid] = dict(id=aid, body=x["b"], number=x["num"], type=x["t"], year=x["y"], ext=x["ext"], cause=cause,
                       answer_dates=[], gov_dates=[], submit_dates=[], begin=(x["begin"] or "")[:10] or None)
    for e in rows("events"):
        a = i(e["affair"])
        x = tg.get(a)
        if x is None or not e["date"]:
            continue
        hid = i(e["hid"])
        if defs.classify_event(e["title"], hid) == "written":
            x["answer_dates"].append(e["date"][:10])
        elif GOV_ACTOR.search(e.get("actor") or "") and not defs.NOT_EV.search(e["title"]):
            x["gov_dates"].append(e["date"][:10])
        if hid in (1, 56, 67):
            x["submit_dates"].append(e["date"][:10])
    for a in iter_ndjson("affairs"):
        x = tg.get(a["id"])
        if x is None:
            continue
        x["title"] = next((a.get(f"title_{lang}") for lang in ("de", "fr", "it") if a.get(f"title_{lang}")), None)
        x["title_long"] = next((a.get(f"title_long_{lang}") for lang in ("de", "fr", "it") if a.get(f"title_long_{lang}")),
                               None)
        x["url_external"] = next((a.get(f"url_external_{lang}") for lang in ("de", "fr", "it")
                                  if a.get(f"url_external_{lang}")), None)
        x["external_id"] = a.get("external_id")
        x["type_raw"] = a.get("type_name_de") or a.get("type_name_fr") or a.get("type_name_it")
    for x in tg.values():
        x["answer_dates"] = sorted(set(x["answer_dates"]))
        x["submit_dates"] = sorted(set(x["submit_dates"]))
        x["gov_dates"] = sorted(set(x["gov_dates"]) - set(x["answer_dates"]))
    return tg


def save(tg: dict[int, dict]) -> None:
    ADIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(TARGETS, "wt", encoding="utf-8") as f:
        json.dump(sorted(tg.values(), key=lambda x: x["id"]), f, ensure_ascii=False)


def load(body: str | None = None, cause: str | None = None) -> list[dict]:
    if not TARGETS.exists():
        save(build())
    with gzip.open(TARGETS, "rt", encoding="utf-8") as f:
        xs = json.load(f)
    return [x for x in xs if (body is None or x["body"] == body) and (cause is None or x["cause"] == cause)]


def counts(xs: list[dict]) -> dict[str, dict[str, int]]:
    c: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for x in xs:
        c[x["body"]][x["cause"]] += 1
    return {b: dict(v) for b, v in sorted(c.items(), key=lambda kv: -sum(kv[1].values()))}


def main(argv: list[str]) -> int:
    tg = build()
    save(tg)
    c = counts(list(tg.values()))
    print(json.dumps(dict(absent=sum(v.get("absent", 0) for v in c.values()),
                          image_only=sum(v.get("image_only", 0) for v in c.values()),
                          top=dict(list(c.items())[:15]))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
