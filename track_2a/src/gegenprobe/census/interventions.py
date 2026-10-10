"""Research dataset: one row per in-scope intervention whose events record a written government answer (the census funnel's
denominator, 91,268 on the 2026-10-06 snapshot), plus a per-body date-trust table. NEW outputs only; the asserted census
results (funnel, summary, matrix, question …) are not touched.

    python -m gegenprobe.census.interventions      -> results/census/interventions.tsv.gz, interventions_README.md,
                                                     date_trust.json, answer_rule_alt.json

Columns are documented in results/census/interventions_README.md. Two answer-date rules:
  answer_date      the census rule: the EARLIEST written-answer event (what results/census/question.json uses)
  answer_date_alt  prefer OPD's harmonised 'Beantwortet' events (harmonised id 6); earliest of those, else the census rule.
                   Fixes bodies where an event harmonised as 'Eingereicht' (id 1) carries an answer title on the
                   submission date (Schaffhausen), which the earliest-event rule picks up.
The source canton page (OPD's url_external_*) is added for rows without an attached answer when the raw affairs export is
available at build time (GP_OPD_RAW); the committed file carries it, so nothing downstream needs the raw export.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import gzip
import io
import json
import re
import statistics
from pathlib import Path

from ..paths import OPD_RAW, RESULTS
from . import defs, funnel
from .tables import i, rows

OUT = RESULTS / "census"
OPD_AFFAIR_URL = "https://openparldata.ch/item/affairs/{id}"
BE_LOAD_DATE = "2024-10-28"
COLS = ["body", "affair_id", "number", "type", "type_raw", "year", "submitted", "submitted_source", "be_load_date",
        "answer_date", "answer_hid", "answer_date_alt", "answer_hid_alt", "n_answer_events", "answer_spread_days",
        "days_to_answer", "days_to_answer_alt", "link_status", "oral_event", "same_day_body", "date_trust",
        "opd_url", "source_url"]


# Publisher titles that name the government's decision date of an answer document (the same two patterns as the post-hoc
# gold oracle, eval/posthoc_r3.py): Ticino 'Risposta del CdS del dd.mm.yyyy', Bern 'RRB-dd.mm.yyyy'.
TITLE_DATE = (re.compile(r"Risposta del CdS del (\d{2})\.(\d{2})\.(\d{4})"), re.compile(r"\bRRB-(\d{2})\.(\d{2})\.(\d{4})"))
# 'verified' by title: at least this share of a body's dated answers carry a title date, and at least this share of those
# equal OPD's answer date (Bern is verified by the printed date, document by document: results/repair/be_verify_all.json)
TITLE_COVER, TITLE_AGREE = 0.9, 0.99


def _title_dates(written: set[int]) -> dict[int, set[str]]:
    """affair -> the decision dates its documents' publisher titles name (data/census/docs.tsv.gz `name`)."""
    out: dict[int, set[str]] = collections.defaultdict(set)
    for d in rows("docs"):
        a = i(d["affair"])
        if a is None or a not in written:
            continue
        for rx in TITLE_DATE:
            m = rx.search(d["name"] or "")
            if m:
                try:
                    out[a].add(dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat())
                except ValueError:
                    pass
    return out


