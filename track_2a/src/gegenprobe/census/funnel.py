"""National answer funnel and per-affair answer-link status, computed from the compact census tables.

Definitions (frozen; ported from spikes/recovery/scripts/funnel.py, see docs/census.md §1):
  ev_answer        written-answer event: harmonised 'Beantwortet'/'Beantwortung' or an answer-pattern title, minus referrals
  ev_oral_only     only oral answer events (Fragestunde, 'mündlich', ...)
  doc_answer       answer-named/-headed document attached to the affair; doc_answer_txt: with usable text (ok, >= 200 chars)
  text_answer      answer row in the `texts` export (>= 50 chars, not a placeholder)
  gap              ev_answer and no answer text (doc or texts);  gap' (gap_after_agenda_join): also none via agenda items

Answer-link status (new schema field `answer_link_status`), for in-scope affairs:
  attached    answer text in OPD on the affair (document or texts export)      agenda   answer document under an agenda item
  -- the rest only where a written answer is expected (ev_answer) --
  parentless  BE: the canton's answer document is in OPD with no affair/agenda/meeting (joinable by canton uid)
  oral        VS `_ANT` 87-char stub "réponse orale"; or question time (Fragestunde, heure des questions, question orale)
              with no answer document anywhere in OPD and no event saying the answer was written (defs.is_question_time;
              the answer is in the session minutes); or only oral answer events, no written answer expected
  image_only  an answer document is attached but OPD holds no usable text (re-fetch of 30 sampled: 15 image-only scans,
              13 VS oral pointers with a text layer, 2 other; results/repair/ocr_probe.json)
  absent      no answer document in OPD
  not_applicable  no answer event and no answer text

usage: python -m gegenprobe.census.funnel [--data data/census] [--out results/census]
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from ..paths import RESULTS
from . import defs
from .tables import CENSUS, i, rows

OUT = RESULTS / "census"
FLAG_BITS = {k: 1 << n for n, k in enumerate(defs.TEXT_FLAGS)}
FIELDS = [
    "n",
    "ev_answer",
    "ev_oral_only",
    "doc_answer",
    "doc_answer_txt",
    "text_answer",
    "any_answer_txt",
    "gap",
    "gap_doc_present_no_text",
    "agenda_answer_txt",
    "gap_after_agenda_join",
]
LINK_STATUSES = ["attached", "agenda", "parentless", "oral", "image_only", "absent", "not_applicable"]
VS_ANT = re.compile(r"_ANT\b")


def flags_of(bits: int) -> list[str]:
    return [k for k, b in FLAG_BITS.items() if bits & b]


def scope_affairs(root: Path = CENSUS) -> dict[int, dict]:
    aff = {}
    for a in rows("affairs", root):
        if a["type_h"] not in defs.SCOPE_TYPES:
            continue
        y, ys = defs.year_of(a["number"], a["begin"])
        aff[int(a["id"])] = dict(
            b=a["body"],
            t=a["type_h"],
            y=y,
            ys=ys,
            num=a["number"],
            ext=a["ext"],
            begin=a["begin"],
            qt=defs.is_question_time(a["type_h"], a["type_raw"]),
            ev_w=False,
            ev_w_explicit=False,
            ev_oral=False,
            dA=False,
            dAt=False,
            gA=False,
            gAt=False,
            tA=False,
            vs_stub=False,
            ans_date=None,
            sub_date=None,
        )
    return aff


def compute(root: Path = CENSUS) -> tuple[dict, dict]:
    """Return (results, per-affair records)."""
    aff = scope_affairs(root)
    for e in rows("events", root):
        x = aff.get(int(e["affair"]))
        if x is None:
            continue
        hid = i(e["hid"])
        k = defs.classify_event(e["title"], hid)
        if k == "oral":
            x["ev_oral"] = True
        elif k == "written":
            x["ev_w"] = True
            x["ev_w_explicit"] |= bool(defs.WRITTEN_EXPLICIT.search(e["title"]))
            if e["date"] and (x["ans_date"] is None or e["date"] < x["ans_date"]):
                x["ans_date"] = e["date"]
        if hid in (1, 56, 67) and e["date"] and (x["sub_date"] is None or e["date"] < x["sub_date"]):
            x["sub_date"] = e["date"]

    ag2aff = {int(g["id"]): int(g["affair"]) for g in rows("agendas", root)}
    docstat = collections.defaultdict(collections.Counter)
    be_parentless_uid: dict[str, dict] = {}
    parentless_by_body = collections.Counter()
    for d in rows("docs", root):
        st, n = d["status"], int(d["n"])
        docstat[d["body"]][st] += 1
        docstat[d["body"]]["_n"] += 1
        a, ag = i(d["affair"]), i(d["agenda"])
        if a is None and ag is None and d["meeting"] == "0":
            parentless_by_body[d["body"]] += 1
            if d["be_uid"]:
                be_parentless_uid.setdefault(d["be_uid"], dict(id=int(d["id"]), usable=st == "ok" and n >= defs.MIN_DOC_CHARS))
        via = False
        x = aff.get(a)
        if x is None and a is None and ag in ag2aff:
            x = aff.get(ag2aff[ag])
            via = True
        if x is None:
            continue
        if defs.is_answer_doc(d["name"], d["cat"], flags_of(int(d["flags"]))):
            x["gA" if via else "dA"] = True
            if st == "ok" and n >= defs.MIN_DOC_CHARS:
                x["gAt" if via else "dAt"] = True
            if (
                x["b"] == "VS"
                and VS_ANT.search(d["name"])
                and st == "ok"
                and defs.VS_ORAL_STUB_LEN[0] <= n <= defs.VS_ORAL_STUB_LEN[1]
            ):
                x["vs_stub"] = True
    for d in rows("docs_other", root):
        c = int(d["count"])
        docstat[d["body"]][d["status"]] += c
        docstat[d["body"]]["_n"] += c
        if d["affair"] == "" and d["agenda"] == "0" and d["meeting"] == "0":
            parentless_by_body[d["body"]] += c

    for t in rows("texts", root):
        x = aff.get(i(t["affair"]))
        if x is None:
            continue
        if defs.ANS_TXT_TYPE.search(t["type"] or "") and int(t["maxlen"]) >= defs.MIN_TEXT_CHARS:
            x["tA"] = True

    # BE canton OGD: affairs answered at source, and whether the canton document sits parentless in OPD
    be_src = collections.defaultdict(list)
    for r in rows("be_ogd_answers", root):
        be_src[r["geschaeft_uid"]].append(r["dokument_uid"])

    for x in aff.values():
        anyt = x["dAt"] or x["tA"]
        if anyt:
            s = "attached"
        elif x["gAt"]:
            s = "agenda"
        elif not x["ev_w"]:
            s = "oral" if x["ev_oral"] else "not_applicable"
        elif x["b"] == "BE" and any(u in be_parentless_uid for u in be_src.get(x["ext"], [])):
            s = "parentless"
        elif x["vs_stub"]:
            s = "oral"
        elif x["dA"] or x["gA"]:
            s = "image_only"
        elif x["qt"] and not x["ev_w_explicit"]:
            s = "oral"
        else:
            s = "absent"
        x["link"] = s
        x["be_src_answer"] = bool(be_src.get(x["ext"])) if x["b"] == "BE" else None

    cells = collections.defaultdict(collections.Counter)
    for x in aff.values():
        c = cells[(x["b"], x["t"], x["y"])]
        c["n"] += 1
        c["ev_answer"] += x["ev_w"]
        c["ev_oral_only"] += x["ev_oral"] and not x["ev_w"]
        c["doc_answer"] += x["dA"]
        c["doc_answer_txt"] += x["dAt"]
        c["text_answer"] += x["tA"]
        anyt = x["dAt"] or x["tA"]
        c["any_answer_txt"] += anyt
        c["gap"] += x["ev_w"] and not anyt
        c["gap_doc_present_no_text"] += x["ev_w"] and x["dA"] and not anyt
        c["agenda_answer_txt"] += x["gAt"]
        c["gap_after_agenda_join"] += x["ev_w"] and not (anyt or x["gAt"])
        c["year_from_begin"] += x["ys"] == "begin"
        c["link_" + x["link"]] += 1
    cell_rows = [
        dict(
            body=k[0],
            type=k[1],
            year=k[2],
            **{f: v.get(f, 0) for f in FIELDS + ["year_from_begin"]},
            **{"link_" + s: v.get("link_" + s, 0) for s in LINK_STATUSES},
        )
        for k, v in sorted(cells.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or 0))
    ]
    res = dict(
        cells=cell_rows,
        docstat={b: dict(sorted(c.items())) for b, c in sorted(docstat.items())},
        parentless_docs_by_body=dict(sorted(parentless_by_body.items())),
    )
    return res, aff


def aggregate(cells: list[dict], pred, key) -> dict:
    A = collections.defaultdict(collections.Counter)
    for c in cells:
        if pred(c):
            for f in FIELDS + ["link_" + s for s in LINK_STATUSES]:
                A[key(c)][f] += c.get(f, 0)
    return {k: dict(v) for k, v in sorted(A.items(), key=lambda kv: str(kv[0]))}


FOCUS = ["BE", "CHE", "ZH", "BS", "TI", "LU", "SG"]


def summarise(res: dict, aff: dict) -> dict:
    cells = res["cells"]
    nat = aggregate(cells, lambda c: True, lambda c: "ALL")["ALL"]
    nat25 = aggregate(cells, lambda c: c["year"] in (2024, 2025), lambda c: "ALL")["ALL"]
    out = dict(
        national=nat,
        national_2024_25=nat25,
        national_gap_share=nat["gap"] / nat["ev_answer"],
        national_2024_25_gap_share=nat25["gap"] / nat25["ev_answer"],
        n_bodies_in_scope=len({c["body"] for c in cells}),
        focus_all_years=aggregate(cells, lambda c: c["body"] in FOCUS, lambda c: f"{c['body']}|{c['type']}"),
        focus_2024_25=aggregate(
            cells, lambda c: c["body"] in FOCUS and c["year"] in (2024, 2025), lambda c: f"{c['body']}|{c['type']}"
        ),
        by_body=aggregate(cells, lambda c: True, lambda c: c["body"]),
        by_type=aggregate(cells, lambda c: True, lambda c: c["type"]),
        docstat_focus={b: res["docstat"].get(b) for b in FOCUS + ["JU", "VS", "GE"]},
    )
    out["agenda_rejoin_in_gap"] = nat["gap"] - nat["gap_after_agenda_join"]
    # answer-link status (written answer expected) nationally, and BE in detail
    link = collections.Counter(x["link"] for x in aff.values())
    out["link_status"] = {s: link.get(s, 0) for s in LINK_STATUSES}
    be = [x for x in aff.values() if x["b"] == "BE" and x["ev_w"]]
    out["be_link_status_written"] = dict(collections.Counter(x["link"] for x in be))
    gap_be = [x for x in aff.values() if x["b"] == "BE" and x["ev_w"] and not (x["dAt"] or x["tA"] or x["gAt"])]
    out["be_gap_prime"] = dict(
        n=len(gap_be),
        source_has_answer=sum(bool(x["be_src_answer"]) for x in gap_be),
        parentless=sum(x["link"] == "parentless" for x in gap_be),
    )
    pl = res["parentless_docs_by_body"]
    tot = sum(v["_n"] for v in res["docstat"].values())
    out["parentless_docs"] = dict(
        national=sum(pl.values()),
        national_share=sum(pl.values()) / tot,
        BE=pl.get("BE", 0),
        BE_share=pl.get("BE", 0) / res["docstat"]["BE"]["_n"],
        docs_total=tot,
    )
    # decomposition of gap' outside BE/CHE
    g = [x for x in aff.values() if x["ev_w"] and not (x["dAt"] or x["tA"] or x["gAt"])]
    out["gap_prime_decomposition"] = dict(
        BE=sum(x["b"] == "BE" for x in g),
        CHE=sum(x["b"] == "CHE" for x in g),
        other_doc_present_no_text=sum(x["b"] not in ("BE", "CHE") and (x["dA"] or x["gA"]) for x in g),
        other_vs_oral_stub=sum(x["b"] == "VS" and x["vs_stub"] for x in g),
        other_no_answer_doc=sum(x["b"] not in ("BE", "CHE") and not (x["dA"] or x["gA"]) for x in g),
        other_no_answer_doc_question_time=sum(
            x["b"] not in ("BE", "CHE") and not (x["dA"] or x["gA"]) and x["link"] == "oral" for x in g
        ),
    )
    # typed causes of the gap (written answer recorded, no answer text attached): one cause per affair
    gap = [x for x in aff.values() if x["ev_w"] and not (x["dAt"] or x["tA"])]
    out["gap_causes"] = {s: sum(x["link"] == s for x in gap) for s in LINK_STATUSES if s not in ("attached", "not_applicable")}
    oral_gap = [x for x in gap if x["link"] == "oral"]
    out["gap_oral_split"] = dict(
        vs_stub=sum(x["vs_stub"] for x in oral_gap),
        question_time=sum(not x["vs_stub"] for x in oral_gap),
        question_time_by_body=dict(collections.Counter(x["b"] for x in oral_gap if not x["vs_stub"]).most_common()),
    )
    return out


def main(root: Path = CENSUS, out: Path = OUT) -> tuple[dict, dict]:
    """Write funnel.json + summary.json; return (summary, per-affair records) so later steps reuse the records."""
    res, aff = compute(root)
    summ = summarise(res, aff)
    out.mkdir(parents=True, exist_ok=True)
    (out / "funnel.json").write_text(json.dumps(res, indent=0, sort_keys=True))
    (out / "summary.json").write_text(json.dumps(summ, indent=1, sort_keys=True))
    return summ, aff


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=CENSUS)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    s, _ = main(a.data, a.out)
    print(
        json.dumps(
            {k: s[k] for k in ("national", "national_2024_25", "link_status", "be_gap_prime", "gap_prime_decomposition")},
            indent=1,
        )
    )
