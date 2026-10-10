"""Collect the viewer's data from committed results files (and, for the documents view, the cached page texts and the
hash-keyed model cache). Every number the site prints comes from here; nothing is typed by hand.

Committed mode (default): document text appears only as excerpt windows (<= EXCERPT_MAX characters) around the spans
that matter — the gold quote, the rule's span, the pointer's choice and each candidate date's immediate context — never
the full text. `full_text=True` (local builds only, never committed) adds every page.
"""

from __future__ import annotations

import collections
import csv
import gzip
import io
import json
import math
import os
import re
import statistics
import subprocess

from .. import llm, pdftext
from ..convert import lattice, pointer, rules
from ..paths import DATA, ROOT

RESULTS = ROOT / "results"
BUILD = "publicai:swiss-ai/apertus-v1.5-8b"
EXCERPT_MAX = 280
CTX = 46  # characters either side of a candidate date in the candidate list
CELL = {
    "de_canton": ("DE", "canton"),
    "de_commune": ("DE", "commune"),
    "fr_canton": ("FR", "canton"),
    "fr_commune": ("FR", "commune"),
    "it_canton": ("IT", "canton"),
    "it_commune": ("IT", "commune"),
    "ocr_ti": ("IT", "scan · OCR"),
}


# Gold labels open to argument, shown as such in the reviewer view (the scores keep the frozen labels).
CONTESTED = {
    28271: "Government decision on its own business (a credit), not an answer to a member's affair; the two annotators split "
    "and the tie-break said 'no answer'. A decision of the same kind (300277) is labelled 'answer' because OPD links it "
    "to an affair.",
    862297: "Government report on its own ordinance; it mentions an earlier answer but answers no affair here. The annotators "
    "split; the tie-break said 'no answer'.",
    300277: "Government decision on its own business (a flood-protection credit). Labelled 'answer' because OPD links it to an "
    "affair; two similar decisions (28271, 862297) are labelled 'no answer'.",
}


class _Replay(llm._Remote):
    """Replay-only view of the committed model cache (no network, no gateway, no key)."""

    def __init__(self):
        super().__init__("swiss-ai/apertus-v1.5-8b", build=BUILD, cache_readonly=True)
        self.offline = True

    def _post(self, payload):  # pragma: no cover - offline by construction
        raise llm.CacheMiss("replay only")


def _j(p):
    return json.loads((RESULTS / p).read_text()) if not str(p).startswith("/") else json.loads(open(p).read())