def _days(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    return (dt.date.fromisoformat(b[:10]) - dt.date.fromisoformat(a[:10])).days


def _raw_types_and_urls(need: set[int]) -> tuple[dict, dict]:
    """type_raw for all in-scope affairs from the vendored table; source urls from the raw export when present."""
    types = {int(a["id"]): a["type_raw"] for a in rows("affairs")}
    urls = {}
    raw = OPD_RAW / "affairs.ndjson.gz"
    if raw.exists():
        with gzip.open(raw, "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d["id"] in need:
                    urls[d["id"]] = next((d.get(f"url_external_{lg}") for lg in ("de", "fr", "it", "rm")
                                          if d.get(f"url_external_{lg}")), "") or ""
    return types, urls


def build() -> dict:
    _, F = funnel.compute()
    written = {a: x for a, x in F.items() if x["ev_w"]}
    ev = collections.defaultdict(list)  # affair -> [(date, hid)] written-answer events
    for e in rows("events"):
        a = int(e["affair"])
        if a not in written or not e["date"]:
            continue
        hid = i(e["hid"])
        if defs.classify_event(e["title"], hid) == "written":
            ev[a].append((e["date"][:10], hid))
    q = json.loads((OUT / "question.json").read_text())
    same_day = {b["body"] for b in q["same_day_bodies"]}
    missing = {a for a, x in written.items() if x["link"] != "attached"}
    types, urls = _raw_types_and_urls(missing)

    titles = _title_dates(set(written))
    out_rows, per_body = [], collections.defaultdict(lambda: dict(d=[], d_alt=[], wd=collections.Counter(), n=0, title_n=0,
                                                                  title_eq=0))
    changed = collections.Counter()
    for a, x in sorted(written.items()):
        es = sorted(ev.get(a, []))
        ans = x["ans_date"]
        h6 = [d for d, h in es if h == 6]
        alt = min(h6) if h6 else ans
        hid = next((h for d, h in es if d == (ans or "")[:10]), None)
        hid_alt = 6 if h6 else hid
        sub, src = (x["sub_date"], "event") if x["sub_date"] else (x["begin"], "begin_date" if x["begin"] else "")
        be_load = x["b"] == "BE" and not x["sub_date"] and (x["begin"] or "")[:10] == BE_LOAD_DATE
        d1 = None if be_load else _days(sub, ans)
        d2 = None if be_load else _days(sub, alt)
        d1 = d1 if d1 is not None and 0 <= d1 <= 3650 else None
        d2 = d2 if d2 is not None and 0 <= d2 <= 3650 else None
        spread = _days(es[0][0], es[-1][0]) if len(es) > 1 else 0
        if (alt or "")[:10] != (ans or "")[:10]:
            changed[x["b"]] += 1
        pb = per_body[x["b"]]
        pb["n"] += 1
        if d1 is not None:
            pb["d"].append(d1)
        if d2 is not None:
            pb["d_alt"].append(d2)
        if ans:
            pb["wd"][dt.date.fromisoformat(ans[:10]).weekday()] += 1
            if titles.get(a):
                pb["title_n"] += 1
                pb["title_eq"] += (ans or "")[:10] in titles[a]
        out_rows.append(dict(
            body=x["b"], affair_id=a, number=x["num"] or "", type=x["t"], type_raw=types.get(a, ""), year=x["y"] or "",
            submitted=(sub or "")[:10], submitted_source=src, be_load_date=int(be_load), answer_date=(ans or "")[:10],
            answer_hid=hid if hid is not None else "", answer_date_alt=(alt or "")[:10],
            answer_hid_alt=hid_alt if hid_alt is not None else "", n_answer_events=len(es), answer_spread_days=spread,
            days_to_answer="" if d1 is None else d1, days_to_answer_alt="" if d2 is None else d2, link_status=x["link"],
            oral_event=int(x["ev_oral"]), same_day_body=int(x["b"] in same_day), date_trust="",
            opd_url=OPD_AFFAIR_URL.format(id=a), source_url=urls.get(a, "") if a in missing else ""))

    # date trust per body: verified (Bern by printed date; others by publisher title), same-day artefact, or concentration of
    # answer dates on one weekday
    vb = json.loads((RESULTS / "repair" / "be_verify_all.json").read_text())
    trust = {}
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for b, pb in per_body.items():
        tot = sum(pb["wd"].values())
        mw, mc = (pb["wd"].most_common(1)[0] if tot else (None, 0))
        share = mc / tot if tot else None
        by_title = (tot >= 20 and pb["title_n"] >= TITLE_COVER * tot and pb["title_eq"] >= TITLE_AGREE * pb["title_n"])
        if b == "BE":
            tier, basis = "verified", "printed"
        elif b in same_day:
            tier, basis = "same_day", None
        elif tot < 20:
            tier, basis = "too_few", None
        elif by_title:
            tier, basis = "verified", "title"
        elif share >= 0.8:
            tier, basis = "sitting_day", None
        elif share >= 0.5:
            tier, basis = "mixed", None
        else:
            tier, basis = "diffuse", None
        trust[b] = dict(n=pb["n"], dated=tot, modal_weekday=names[mw] if mw is not None else None,
                        modal_share=round(share, 4) if share is not None else None, tier=tier, verified_by=basis,
                        title_dated=pb["title_n"], title_equal=pb["title_eq"],
                        median_days=statistics.median(pb["d"]) if pb["d"] else None,
                        median_days_alt=statistics.median(pb["d_alt"]) if pb["d_alt"] else None,
                        n_durations=len(pb["d"]), n_durations_alt=len(pb["d_alt"]), rows_changed_by_alt=changed[b])
    for r in out_rows:
        r["date_trust"] = trust[r["body"]]["tier"]

    OUT.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, COLS, delimiter="\t", lineterminator="\n")
    w.writeheader()
    w.writerows(out_rows)
    with gzip.GzipFile(OUT / "interventions.tsv.gz", "wb", mtime=0) as f:
        f.write(buf.getvalue().encode("utf-8"))
    tiers = collections.Counter(t["tier"] for t in trust.values())
    rows_by_tier = collections.Counter()
    for t in trust.values():
        rows_by_tier[t["tier"]] += t["n"]
    dt_out = dict(
        definition="Per body: share of answer dates (census rule) falling on the most common weekday; >= 0.8 'sitting_day' "
                   "(a government's weekly sitting), 0.5-0.8 'mixed', < 0.5 'diffuse'; 'same_day' = the census flag (answer "
                   "event mostly on the submission date); 'verified' = OPD's answer date is the government's decision "
                   "date: Bern by the RRB date printed in the answer (verified relink rows, verified_by 'printed'), or a "
                   "body where >= 90% of dated answers carry a publisher title naming the decision date ('Risposta del CdS "
                   "del dd.mm.yyyy', 'RRB-dd.mm.yyyy') and >= 99% of those equal OPD's answer date (verified_by 'title'; "
                   "title date = date printed in the answer on 20/20 P1 held-out documents, "
                   "results/eval/posthoc_r3_gold_oracle.json); 'too_few' < 20 dated answers.",
        bern_verified=dict(date_equal=vb["by_action"]["relink"]["v2"]["date_eq_event"], n=vb["by_action"]["relink"]["v2"]["n"],
                           date_equal_v1_registered=vb["by_action"]["relink"]["v1_registered"]["date_eq_event"]),
        title_verified={b: dict(dated=t["dated"], title_dated=t["title_dated"], title_equal=t["title_equal"])
                        for b, t in sorted(trust.items()) if t["verified_by"] == "title"},
        tier_counts=dict(tiers), interventions_by_tier=dict(rows_by_tier), bodies=trust)
    (OUT / "date_trust.json").write_text(json.dumps(dt_out, indent=1, ensure_ascii=False))
    alt = dict(
        rule="answer_date_alt: earliest harmonised 'Beantwortet' (id 6) written-answer event if any, else the census rule "
             "(earliest written-answer event)",
        rows=len(out_rows), rows_changed=sum(changed.values()),
        not_attached=len(missing), source_url_filled=sum(1 for r in out_rows if r["source_url"]),
        bodies={b: dict(changed=changed[b], median_days=t["median_days"], median_days_alt=t["median_days_alt"],
                        n=t["n_durations"], n_alt=t["n_durations_alt"])
                for b, t in sorted(trust.items()) if changed[b]},
        national=dict(median_days=statistics.median([d for t in per_body.values() for d in t["d"]]),
                      median_days_alt=statistics.median([d for t in per_body.values() for d in t["d_alt"]])))
    (OUT / "answer_rule_alt.json").write_text(json.dumps(alt, indent=1, ensure_ascii=False))
    return dict(rows=len(out_rows), changed=sum(changed.values()), size=(OUT / "interventions.tsv.gz").stat().st_size,
                tiers=dict(tiers))


def load(path: Path | None = None) -> list[dict]:
    with gzip.open(path or OUT / "interventions.tsv.gz", "rt", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
