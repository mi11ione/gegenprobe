"""The cross-parliamentary question (challenge requirement): for each Swiss parliament in OPD,
  (1) what share of interventions with a written government answer have that answer's text available in OPD, and
  (2) how long the government takes to answer (submission -> first written-answer event), median days.
Neither is answerable reliably today: (1) needs the answer-link census (answers are filed parentless, under agenda items,
as scans or as oral stubs), (2) needs role-typed dates across 89 differently-structured event vocabularies.

Caveats (also in results): the answer date is the OPD event date; where it is verified as the government's decision date
is read from the committed verification results (presentation.answer_date_caveat: Bern relink answers by
the printed RRB date, Ticino by the publisher's answer title; unverified elsewhere).
Submission = the earliest 'Eingereicht'-type event (harmonised ids 1/56/67), else `begin_date`; BE affairs whose begin_date
is the 2024-10-28 import artefact and no submission event are excluded; durations < 0 or > 3,650 days are excluded and counted.
The national median pools date roles (decision, weekly-sitting, publication dates) and intervention types: see
results/census/answer_days_by_trust.json before quoting it. Body names follow the site's rule (`name`; OPD's: `opd_name`).

usage: python -m gegenprobe.census.question [--data data/census] [--out results/census]
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
from datetime import date
from pathlib import Path

from ..paths import RESULTS
from . import funnel
from .presentation import answer_date_caveat, site_name
from .tables import CENSUS, rows

OUT = RESULTS / "census"
MIN_N = 20
BE_IMPORT_DATE = "2024-10-28"


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def compute(root: Path = CENSUS, F: dict | None = None) -> dict:
    if F is None:
        _, F = funnel.compute(root)
    # submission event dates per affair for all in-scope affairs (funnel keeps the earliest)
    names = {r["key"]: dict(name=r["name"], type=r["type"]) for r in rows("bodies", root)}
    per = collections.defaultdict(
        lambda: dict(written=0, text_now=0, text_after_repair=0, durations=[], excl=collections.Counter())
    )
    by_type = collections.defaultdict(list)
    for x in F.values():
        if not x["ev_w"]:
            continue
        p = per[x["b"]]
        p["written"] += 1
        p["text_now"] += x["link"] in ("attached", "agenda")
        # measured repair routes counted here: agenda join, BE parentless relink. OCR of image-only scans (15/15 recovered in
        # the repair probe, results/repair/ocr_probe.json) is not counted: only the 30-document probe was actually OCR'd
        p["text_after_repair"] += x["link"] in ("attached", "agenda", "parentless")
        sub = x["sub_date"] or x["begin"]
        if not x["sub_date"] and x["b"] == "BE" and x["begin"] == BE_IMPORT_DATE:
            p["excl"]["be_import_date"] += 1
            continue
        if not sub or not x["ans_date"]:
            p["excl"]["missing_date"] += 1
            continue
        d = _days(sub, x["ans_date"])
        if d < 0 or d > 3650:
            p["excl"]["out_of_range"] += 1
            continue
        p["durations"].append(d)
        by_type[x["t"]].append(d)
    bodies = []
    for b, p in per.items():
        if p["written"] < MIN_N:
            continue
        ds = sorted(p["durations"])
        q = statistics.quantiles(ds, n=4) if len(ds) >= 4 else [None, None, None]
        bodies.append(
            dict(
                body=b,
                name=site_name(b, names.get(b, {}).get("name"), names.get(b, {}).get("type")),
                opd_name=names.get(b, {}).get("name"),
                level=names.get(b, {}).get("type"),
                written=p["written"],
                text_share_now=round(p["text_now"] / p["written"], 4),
                text_share_after_relink=round(p["text_after_repair"] / p["written"], 4),
                n_durations=len(ds),
                median_days=statistics.median(ds) if ds else None,
                same_day_share=round(sum(d == 0 for d in ds) / len(ds), 4) if ds else None,
                q1_days=q[0],
                q3_days=q[2],
                excluded=dict(p["excl"]),
            )
        )
    bodies.sort(key=lambda r: (r["median_days"] is None, r["median_days"]))
    allds = [d for p in per.values() for d in p["durations"]]
    tw = sum(p["written"] for p in per.values())
    return dict(
        question="Per parliament: share of written-answer interventions whose answer text is in OPD, and median days to answer",
        min_written=MIN_N,
        n_bodies=len(bodies),
        national=dict(
            written=tw,
            text_share_now=round(sum(p["text_now"] for p in per.values()) / tw, 4),
            text_share_after_relink=round(sum(p["text_after_repair"] for p in per.values()) / tw, 4),
            n_durations=len(allds),
            median_days=statistics.median(allds),
        ),
        by_type={t: dict(n=len(v), median_days=statistics.median(v)) for t, v in sorted(by_type.items())},
        fastest=bodies[:5],
        slowest=[r for r in bodies if r["median_days"] is not None][-5:],
        # bodies where the 'answer' event date is mostly the submission date: the date exists but is not an answer date
        same_day_bodies=[
            dict(body=r["body"], name=r["name"], same_day_share=r["same_day_share"], n=r["n_durations"])
            for r in bodies
            if r["same_day_share"] is not None and r["same_day_share"] >= 0.5
        ],
        n_same_day_bodies=sum(r["same_day_share"] is not None and r["same_day_share"] >= 0.5 for r in bodies),
        lowest_text_share=sorted(bodies, key=lambda r: r["text_share_now"])[:8],
        bodies=sorted(bodies, key=lambda r: r["body"]),
        caveats=[answer_date_caveat() + " " + __doc__.split("unverified elsewhere).\n")[1].split("\n\nusage")[0]
                 .replace("\n", " ")],
    )


def main(root: Path = CENSUS, out: Path = OUT, F: dict | None = None) -> dict:
    q = compute(root, F)
    out.mkdir(parents=True, exist_ok=True)
    (out / "question.json").write_text(json.dumps(q, indent=1, ensure_ascii=False, sort_keys=True))
    return q


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=CENSUS)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    q = main(a.data, a.out)
    print(json.dumps(q["national"]), json.dumps(q["by_type"]))
    for r in q["fastest"] + q["slowest"]:
        print(r["body"], r["name"], r["written"], r["text_share_now"], r["median_days"], r["excluded"])
    for r in q["lowest_text_share"]:
        print("low", r["body"], r["name"], r["written"], r["text_share_now"], r["text_share_after_relink"])