def _tsv_gz(name):
    with gzip.open(DATA / "census" / f"{name}.tsv.gz", "rb") as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def excerpt(text: str, s: int, e: int, width: int = EXCERPT_MAX) -> dict:
    """A window around [s, e) of at most `width` characters, whitespace collapsed, with the span's position inside it.
    Returns {t: text, a: span start in t, b: span end in t, o: absolute char offset of the window start}."""
    pad = max(0, (width - (e - s)) // 2)
    lo, hi = max(0, s - pad), min(len(text), e + pad)
    if lo > 0:  # start on a word boundary
        sp = text.find(" ", lo, s)
        lo = sp + 1 if sp != -1 else lo
    if hi < len(text):
        sp = text.rfind(" ", e, hi)
        hi = sp if sp != -1 else hi
    before, mid, after = _ws(text[lo:s]), _ws(text[s:e]), _ws(text[e:hi])
    t = (before + " " if before else "") + mid + (" " + after if after else "")
    a = len(before) + (1 if before else 0)
    t = t[:width]
    return dict(t=t, a=a, b=min(len(t), a + len(mid)), o=lo, lead=lo > 0, tail=hi < len(text))


def _ctx(text: str, s: int, e: int) -> dict:
    return excerpt(text, s, e, width=(e - s) + 2 * CTX)


def _lang(d: dict) -> str:
    # exactly the frozen eval.arms.load_split + _lang mapping (ocr_ti -> de; deviation D1)
    lg = d.get("lang") or {"it": "it", "fr": "fr"}.get(d["cell"][:2], "de")
    return lg if lg in ("de", "fr", "it") else {"fr": "fr", "it": "it", "oc": "it"}.get(d["cell"][:2], "de")


def _outcome(pred, gold, doc_dates, lenient):
    from eval.score import outcome

    return outcome(pred, gold, set(doc_dates), lenient, True)


def _find_quote(pages: list[str], page: int | None, quote: str, value: str | None, cands: list[dict]):
    """Locate the gold label: the candidate with the gold value on the labelled page nearest the verbatim quote."""
    if not value:
        return None
    occ = [c for c in cands if c["value"] == value]
    if not occ:
        return None
    if page:
        on = [c for c in occ if c["page"] == page] or occ
        q = _ws(quote)[:40]
        txt = pages[on[0]["page"] - 1]
        pos = _ws(txt).find(q) if q else -1
        if pos >= 0:
            on.sort(key=lambda c: abs(len(_ws(txt[: c["char_start"]])) - pos))
        return on[0]
    return occ[0]


def documents(full_text: bool = False) -> list[dict]:
    docs = {d["doc_id"]: d for d in map(json.loads, open(DATA / "gold" / "heldout_docs.jsonl"))}
    labels = {r["doc_id"]: r for r in map(json.loads, open(DATA / "gold" / "heldout_labels.jsonl"))}
    res = _j("eval/heldout__publicai_swiss-ai_apertus-v1.5-8b.json")
    theta = res["theta"]
    be = _Replay()
    bodies = body_names()
    out = []
    for r in res["per_doc"]:
        d, lab = docs[r["doc_id"]], labels[r["doc_id"]]
        t = pdftext.extract(d["sha256"], ocr=d.get("image_only", False))
        pages = t["pages"]
        cands = lattice.dates(pages)
        anch = rules.anchors(pages)
        try:
            p = pointer.answer_date(be, pages, _lang(d), math.inf, anchors=anch)
            lps = dict(p.candidates)
            lp_null, margin = p.lp_null, p.margin
        except llm.CacheMiss:
            lps, lp_null, margin = {}, None, None
        # candidate list: one row per distinct date (first occurrence, or nearest an answer anchor), with its score
        seen, crow = set(), []
        for v in lattice.distinct_dates(
            [c for c in cands if pointer._visible(c, pointer.doc_text(pages)[1], pointer.CHAR_BUDGET)]
        ):
            loc = pointer.locate(v, cands, pages, anch) or {}
            c = next(
                (
                    c
                    for c in cands
                    if c["value"] == v and c["page"] == loc.get("page") and c["char_start"] == loc.get("char_start")
                ),
                next(c for c in cands if c["value"] == v),
            )
            if v in seen:
                continue
            seen.add(v)
            crow.append(
                dict(
                    v=v,
                    lp=lps.get(v),
                    page=c["page"],
                    s=c["char_start"],
                    e=c["char_end"],
                    x=_ctx(pages[c["page"] - 1], c["char_start"], c["char_end"]),
                )
            )
        crow.sort(key=lambda x: -(x["lp"] if x["lp"] is not None else -1e9))
        n_cands = len(crow)
        crow = crow[:10]

        def span_of(value, prefer=None, cands=cands, pages=pages):
            if not value:
                return None
            c = prefer or next((c for c in cands if c["value"] == value), None)
            if not c:
                return None
            return dict(
                page=c["page"],
                s=c["char_start"],
                e=c["char_end"],
                x=excerpt(pages[c["page"] - 1], c["char_start"], c["char_end"]),
            )

        gold_c = _find_quote(pages, lab.get("answer_date_page"), lab.get("answer_date_quote") or "", lab["answer_date"], cands)
        rr = r["rules"]
        rspan = None
        if rr["status"] == "value":
            rv = rules.answer_date(pages, t["image_only"])
            sp = rv.get("span") or {}
            if sp.get("page"):
                rspan = dict(
                    page=sp["page"],
                    s=sp["char_start"],
                    e=sp["char_end"],
                    x=excerpt(pages[sp["page"] - 1], sp["char_start"], sp["char_end"]),
                )
        pv = r["pointer"].get("value")
        ploc = pointer.locate(pv, cands, pages, anch) if pv else None
        pc = next((c for c in cands if ploc and c["page"] == ploc["page"] and c["char_start"] == ploc["char_start"]), None)
        sugg = r["cascade"]["value"] if r["cascade"].get("route") == "apertus" else None
        naive = {}
        for arm in ("naive_plain", "naive_null"):
            v = r[arm].get("date")
            v = None if (v is None or str(v).startswith("unparseable")) else v
            naive[arm] = dict(
                v=v,
                o=_outcome(v, r["gold"], r["doc_dates"], r["lenient"]),
                in_doc=v in r["doc_dates"] if v else None,
                receipt_ok=r[arm].get("receipt_ok"),
            )
        lang, level = CELL[d["cell"]]
        rec = dict(
            id=d["doc_id"],
            cell=d["cell"],
            lang=lang,
            level=level,
            body=d["body"],
            body_name=bodies.get(d["body"], d["body"]),
            affair=d.get("affair_id"),
            affair_type=d.get("affair_type"),
            dtype=d["dtype"],
            name=d.get("name"),
            url=d["url"],
            sha=d["sha256"],
            pages=len(pages),
            chars=sum(map(len, pages)),
            image_only=t["image_only"],
            extractor=t["extractor"],
            gold=dict(
                v=lab["answer_date"],
                role=lab.get("role"),
                present=lab.get("answer_present"),
                lenient=lab.get("answer_date_lenient") or [],
                by=lab.get("labeller"),
                span=span_of(lab["answer_date"], gold_c),
            ),
            rules=dict(
                status=rr["status"],
                v=rr.get("value"),
                rule=rr.get("rule"),
                span=rspan,
                o=_outcome(rr.get("value"), r["gold"], r["doc_dates"], r["lenient"]),
            ),
            pointer=dict(
                v=pv,
                margin=margin if margin is not None else r["pointer"].get("margin"),
                theta=theta,
                lp_null=lp_null,
                span=span_of(pv, pc),
                n=n_cands,
                cands=crow,
                truncated=r["pointer"].get("truncated"),
                o=_outcome(pv, r["gold"], r["doc_dates"], r["lenient"]),
            ),
            review=dict(
                v=sugg,
                needs_review=sugg is not None,
                o=_outcome(r["cascade"].get("value"), r["gold"], r["doc_dates"], r["lenient"]),
            ),
            naive=naive,
            contested=CONTESTED.get(d["doc_id"]),
        )
        if full_text:
            rec["text"] = pages
        out.append(rec)
    out.sort(key=lambda x: (x["cell"], x["body"], x["id"]))
    return out


def body_names() -> dict[str, str]:
    names = {b["key"]: b["name"] for b in _tsv_gz("bodies")}
    for b in _j("census/question.json")["bodies"]:
        names[b["body"]] = b["name"]
    return names


# One denominator for every per-body number: interventions whose events record a WRITTEN government answer (the census
# funnel's ev_w). Each of them has exactly one answer-link status, so the parts below always sum to `written`.
LINKS = ("attached", "agenda", "parentless", "image_only", "oral", "absent")
PERIODS = {"all": (None, None), "since2015": (2015, None), "y2425": (2024, 2025)}
PERIOD_LABEL = {"all": "all years", "since2015": "since 2015", "y2425": "2024–25"}


# Canton names on this English page: the canton's official name in the language of its majority (OPD labels every canton
# in German: 'Tessin', 'Genf', 'Waadt' ...). Cities and communes keep OPD's name, which is already the local one (Lugano,
# Neuchâtel, Genève). OPD's German name stays searchable (row 'alt').
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


def label_of(key: str, name: str, btype: str | None) -> tuple[str, str]:
    """(display label, level): 'Bern (canton)' vs 'Bern (city)'; cantons by CANTON_NAME, other bodies by OPD's name."""
    if key == "CHE":
        return "Federal Assembly", "federal"
    if key == "LIE":
        return "Liechtenstein (Landtag)", "country"
    level = {"canton": "canton", "city": "city", "municipality": "municipality"}.get(btype or "", btype or "")
    if level == "canton":
        name = CANTON_NAME.get(key, name)
    return (f"{name} ({level})" if level else name), level


def _in(y, period: str) -> bool:
    lo, hi = PERIODS[period]
    if lo is None:
        return True
    return y is not None and y >= lo and (hi is None or y <= hi)


def _partition(per_affair: dict) -> dict:
    """body -> period -> {written, attached, agenda, parentless, image_only, oral, absent} over written-answer affairs."""
    out = collections.defaultdict(lambda: {p: dict(written=0, **{k: 0 for k in LINKS}) for p in PERIODS})
    for x in per_affair.values():
        if not x["ev_w"]:
            continue
        for p in PERIODS:
            if _in(x["y"], p):
                c = out[x["b"]][p]
                c["written"] += 1
                c[x["link"]] += 1
    for b, per in out.items():
        for p, c in per.items():
            assert sum(c[k] for k in LINKS) == c["written"], (b, p, c)
    return out


def _snapshot() -> str:
    m = json.loads((DATA / "census" / "meta.json").read_text())
    days = sorted(
        {v["mtime"][:10] for k, v in m["inputs"].items() if isinstance(v, dict) and "mtime" in v and k != "contributors"}
    )
    created = m["inputs"].get("index.json", {}).get("generated_at", "")[:10]
    return created or (days[0] if days else "")


def _pc(k: int, n: int) -> str:
    v = 100 * k / n
    return "under 1%" if 0 < v < 1 else f"{v:.0f}%"


COVERAGE_MIN = 20  # written-answer events needed before a body's answer numbers mean anything (the same 20 as elsewhere)
COVERAGE_SHARE = 0.1  # ... and below this share of the body's in-scope interventions, a coverage gap rather than a small body


def coverage_of(n_in_scope: int, written: int) -> str:
    """measured: >= 20 written-answer events (all years). coverage_gap: OPD holds >= 20 in-scope interventions but records a
    written government answer for fewer than 20 of them and for under 10% of them, so the answer question cannot be asked of
    OPD for this body (a gap in the aggregator's coverage of answer events, not evidence about the parliament). few: the
    rest with fewer than 20 written answers.
    no_affairs: no in-scope interventions (the body publishes meeting documents only)."""
    if written >= COVERAGE_MIN:
        return "measured"
    if n_in_scope == 0:
        return "no_affairs"
    return "coverage_gap" if n_in_scope >= COVERAGE_MIN and written < COVERAGE_SHARE * n_in_scope else "few"


def safe_say(r: dict) -> str:
    """One sentence a journalist can quote, with its caveat, generated from the row (never typed by hand)."""
    a, n = r["periods"]["all"], r["periods"]["y2425"]
    cov = r.get("coverage") or coverage_of(r["n"], a["written"])
    if cov == "no_affairs":
        return ("OpenParlData holds no interventions of the census types for this parliament (only meeting documents), so "
                "nothing can be said about its answers from OPD.")
    if cov == "coverage_gap":
        return (f"OpenParlData holds {r['n']:,} interventions for this parliament but records a written government answer for "
                f"{'none' if a['written'] == 0 else a['written']} of them: a gap in OPD's coverage of answers, not evidence that "
                "the parliament leaves questions unanswered; ask OPD and the parliament before writing about it.")
    if cov == "few":
        return f"Too few written answers in OPD ({a['written']}) to say anything about this parliament."
    miss = lambda c: c["written"] - c["attached"]  # noqa: E731
    out = []
    pick = n if n["written"] >= 20 else a
    yrs = r.get("years")
    allw = f"over all years OPD holds ({yrs[0]}–{yrs[1]})" if yrs else "over all years"
    if n["written"] >= 20:
        out.append(
            f"In 2024–25, {miss(n):,} of {n['written']:,} written government answers ({_pc(miss(n), n['written'])}) have no "
            f"answer text attached in OpenParlData"
        )
        if abs(miss(a) / a["written"] - miss(n) / n["written"]) > 0.15:
            out.append(
                f"{allw} it is {100 * miss(a) / a['written']:.0f}%, so older interventions dominate the all-years figure"
            )
    else:
        out.append(
            f"{allw[0].upper() + allw[1:]}, {miss(a):,} of {a['written']:,} written answers ({_pc(miss(a), a['written'])}) "
            "have no answer text "
            f"attached in OpenParlData; 2024–25 has too few to compare"
        )
    # oral answers (question time, VS oral-answer stubs) first, in the period quoted: they are not missing
    mp = miss(pick)
    oral_said = False
    if mp >= 5 and pick["oral"] >= 0.3 * mp:
        oral_said = True
        what = "an oral-answer note filed in place of a text" if r["key"] == "VS" else "question time"
        rest, base = mp - pick["oral"], pick["written"] - pick["oral"]
        lead = "all of these" if pick["oral"] == mp else f"{pick['oral']:,} of these {mp:,}"
        out.append(
            f"{lead} were answered orally in the sitting ({what}), so they are not missing"
            + (": every answer given in writing has its text attached" if rest == 0 else
               f"; of the {base:,} answers given in writing, {rest:,} ({_pc(rest, base)}) lack text")
        )
    m = max(1, miss(a) - (a["oral"] if oral_said else 0))
    the = "the other" if oral_said else "the"
    if m < 20:
        pass
    elif a["parentless"] + a["agenda"] > 0.5 * m:
        out.append(
            f"most of {the} missing answers are in OpenParlData but not linked to their intervention, an aggregator issue "
            "that OPD has confirmed, not the parliament's"
        )
    elif a["oral"] > 0.3 * m and not oral_said:
        out.append("many 'missing' answers were given orally, so they are not missing")
    elif a["image_only"] > 0.3 * m:
        out.append(f"most of {the} missing answers are documents whose copy in OPD has no text: OCR would recover them "
                   "(not yet run on all of them), and where the parliament publishes a text PDF or a Word file, OPD can "
                   "re-take that instead")
    elif a["absent"] > 0.5 * m:
        out.append(f"{the} missing answers are not in OpenParlData; whether the parliament publishes them elsewhere was not "
                   "checked")
    if r["median"]["flag"] == "same_day":
        out.append("its 'answer' dates in OPD mostly equal submission dates, so answer times cannot be computed")
    return "; ".join(out) + "."


def parliaments() -> dict:
    from ..census import funnel

    s = _j("census/summary.json")
    q = {b["body"]: b for b in _j("census/question.json")["bodies"]}
    same_day = {b["body"] for b in _j("census/question.json")["same_day_bodies"]}
    rep = _j("repair/summary.json")["by_body"]
    m = _j("census/matrix.json")
    bodies_meta = {b["key"]: b for b in _tsv_gz("bodies")}
    names = body_names()
    cells = collections.defaultdict(dict)
    for c in m["cells"]:
        cells[c["body"]][c["field"]] = dict(st=c["status"], r=c["route"], meta=c["meta"], doc=c["doc"], n=c["n"])
    _, per_affair = funnel.compute()
    part = _partition(per_affair)
    fetch = {b: rep.get(b, {}).get("fetch", 0) for b in rep}
    rows = []
    for k in sorted(set(s["by_body"]) | set(cells)):
        bm = bodies_meta.get(k, {})
        label, level = label_of(k, names.get(k, k), bm.get("type"))
        qq = q.get(k, {})
        periods = {}
        for p in PERIODS:
            c = dict(part[k][p]) if k in part else dict(written=0, **{x: 0 for x in LINKS})
            c["missing"] = c["written"] - c["attached"]
            c["with_text"] = c["attached"] / c["written"] if c["written"] else None
            # repair routes that put text back: agenda join, BE parentless relink, BE fetch from the canton (its 49 absent
            # answers are all on the canton's list); OCR candidates and oral retypes are typed, not counted as text
            f = min(fetch.get(k, 0), c["absent"]) if p == "all" else (c["absent"] if k == "BE" else 0)
            c["fetchable"] = f
            c["after_repair"] = (c["attached"] + c["agenda"] + c["parentless"] + f) / c["written"] if c["written"] else None
            periods[p] = c
        flag = "same_day" if k in same_day else ("few" if qq.get("n_durations", 0) < 20 else None)
        rows.append(
            dict(
                key=k,
                name=names.get(k, k),
                label=label,
                alt=names.get(k, k) if not label.startswith(names.get(k, k) + " (") else None,
                level=level,
                canton=bm.get("canton") or (k if len(k) == 2 else ""),
                lang=bm.get("lang"),
                n=s["by_body"].get(k, {}).get("n", 0),
                periods=periods,
                median=dict(
                    days=None if flag else qq.get("median_days"),
                    raw=qq.get("median_days"),
                    q1=qq.get("q1_days"),
                    q3=qq.get("q3_days"),
                    n=qq.get("n_durations"),
                    same_day_share=qq.get("same_day_share"),
                    flag=flag,
                ),
                repair=rep.get(k, {}),
                fields=cells.get(k, {}),
                in_scope=k in s["by_body"],
            )
        )
    extras = research_extras()
    for r in rows:
        ex = extras["bodies"].get(r["key"], {})
        r["coverage"] = coverage_of(r["n"], r["periods"]["all"]["written"])
        # answer times within one intervention type, per period (census rule; n >= 10; IQR); hidden for same-day bodies
        r["times"] = {} if r["median"]["flag"] == "same_day" else ex.get("times", {})
        r["median"]["days_alt"] = ex.get("median_alt")
        r["trust"] = extras["trust"].get(r["key"], {})
        r["years"] = ex.get("years")  # [first, last] year of the body's written-answer interventions in OPD
        r["main_type"] = ex.get("main_type", {}) if r["median"]["flag"] != "same_day" else {}
        for c in r["periods"].values():
            c["after_ocr"] = ((c["attached"] + c["agenda"] + c["parentless"] + c["fetchable"] + c["image_only"]) / c["written"]
                              if c["written"] else None)
        r["safe_say"] = safe_say(r)
        r["safe_say_period"] = "2024–25 and all years" if r["periods"]["y2425"]["written"] >= 20 else "all years"
    rows.sort(key=lambda r: (-r["periods"]["all"]["written"], -r["n"]))
    # Bern, by the canton's own list (a different denominator, shown only in Bern's detail panel; same numbers as fig. 3)
    rc = _j("repair/be_reconcile.json")
    bern = dict(
        canton_listed=rc["source_answered"],
        placement=rc["placement"],
        linkable=rc["linkable_within_opd"],
        parentless_breakdown=rc["parentless_breakdown"],
        relink_list=rc["relink_list"],
    )
    fields = [
        dict(
            key=k,
            tier=f["tier"],
            route=f["extraction_route"],
            eligible=f["eligible_bodies"],
            counts=f["status_counts"],
            meta=f["pooled_meta"],
            note=f.get("note", ""),
        )
        for k, f in m["fields"].items()
    ]
    fj = _j("census/findings.json")
    findings = [
        dict(
            id=f["id"],
            statement=f["statement"],
            count=f.get("count"),
            denominator=f.get("denominator"),
            share=f.get("share"),
            definition=f.get("definition"),
            status=(f.get("opd_response") or {}).get("status"),
            opd=(f.get("opd_response") or {}).get("summary"),
        )
        for f in fj["findings"]
    ]
    nat = {
        p: dict(written=sum(r["periods"][p]["written"] for r in rows), attached=sum(r["periods"][p]["attached"] for r in rows))
        for p in PERIODS
    }
    return dict(
        rows=rows,
        fields=fields,
        national=s["national"],
        national_periods=nat,
        gap_share=s["national_gap_share"],
        decomposition=s["gap_prime_decomposition"],
        question=_j("census/question.json")["national"],
        same_day=[dict(b, label=next((r["label"] for r in rows if r["key"] == b["body"]), b["name"]))
                  for b in _j("census/question.json")["same_day_bodies"]],
        canton_rule=CANTON_RULE,
        source_formats=_source_formats(),
        tier_counts=m["tier_counts"],
        criteria=m["criteria"],
        repair=_j("repair/summary.json")["by_action"],
        findings=findings,
        attribution=fj.get("opd_attribution"),
        bern=bern,
        snapshot=_snapshot(),
        n_bodies=len(rows),
        periods=PERIOD_LABEL,
        bern_numbers=bern_numbers(rows),
        coverage=dict(
            definition="coverage gap: OPD holds >= 20 in-scope interventions for the body but records a written "
            "government answer for fewer than 20 of them and for under 10% of them (all years); no_affairs: no in-scope "
            "interventions; few: the rest with fewer than 20 written answers",
            gaps=[dict(key=r["key"], label=r["label"], level=r["level"], n=r["n"], written=r["periods"]["all"]["written"])
                  for r in sorted(rows, key=lambda r: -r["n"]) if r["coverage"] == "coverage_gap"],
            counts=dict(collections.Counter(r["coverage"] for r in rows)),
        ),
        types=list(TYPE_ORDER),
        missing={k: v["missing"] for k, v in extras["bodies"].items()},  # split off into site/missing.json by `collect`
        research=extras["meta"],
    )


TIMES_MIN = 10  # durations needed for a per-type median
TYPE_ORDER = ("Interpellation", "Question", "Motion", "Postulate", "Question time")  # the site's type selector
LINK_CODE = {"agenda": "a", "parentless": "p", "image_only": "s", "oral": "o", "absent": "x"}


def research_extras() -> dict:
    """Per-body extras from the research dataset (results/census/interventions.tsv.gz, census/interventions.py): the
    affairs whose answer text is not attached ([number, affair id, link code, year, source url minus the body's common
    prefix]; shipped as site/missing.json, loaded when a row is opened), median days by intervention type
    (n >= 10, census rule), the alternative-rule median, and the date-trust tier (results/census/date_trust.json)."""
    from ..census import interventions as iv

    p = RESULTS / "census" / "interventions.tsv.gz"
    trust = json.loads((RESULTS / "census" / "date_trust.json").read_text())
    if not p.exists():
        return dict(bodies={}, trust={}, meta=None)
    bodies: dict = collections.defaultdict(lambda: dict(missing=[], days=collections.defaultdict(list), years=[]))
    for r in iv.load(p):
        b = bodies[r["body"]]
        if r["year"]:
            b["years"].append(int(r["year"]))
        if r["link_status"] != "attached":
            b["missing"].append([r["number"], int(r["affair_id"]), LINK_CODE.get(r["link_status"], "x"),
                                 int(r["year"]) if r["year"] else None, r["source_url"]])
        if r["days_to_answer"] != "":
            y = int(r["year"]) if r["year"] else None
            for per in PERIODS:
                if _in(y, per):
                    b["days"][(per, r["type"])].append(int(r["days_to_answer"]))
    out = {}
    for k, b in bodies.items():
        times: dict = {}
        for (per, t), v in sorted(b["days"].items()):
            if len(v) >= TIMES_MIN:
                q = statistics.quantiles(v, n=4)
                times.setdefault(per, {})[t] = dict(median=statistics.median(v), q1=q[0], q3=q[2], n=len(v))
        b["missing"].sort(key=lambda m: (-(m[3] or 0), m[0]))
        # a source url shared by several affairs is the parliament's list page, not the affair's own page (Lugano: every
        # affair points at one 'Mozioni' page); flagged per row as a 6th element (1 = list page)
        shared = collections.Counter(m[4] for m in b["missing"] if m[4])
        for m in b["missing"]:
            m.append(1 if m[4] and shared[m[4]] > 1 else 0)
        pre = os.path.commonprefix([m[4] for m in b["missing"] if m[4]]) if b["missing"] else ""
        for m in b["missing"]:
            m[4] = m[4][len(pre):] if m[4] else None
        # the intervention type with the most dated answers, per period (the answer-time default for this parliament)
        main = {per: max(ts, key=lambda t: (ts[t]["n"], t == "Interpellation")) for per, ts in times.items() if ts}
        out[k] = dict(missing=dict(prefix=pre, rows=b["missing"]), times=times, main_type=main,
                      years=[min(b["years"]), max(b["years"])] if b["years"] else None,
                      median_alt=trust["bodies"].get(k, {}).get("median_days_alt"))
    alt = json.loads((RESULTS / "census" / "answer_rule_alt.json").read_text())
    meta = dict(rows=alt["rows"], rows_changed_alt=alt["rows_changed"], tier_counts=trust["tier_counts"],
                interventions_by_tier=trust["interventions_by_tier"], bern_verified=trust["bern_verified"],
                title_verified=trust.get("title_verified", {}), title_oracle=_title_oracle(),
                schaffhausen=alt["bodies"].get("SH"), download="interventions.tsv.gz", readme="interventions_README.md",
                opd_url="https://openparldata.ch/item/affairs/{id}")
    return dict(bodies=out, trust={k: dict(tier=v["tier"], modal_weekday=v["modal_weekday"], modal_share=v["modal_share"],
                                           by=v.get("verified_by"), title_dated=v.get("title_dated"),
                                           title_equal=v.get("title_equal"), dated=v.get("dated"))
                                   for k, v in trust["bodies"].items()}, meta=meta)


def _source_formats() -> dict:
    """Spot check of the answer files a parliament publishes vs OPD's copies (census/source_formats.py; network, committed)."""
    p = RESULTS / "census" / "source_formats_ti.json"
    if not p.exists():
        return {}
    j = json.loads(p.read_text())
    return {"TI": [dict(atto=a["atto"], page=a["page"], affair=a["affair"], checked=j["checked"],
                        files=[f["filename"] for f in a["source_answer_files"]], opd_copies=a["opd_answer_copies"],
                        opd_with_text=a["opd_answer_copies_with_text"]) for a in j["attos"]]}


def _title_oracle() -> dict | None:
    """P1 held-out gold answer dates vs the publisher's answer title (post hoc, non-LLM; all 20 are Ticino documents)."""
    p = RESULTS / "eval" / "posthoc_r3_gold_oracle.json"
    if not p.exists():
        return None
    t = json.loads(p.read_text())["splits"]["P1"]["answer_date_vs_publisher_title_date"]
    return dict(agree=t["agree"], checked=t["checked"])


def bern_numbers(rows: list[dict]) -> list[dict]:
    """Every Bern number on the site and in the report with its denominator, in one place (U2/U3/J4: 'they don't match')."""
    rc = _j("repair/be_reconcile.json")
    be = next(r for r in rows if r["key"] == "BE")
    pl, pb, rl = rc["placement"], rc["parentless_breakdown"], rc["relink_list"]
    n = rc["source_answered"]
    out = [
        dict(v=n, what="answers the canton lists in its own open data (dokument.csv)", base="the canton's list"),
        dict(v=pl["attached"], what="of them attached to their intervention in OPD",
             base=f"of {n:,} ({100 * pl['attached'] / n:.1f}%)"),
        dict(v=n - pl["attached"], what="not attached to their intervention (the confirmed OPD bug)", base=f"of {n:,}"),
        dict(v=pl["via_agenda"], what="filed in OPD under an agenda item", base=f"of {n:,}"),
        dict(v=pl["parentless"], what="in OPD as documents without any parent", base=f"of {n:,}"),
        dict(v=pl["absent"], what="not in OPD at all (fetch from the canton)", base=f"of {n:,}"),
        dict(v=rc["linkable_within_opd"], what="linkable within OPD (attached + agenda + parentless)",
             base=f"of {n:,} ({100 * rc['linkable_within_opd'] / n:.1f}%)"),
        dict(v=rl["relink"], what="parentless answers in the relink list: interventions in the census gap",
             base=f"of {pl['parentless']:,} parentless"),
        dict(v=rl["fetch"], what="answers to fetch from the canton for interventions in the gap",
             base=f"of {pl['absent']:,} absent"),
    ]
    for k, v in pb.items():
        if not k.startswith("in the relink list") and isinstance(v, int):
            out.append(dict(v=v, what=f"parentless answers not in the list: {k}", base=f"of {pl['parentless']:,} parentless"))
    for per in ("all", "since2015", "y2425"):
        c = be["periods"][per]
        lab = PERIOD_LABEL[per]
        out.append(dict(v=c["written"], what=f"Bern interventions with a written-answer event ({lab}): the table's denominator",
                        base="OPD events, not the canton's list"))
        out.append(dict(v=c["missing"], what=f"of them without attached answer text ({lab})", base=f"of {c['written']:,}"))
    return out


def write_csv(par: dict, path) -> None:
    """The Parliaments table as CSV (one row per body; columns per period), for journalists and OPD."""
    cols = ["key", "label", "level", "canton"]
    per_cols = [
        "written",
        "attached",
        "agenda",
        "parentless",
        "image_only",
        "oral",
        "absent",
        "missing",
        "with_text",
        "after_repair",
    ]
    head = (cols + [f"{p}_{c}" for p in PERIODS for c in per_cols] + ["median_days", "median_flag", "safe_to_say", "coverage"]
            + [f"{p}_median_days_interpellation" for p in PERIODS]
            + ["first_year", "last_year", "all_main_type", "all_median_days_main_type", "date_trust", "date_verified_by"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(head)
        for r in par["rows"]:
            vals = [r[c] for c in cols]
            for p in PERIODS:
                c = r["periods"][p]
                vals += [round(c[x], 4) if isinstance(c[x], float) else c[x] for x in per_cols]
            ti = [r["times"].get(p, {}).get("Interpellation", {}).get("median", "") for p in PERIODS]
            yrs, mt = r.get("years") or ["", ""], (r.get("main_type") or {}).get("all", "")
            w.writerow(vals + [r["median"]["days"], r["median"]["flag"] or "", r["safe_say"], r["coverage"]] + ti
                       + [yrs[0], yrs[1], mt, r["times"].get("all", {}).get(mt, {}).get("median", "") if mt else "",
                          (r.get("trust") or {}).get("tier", ""), (r.get("trust") or {}).get("by") or ""])


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return ""


def evaluation() -> dict:
    res = _j("eval/heldout__publicai_swiss-ai_apertus-v1.5-8b.json")
    arms = {a: v["strict"]["ALL"] for a, v in res["arms"].items()}
    hyp = _j("eval/hypotheses__publicai_swiss-ai_apertus-v1.5-8b.json")
    gold = _j("eval/gold_agreement.json")
    curve = _j("eval/posthoc/theta_curve.json")
    ocr = _j("eval/posthoc/ocr_it_prompt.json")
    lock = json.loads((ROOT / "eval/prereg/LOCK").read_text())
    dev = (ROOT / "eval/prereg/DEVIATIONS.md").read_text()
    deviations = re.findall(r"^## (D\d+) \(([^)]*)\):? ?(.*)$", dev, re.M)
    lab_commit = _git("log", "-1", "--format=%h %cI", "--", "data/gold/heldout_labels.jsonl")
    lock_commit = _git("log", "--diff-filter=A", "-1", "--format=%h %cI", "--", "eval/prereg/LOCK")
    eight = RESULTS / "eval" / "gguf_8b_analysis.json"
    rows = res["per_doc"]
    n_null = sum(r["gold"] is None for r in rows)
    sugg = [r for r in rows if r["cascade"].get("route") == "apertus" and r["cascade"].get("value")]
    sugg_ok = sum(_outcome(r["cascade"]["value"], r["gold"], r["doc_dates"], r["lenient"]) == "correct" for r in sugg)
    baselines = dict(
        always_null=dict(exact=n_null, n=len(rows)),
        recall={
            a: dict(correct=v["strict"]["ALL"]["correct"], of=v["strict"]["ALL"]["n_gold_value"]) for a, v in res["arms"].items()
        },
        suggestions=dict(right=sugg_ok, of=len(sugg), on_answerless=sum(r["gold"] is None for r in sugg)),
    )
    return dict(
        baselines=baselines,
        theta=res["theta"],
        n=res["n_docs"],
        arms=arms,
        cells={a: v["strict"] for a, v in res["arms"].items()},
        hypotheses=hyp,
        gold=dict(n=gold["n"], agreement=gold["agreement"], a3=gold["decided_by_A3"], oracle=gold["oracle"]),
        curve=curve["table"],
        ocr_it=ocr["arms"],
        lock=dict(files=len(lock["files"]), written=lock["written"], commit=lock_commit),
        labels_commit=lab_commit,
        deviations=[dict(id=a, when=b, title=c) for a, b, c in deviations],
        served=res.get("served_fingerprints")
        or json.loads((DATA / "convert" / "theta" / "publicai_swiss-ai_apertus-v1.5-8b.json").read_text())["served_fingerprints"],
        eight=(_eight(json.loads(eight.read_text())) if eight.exists() else None),
    )


def _eight(g: dict) -> dict:
    """The real 8B (GGUF Q4_K_M, CPU) on the same 154 documents: eval/gguf_8b_analysis.py."""
    c = g.get("cost") or {}
    return dict(
        theta=g["theta"],
        arms={a: dict(g["arms"][a]["strict"]["ALL"], n_gold_null=g["arms"][a]["n_answerless"],
                      invented_on_null=g["arms"][a]["dates_on_answerless"]) for a in ("pointer", "cascade")},
        auroc=g["abstention_auroc"]["auroc"],
        mcnemar_cascade=g["mcnemar"]["cascade_8b_vs_70b"],
        wall_s_per_doc=c.get("heldout_wall_s_per_doc"),
        cpu_s_per_doc=c.get("heldout_cpu_s_per_doc"),
        vcpus=c.get("runner_vcpus"),
        max_rss_gb=c.get("max_rss_gb"),
    )


def p2() -> dict | None:
    """The second pre-registered test: 15 parliaments absent from every dev and held-out set (results/eval2)."""
    build = "publicai_swiss-ai_apertus-v1.5-8b"
    bp, hp = RESULTS / "eval2" / f"p2__{build}.json", RESULTS / "eval2" / f"hypotheses2__{build}.json"
    if not (bp.exists() and hp.exists()):
        return None
    board, hyp = json.loads(bp.read_text()), json.loads(hp.read_text())
    gold = _j("eval2/gold2_agreement.json")
    docs = [json.loads(x) for x in open(DATA / "gold2" / "p2_docs.jsonl")]
    names = body_names()
    meta = {b["key"]: b for b in _tsv_gz("bodies")}
    bodies: dict = {}
    for d in docs:
        label, _ = label_of(d["body"], names.get(d["body"], d["body"]), meta.get(d["body"], {}).get("type"))
        b = bodies.setdefault(d["body"], dict(key=d["body"], name=label, n=0, lang=d.get("cell", "")[:2]))
        b["n"] += 1
    t = hyp["subsets"]["all"]["theta_10_40"]
    # error profile in words, and why 'rules + Apertus' can trail 'Apertus alone' (data-driven from the per-document rows)
    profile = {}
    for a, v in board["arms"].items():
        x = v["strict"]["ALL"]
        profile[a] = dict(right=x["correct"], right_null=x["correct_null"], missed=x["false_null"],
                          date_no_answer=x["invented_on_null"],
                          wrong_date=x["misattributed"] + x["fabricated"] - x["invented_on_null"], invented=x["fabricated"])

    def _ok(r, arm):
        v = r[arm].get("value")
        return v == r["gold"] or (v is not None and v in (r.get("lenient") or []))
    po = [r for r in board["per_doc"] if _ok(r, "pointer") and not _ok(r, "cascade")]
    co = [r for r in board["per_doc"] if _ok(r, "cascade") and not _ok(r, "pointer")]
    why = collections.Counter(("a rule fired with a wrong date, so Apertus was not asked" if r["rules"]["status"] == "value" else
                               "the rules said null, so Apertus was not asked" if r["rules"]["status"] == "null" else "other")
                              for r in po)
    cvp = dict(pointer_only=len(po), cascade_only=len(co), reasons=dict(why))
    return dict(
        profile=profile,
        cascade_vs_pointer=cvp,
        n=board["n_docs"],
        arms={a: v["strict"]["ALL"] for a, v in board["arms"].items()},
        recall={a: dict(correct=v["value_recall"][0], of=v["value_recall"][1]) for a, v in t["arms"].items()},
        always_null=t["always_null_exact"],
        h1=hyp["subsets"]["all"]["H1_rules_value_recall"],
        h2=t["H2_pointer_vs_rules"],
        h2_without_bellinzona=hyp["subsets"]["without_bellinzona"]["theta_10_40"]["H2_pointer_vs_rules"],
        h3=t["H3_cascade_values_on_null"],
        h4=hyp["subsets"]["all"]["H4_auroc"],
        gold=dict(n=gold["n"], kappa_date=gold["agreement"]["answer_date"]["kappa"], a3=gold["decided_by_A3"],
                  oracle_match=gold["oracle"].get("match", 0)),
        lock_commit=_git("log", "--diff-filter=A", "-1", "--format=%h %cI", "--", "eval/prereg2/LOCK2"),
        labels_commit=_git("log", "--diff-filter=A", "-1", "--format=%h %cI", "--", "data/gold2/p2_labels.jsonl"),
        bodies=sorted(bodies.values(), key=lambda b: (-b["n"], b["name"])),
    )


P3_FIELDS = (("affair_type", "type"), ("number", "affair number"), ("submitter", "submitter"), ("submitted", "submission date"),
             ("answer_date", "answer date"), ("addressed_body", "addressed body"), ("decision_number", "decision number"),
             ("recommendation", "recommendation"))


def p3() -> dict | None:
    """Whole affairs (P3, results/eval3): per-field accuracy by arm, registered tiers and the Apertus residue test."""
    build = "publicai_swiss-ai_apertus-v1.5-8b"
    rp, hp = RESULTS / "eval3" / f"p3__{build}.json", RESULTS / "eval3" / f"hypotheses3__{build}.json"
    if not (rp.exists() and hp.exists()):
        return None
    res, hyp, agr = json.loads(rp.read_text()), json.loads(hp.read_text()), _j("eval3/gold3_agreement.json")
    aff = [json.loads(x) for x in open(DATA / "gold3" / "p3_affairs.jsonl")]
    names = body_names()
    meta = {b["key"]: b for b in _tsv_gz("bodies")}
    bodies: dict = {}
    for a in aff:
        label, _ = label_of(a["body"], names.get(a["body"], a["body"]), meta.get(a["body"], {}).get("type"))
        b = bodies.setdefault(a["body"], dict(key=a["body"], name=label, n=0, seen=a["seen_by_rules"], lang=a["lang"]))
        b["n"] += 1
    fields = []
    for key, name in P3_FIELDS:
        sc = res["scores"]["fields"][key]
        h = hyp["H1"][key]
        fields.append(dict(key=key, name=name, tier=h["tier"], ci=h["ci"],
                           arms={a: [v.get("correct", 0), v["n"]] for a, v in sc.items() if v.get("n")}))
    return dict(n=len(aff), n_pdfs=sum(len(a["docs"]) for a in aff), fields=fields, h2=hyp["H2"], h3=hyp["H3"],
                sets={k: v["C"] for k, v in res["scores"]["sets"].items()},
                agreement=dict(min_raw=min(v["raw"] for v in agr["agreement"].values()), n=agr["n"],
                               tie_broken=agr["tie_broken_fields"]),
                bodies=sorted(bodies.values(), key=lambda b: (not b["seen"], b["name"])),
                lock_commit=_git("log", "--diff-filter=A", "-1", "--format=%h %cI", "--", "eval/prereg3/LOCK3"),
                labels_commit=_git("log", "--diff-filter=A", "-1", "--format=%h %cI", "--", "data/gold3/p3_labels.jsonl"))


def p3b() -> dict | None:
    """The held-out replication of P3 (P3b, results/eval5; PREREG5): same extractor, fresh affairs from 9 other parliaments."""
    build = "publicai_swiss-ai_apertus-v1.5-8b"
    rp, hp = RESULTS / "eval5" / f"p3b__{build}.json", RESULTS / "eval5" / f"hypotheses_p3b__{build}.json"
    if not (rp.exists() and hp.exists()):
        return None
    res, hyp = json.loads(rp.read_text()), json.loads(hp.read_text())
    agr, audit = _j("eval5/gold5_agreement.json"), _j("eval5/annotation_audit.json")
    aff = [json.loads(x) for x in open(DATA / "gold5" / "p3b_affairs.jsonl")]
    gold = {g["affair_id"]: g for g in map(json.loads, open(DATA / "gold5" / "p3b_labels.jsonl"))}
    names = body_names()
    meta = {b["key"]: b for b in _tsv_gz("bodies")}
    bodies: dict = {}
    for a in aff:
        label, _ = label_of(a["body"], names.get(a["body"], a["body"]), meta.get(a["body"], {}).get("type"))
        b = bodies.setdefault(a["body"], dict(key=a["body"], name=label, n=0, seen=a["seen_by_rules"], lang=a["lang"]))
        b["n"] += 1
    fields = []
    for key, name in P3_FIELDS:
        sc, h = res["scores"]["fields"][key], hyp["H1"][key]
        cb = hyp["constant_baseline"]["fields"].get(key, {})
        rep = hyp["replication"]["S2"]["fields"].get(key, {})
        fields.append(dict(key=key, name=name, tier=h["tier"], ci=h["ci"],
                           arms={a: [v.get("correct", 0), v["n"]] for a, v in sc.items() if v.get("n")},
                           constant=cb.get("constant_correct"), p3=rep.get("p3"), p3_ci=rep.get("p3_ci"),
                           vs_p3=rep.get("vs_p3_ci")))
    # where the default lost a date OPD had right: a rule's printed date replaced the metadata value (data-driven)
    def ok(v, g):
        return v is not None and (v == g["answer_date"] or v in (g.get("answer_date_lenient") or []))
    body_of = {a["affair_id"]: a["body"] for a in aff}
    lost = [dict(affair=x["affair_id"], body=body_of[x["affair_id"]]) for x in res["per_affair"]
            if (g := gold.get(x["affair_id"])) and g["answer_date"]
            and ok(x["arms"]["M"]["answer_date"], g) and not ok(x["arms"]["C"]["answer_date"], g)]
    pre = (ROOT / "eval" / "prereg5" / "PREREG5.md").read_text()
    target = re.search(r"Target \*\*(\d+) affairs\*\*", pre)
    r = hyp["replication"]
    return dict(n=hyp["n"], target=int(target.group(1)) if target else None, n_pdfs=sum(len(a["docs"]) for a in aff),
                fields=fields, verdict=r["verdict"], s1=r["S1"], s2=dict(status=r["S2"]["status"], eligible=r["S2"]["eligible"],
                below=r["S2"]["below"]),
                h3=hyp["H3_primary"], h3_secondary=dict(recall=hyp["H3_secondary_as_PREREG3"]["recall"],
                                                       precision=hyp["H3_secondary_as_PREREG3"]["precision"]),
                answer_date_lost=dict(n=len(lost), bodies=dict(collections.Counter(x["body"] for x in lost))),
                sets={k: dict(precision=v["C"]["precision"], recall=v["C"]["recall"]) for k, v in hyp["sets"].items()},
                agreement=dict(n=agr["n"], min_raw=min(v["raw"] for v in agr["agreement"].values()),
                               tie_broken=agr["tie_broken_fields"]),
                audit=dict(sessions=len([x for x in audit["sessions"] if x["annotator"] in ("A1", "A2")]),
                           cross_paths=sum(x.get("other_annotator_paths", 0) + x.get("results_paths", 0)
                                           + x.get("p3_gold_paths", 0) for x in audit["sessions"])),
                bodies=sorted(bodies.values(), key=lambda b: (not b["seen"], b["name"])),
                lock_commit=_git("log", "--diff-filter=A", "-1", "--format=%h %cI", "--", "eval/prereg5/LOCK5"),
                labels_commit=_git("log", "--diff-filter=A", "-1", "--format=%h %cI", "--", "data/gold5/p3b_labels.jsonl"))


def p4() -> dict | None:
    """Virtual affairs (P4, results/eval4): agenda items of held-out Bulle sittings derived as affairs, with the gold."""
    build = "publicai_swiss-ai_apertus-v1.5-8b"
    sp, pp = RESULTS / "eval4" / f"p4_heldout__{build}__score.json", RESULTS / "eval4" / f"p4_heldout__{build}.json"
    hp = RESULTS / "eval4" / f"hypotheses4__{build}.json"
    if not (sp.exists() and pp.exists() and hp.exists()):
        return None
    sc, pred, hyp = json.loads(sp.read_text()), json.loads(pp.read_text()), json.loads(hp.read_text())
    gold = [json.loads(x) for x in open(DATA / "gold4" / "p4_heldout_labels.jsonl")]
    mtgs = {json.loads(x)["date"]: json.loads(x) for x in open(DATA / "gold4" / "p4_heldout_meetings.jsonl")}
    review = {(r["meeting"], r["no"]): r for r in pred["rows"] if r["arm"] == "review"}
    rules = {(r["meeting"], r["no"]): r for r in pred["rows"] if r["arm"] == "rules_only"}
    meetings = []
    for date in sorted({g["meeting"] for g in gold}):
        items = []
        for g in [x for x in gold if x["meeting"] == date]:
            r, v = rules.get((date, g["no"])), review.get((date, g["no"]))
            r, v = r or {}, v or {}
            items.append(dict(no=g["no"], gold_title=(g.get("title_quote") or "")[:160], gold_type=g["type"],
                              gold_decision=g["decision"], derived=bool(r), number=r.get("number"), type=r.get("type"),
                              decision=r.get("decision"), quote=(r.get("decision_quote") or "")[:220],
                              review_decision=v.get("decision") if v.get("decision_route") == "apertus" else None))
        m = mtgs.get(date, {})
        meetings.append(dict(date=date, agenda_url=(m.get("agenda") or {}).get("url"),
                             minutes_url=(m.get("minutes") or {}).get("url"), items=items))
    return dict(body="2125", arms=sc["arms"], n_items=sc["n_gold_items"], hyp=hyp, meetings=meetings,
                agreement=_j("eval4/gold4_agreement.json"),
                lock_commit=_git("log", "--diff-filter=A", "-1", "--format=%h %cI", "--", "eval/prereg4/LOCK4"),
                labels_commit=_git("log", "--diff-filter=A", "-1", "--format=%h %cI", "--", "data/gold4/p4_heldout_labels.jsonl"))


# The meaning class of each of the 17 schema fields (README "Is a common schema feasible?"; class definitions in
# data/schema/field_verdict_classes.json; evidence from results/census/comparability.json and matrix.json).
FIELD_CLASS = {
    "date_submission": "shared", "submitter": "shared", "co_signatories": "shared", "addressed_body": "shared",
    "government_recommendation": "shared", "date_decision": "shared", "date_dispatch": "shared", "qa_pairing": "shared",
    "related_affairs": "shared", "language": "shared", "documents_usable_text": "shared", "answer_link_status": "shared",
    "date_answer": "shared_with_role_split", "procedural_history": "shared_with_role_split", "type": "shared_with_role_split",
    "procedural_state": "shared_with_role_split", "decision_outcome": "shared_with_role_split",
}
FIELD_NAME = {
    "date_submission": "submission date", "submitter": "submitter", "co_signatories": "co-signatories",
    "addressed_body": "addressed body", "government_recommendation": "government recommendation",
    "date_decision": "decision date", "date_dispatch": "dispatch date", "qa_pairing": "question ↔ answer pairing",
    "related_affairs": "related affairs", "language": "language", "documents_usable_text": "usable text",
    "answer_link_status": "answer-link status", "date_answer": "answer date", "procedural_history": "procedural history",
    "type": "type", "procedural_state": "procedural state", "decision_outcome": "decision outcome",
}
SAMPLE_AFFAIR = 301273  # P3b, Basel-Landschaft: a rule value with page + span, metadata values, typed nulls with reasons


def schema_view() -> dict:
    """Near the top of the site: one real converter record (P3b run, results/eval5) and the 17 fields with their class."""
    m, cmp_ = _j("census/matrix.json"), _j("census/comparability.json")
    classes = {c["key"]: c for c in json.loads((DATA / "schema" / "field_verdict_classes.json").read_text())}
    q = _j("census/question.json")
    va = _j("census/virtual_affairs.json")
    qt = m["concept_split"]["answer_modality_by_type"]["Question time"]
    ev = {  # evidence per field in the role-split class (raw labels mapped to more than one harmonised concept)
        "date_answer": f"‘answer date’ is three dates (decided, dispatched, registered); in {len(q['same_day_bodies'])} "
                       "parliaments OPD’s ‘answer’ event mostly equals the submission date",
        "procedural_history": f"{cmp_['dates_with_roles']['ambiguous_labels']} event labels carry different date roles; "
                              f"{100 * cmp_['dates_with_roles']['unharmonised_share']:.1f}% of events have no harmonised id",
        "type": f"{cmp_['type']['ambiguous_labels']} of {cmp_['type']['raw_labels']:,} raw type labels map to different "
                "harmonised types" + "".join(f" (‘Antrag’ alone to {len(e['concepts'])})"
                                             for e in cmp_["type"]["ambiguous_examples"] if e["label"] == "antrag"),
        "procedural_state": f"{cmp_['procedural_state']['ambiguous_labels']} state labels are ambiguous",
        "decision_outcome": f"{cmp_['decision_outcome']['ambiguous_labels']} outcome labels are ambiguous",
        "government_recommendation": f"{cmp_['government_recommendation']['ambiguous_labels']} ambiguous labels",
    }
    fields = []
    for k, f in m["fields"].items():
        sc = f["status_counts"]
        fields.append(dict(key=k, name=FIELD_NAME.get(k, k.replace("_", " ")), cls=FIELD_CLASS[k], tier=f["tier"],
                           route=f["extraction_route"], eligible=f["eligible_bodies"], metadata=sc["metadata"],
                           mixed=sc["mixed"], pdf=sc["pdf"], no_source=sc["no_source"], evidence=ev.get(k, "")))
    order = {"shared": 0, "shared_with_role_split": 1}
    fields.sort(key=lambda f: (order[f["cls"]], -f["metadata"], f["key"]))
    body_specific = [
        dict(name="oral answers in question time",
             evidence=f"{100 * qt['oral_share']:.1f}% of question-time answers are oral ({qt['oral']:,} of "
                      f"{qt['with_answer']:,}); typed ‘oral’, never ‘missing’"),
        dict(name="councils that publish only meeting documents",
             evidence=f"{va['n_bodies']} bodies, {va['n_bodies_no_affairs']} of them with no affair at all: affairs derived "
                      "from agenda and minutes are marked ‘virtual’ with ‘derived_from’ (test P4)"),
        dict(name="executive business that answers no member’s affair",
             evidence="government credits, reports and ordinances filed as affairs in some parliaments; kept in the "
                      "parliament’s own vocabulary"),
    ]
    res = _j("eval5/p3b__publicai_swiss-ai_apertus-v1.5-8b.json")
    x = next(a for a in res["per_affair"] if a["affair_id"] == SAMPLE_AFFAIR)
    rec = x["affair"]
    ad = rec["qa"][0]["answer_date"]
    assert ad["kind"] == "value" and ad.get("page") and ad.get("char_start") is not None, "sample must carry a span"
    assert rec["government_recommendation"]["kind"] == "null", "sample must carry a typed null"
    gold = next(g for g in map(json.loads, open(DATA / "gold5" / "p3b_labels.jsonl")) if g["affair_id"] == SAMPLE_AFFAIR)
    names = body_names()
    meta = {b["key"]: b for b in _tsv_gz("bodies")}
    bk = rec["ref"]["body_key"]
    label, _ = label_of(bk, names.get(bk, ""), meta.get(bk, {}).get("type"))
    return dict(
        fields=fields, body_specific=body_specific, tier_counts=m["tier_counts"], n_bodies=m["n_bodies"],
        classes={k: dict(label=v["labels"]["en"], definition=v["definition"]) for k, v in classes.items()},
        counts=dict(collections.Counter(FIELD_CLASS[k] for k in m["fields"])),
        sample=dict(record=rec, suggestions=x.get("suggestions", {}), body_label=label, test="P3b",
                    source="results/eval5/p3b__publicai_swiss-ai_apertus-v1.5-8b.json",
                    gold_answer_date=gold["answer_date"], gold_quote=gold.get("answer_date_quote"),
                    gold_page=gold.get("answer_date_page")),
    )


def method() -> dict:
    m = _j("census/matrix.json")
    return dict(
        fields=[dict(key=k, tier=f["tier"], route=f["extraction_route"]) for k, f in m["fields"].items()],
        vocab_sizes={
            p.stem: len(json.loads(p.read_text())) if p.suffix == ".json" else None
            for p in sorted((DATA / "schema").glob("*.json"))
        },
    )


def headline(par: dict, ev: dict) -> dict:
    nat = par["national"]
    be = _j("repair/summary.json")["by_action"]
    return dict(
        gap=nat["gap"],
        written=nat["ev_answer"],
        gap_share=par["gap_share"],
        relink=be["relink"],
        fetch=be["fetch"],
        bodies=len(par["rows"]),
        heldout=ev["n"],
        rules_exact=ev["arms"]["rules"]["exact"],
        rules_on_null=ev["arms"]["rules"]["invented_on_null"],
        n_null=ev["arms"]["rules"]["n_gold_null"],
        naive_fab=ev["arms"]["naive_plain"]["fabricated"],
        p2=(dict(pointer=ev["p2"]["recall"]["pointer"], rules=ev["p2"]["recall"]["rules"], bodies=len(ev["p2"]["bodies"]),
                 p=ev["p2"]["h2"]["p"]) if ev.get("p2") else None),
        periods={k: dict(written=v["written"], missing=v["written"] - v["attached"]) for k, v in par["national_periods"].items()},
    )


def _finite(o):
    """JSON has no Infinity/NaN: a non-finite margin (no date candidate in the document) becomes null."""
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_finite(v) for v in o]
    return o


def collect(full_text: bool = False) -> dict:
    par, ev = parliaments(), evaluation()
    ev["p2"] = p2()
    ev["p3"] = p3()
    ev["p3b"] = p3b()
    ev["p4"] = p4()
    return _finite(
        dict(
            generated=_git("log", "-1", "--format=%h %cI"),
            headline=headline(par, ev),
            documents=documents(full_text),
            parliaments=par,
            evaluation=ev,
            method=method(),
            schema=schema_view(),
        )
    )
