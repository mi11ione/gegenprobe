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
from ..census.presentation import CANTON_NAME, CANTON_RULE
from ..convert import lattice, pointer, rules
from ..paths import DATA, ROOT
from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch through pdftext/net without the RFC 9309 matcher (compliance/fetchguard.py)

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
        names[b["body"]] = b.get("opd_name") or b["name"]  # OPD's name (question.json `name` follows the site's rule)
    return names


# One denominator for every per-body number: interventions whose events record a WRITTEN government answer (the census
# funnel's ev_w). Each of them has exactly one answer-link status, so the parts below always sum to `written`.
LINKS = ("attached", "agenda", "parentless", "image_only", "oral", "absent")
PERIODS = {"all": (None, None), "since2015": (2015, None), "y2425": (2024, 2025)}
PERIOD_LABEL = {"all": "all years", "since2015": "since 2015", "y2425": "2024–25"}


# Canton names on this English page: the canton's official name in the language of its majority (OPD labels every canton
# in German: 'Tessin', 'Genf', 'Waadt' ...). Cities and communes keep OPD's name, which is already the local one (Lugano,
# Neuchâtel, Genève). OPD's German name stays searchable (row 'alt'). One rule for the site, question.json and docs/census.md:
# CANTON_NAME / CANTON_RULE live in census/presentation.py.


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


def _are(n: int, one: str = "was", many: str = "were") -> str:
    return one if n == 1 else many


def where_they_are(c: dict, src: dict | None = None) -> list[str]:
    """Where a period's written answers without attached text are, from the derived layer (census/corrected.py), largest
    first. Never says 'not in OpenParlData' for an answer an adapter found in OPD."""
    g = c.get
    parts = []
    el = c["agenda"] + c["parentless"]
    if el:
        parts.append((el, f"{el:,} {_are(el, 'is', 'are')} in OpenParlData with text but not linked to their intervention "
                      "(an aggregator issue, not the parliament's)"))
    if g("unrecognised"):
        u = c["unrecognised"]
        parts.append((u, f"{u:,} {_are(u, 'is', 'are')} in OpenParlData with text on the intervention, under a heading the "
                      "census does not recognise (OPD only has to mark them as the answer)"))
    img = g("opd_image_only", c["image_only"])
    if img:
        tv, ocr, rest = g("img_text_verified", 0), g("img_ocr", 0), g("img_open", img)
        det = []
        if tv and ocr == tv:
            det.append(f"OCR of OPD's own copies would recover {ocr:,} of them (run and checked by affair and date; "
                       "machine-read text, not the official wording)")
        elif tv:
            det.append(f"reading OPD's own copies would recover {tv:,} of them (text layer or OCR, checked by affair and "
                       "date" + (f"; {ocr:,} by OCR, machine-read text" if ocr else "") + ")")
        if g("img_fetchable"):
            det.append(f"the parliament publishes a text copy of {c['img_fetchable']:,}")
        if rest and det:
            det.append(f"the other {rest:,} still need OCR or the text version the parliament publishes")
        parts.append((img, f"{img:,} {_are(img, 'is', 'are')} in OpenParlData only as a copy without text"
                      + (": " + ", ".join(det) if det else ", to be read by OCR or replaced by the text version the "
                         "parliament publishes")))
    if g("fetchable"):
        fe = c["fetchable"]
        parts.append((fe, f"{fe:,} {_are(fe, 'is', 'are')} not in OpenParlData but the parliament publishes "
                      f"{'it' if fe == 1 else 'them'} (a "
                      "verified fetch list)"))
    op = g("still_open", c["absent"])
    if op:
        src = src or {}
        them = "it" if op == 1 else "them"
        rv, ls = g("open_review", 0), g("open_listed", 0)
        rest = op - rv - ls
        if rest == op and (g("open_no_adapter", op) == op or not src.get("reads_parliament")):
            s = (f"{op:,} {_are(op, 'is', 'are')} not in OpenParlData; whether the parliament publishes {them} elsewhere "
                 "was not checked")
        else:
            notes = [f"{rv:,} with a candidate document for a person to check"] if rv else []
            notes += [f"{ls:,} matched by identity and wording only, listed but not counted"] if ls else []
            if rest and src.get("reads_parliament"):
                hosts = ", ".join(h for h in src["hosts"] if h != "files.openparldata.ch")
                notes.append(f"{rest:,} found neither in OpenParlData nor on the parliament's site that was read ({hosts})")
            elif rest:
                notes.append(f"{rest:,} not found in OpenParlData, and whether the parliament publishes "
                             f"{'it' if rest == 1 else 'them'} elsewhere was not checked")
            s = f"{op:,} {_are(op, 'has', 'have')} no verified answer yet: " + ", ".join(notes)
        parts.append((op, s))
    return [s for _, s in sorted(parts, key=lambda p: -p[0])]


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
    # Every share here is over the answers given in WRITING: interventions OPD records with a written-answer event, minus
    # those answered orally in the sitting (question time, Valais oral-answer stubs), for which no text is expected.
    out = []
    pick = n if n["written"] >= 20 else a
    yrs = r.get("years")
    allw = f"over all years OPD holds ({yrs[0]}–{yrs[1]})" if yrs else "over all years"
    what = "an oral-answer note filed in place of a text" if r["key"] == "VS" else "question time"

    def unrec(c: dict) -> str:
        # the derived layer: answers in OPD with text on the affair under a heading the census lexicon misses
        u, wl, iw = c.get("unrecognised", 0), c.get("written_lack_text_at_most", c["written_missing"]), c["in_writing"]
        if not u:
            return ""
        if not wl:
            return f", but all {u:,} are in OpenParlData with text under a heading the census does not recognise"
        return (f", but {u:,} of these {_are(u, 'is', 'are')} in OpenParlData with text under a heading the census does not "
                f"recognise, so at most {wl:,} ({_pc(wl, iw)}) lack answer text")

    def lead(c: dict, when: str) -> str:
        wm, iw = c["written_missing"], c["in_writing"]
        if not c["oral"]:
            return (f"{when}, {wm:,} of {iw:,} written government answers ({_pc(wm, iw)}) have no answer text attached in "
                    "OpenParlData" + unrec(c))
        return (f"{when}, OPD records {c['written']:,} interventions with a government answer; {c['oral']:,} of them were "
                f"answered orally in the sitting ({what}), so no written text is expected and they are not missing; "
                + ("every answer given in writing has its text attached" if wm == 0 else
                   f"of the {iw:,} answered in writing, {wm:,} ({_pc(wm, iw)}) have no answer text attached in OpenParlData"
                   + unrec(c)))

    share = lambda c: c["written_missing"] / c["in_writing"] if c["in_writing"] else 0.0  # noqa: E731
    if n["written"] >= 20:
        out.append(lead(n, "In 2024–25"))
        if a["in_writing"] and abs(share(a) - share(n)) > 0.15:
            out.append(f"{allw} it is {100 * share(a):.0f}% of written answers, so older interventions dominate the "
                       "all-years figure")
    else:
        out.append(lead(a, allw[0].upper() + allw[1:]) + "; 2024–25 has too few to compare")
    if pick is n and not n["oral"] and a["oral"] >= 20:
        out.append(f"{allw}, {a['oral']:,} answers were given orally in the sitting and are not counted as missing")
    m = a["written_missing"]
    if m >= 20:
        out.append(f"of the {m:,} written answers without attached text over all years, "
                   + "; ".join(where_they_are(a, r.get("adapter"))))
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
    corr = _j("census/corrected.json")  # derived layer over the registered census (census/corrected.py)
    adsum = _j("repair/adapters/adapters_summary.json")["bodies"]
    rows = []
    for k in sorted(set(s["by_body"]) | set(cells)):
        bm = bodies_meta.get(k, {})
        label, level = label_of(k, names.get(k, k), bm.get("type"))
        qq = q.get(k, {})
        periods = {}
        for p in PERIODS:
            c = dict(part[k][p]) if k in part else dict(written=0, **{x: 0 for x in LINKS})
            # 'missing' = no answer text attached (the census gap; includes oral answers, for which no text is expected);
            # written_missing = the gap minus oral answers, over the answers given in writing (in_writing)
            c["missing"] = c["written"] - c["attached"]
            c["written_missing"] = c["missing"] - c["oral"]
            c["in_writing"] = c["written"] - c["oral"]
            c["written_missing_share"] = c["written_missing"] / c["in_writing"] if c["in_writing"] else None
            c["with_text"] = c["attached"] / c["written"] if c["written"] else None
            # the derived layer (results/census/corrected.json): where each registered gap row is once the repair routes
            # looked; adapter rows count only in the counted verification tiers. Registered columns above stay as they are.
            x = (corr["by_body"].get(k) or {}).get(p)
            if x:
                assert (x["written"], x["gap"], x["oral"]) == (c["written"], c["missing"], c["oral"]), (k, p)
            x = x or dict(unrecognised=0, image_only=0, image_only_parts=dict(text_verified=0, fetchable=0, open=0),
                          image_only_ocr=0, fetchable=0, open=0, open_parts=dict(listed_unverified=0, review=0),
                          opd_elsewhere=c["agenda"] + c["parentless"], repaired=c["agenda"] + c["parentless"])
            ip = x["image_only_parts"]
            c["unrecognised"] = x["unrecognised"]  # in OPD with text on the affair, heading the census lexicon misses
            c["opd_image_only"] = x["image_only"]  # in OPD only as a copy without usable text
            c["img_text_verified"], c["img_ocr"] = ip["text_verified"], x["image_only_ocr"]
            c["img_fetchable"], c["img_open"] = ip["fetchable"], ip["open"]
            c["fetchable"] = x["fetchable"]  # not in OPD; verified fetch row from the parliament
            c["still_open"] = x["open"]  # not in OPD, not found yet
            c["open_listed"], c["open_review"] = x["open_parts"]["listed_unverified"], x["open_parts"]["review"]
            c["open_no_adapter"] = x["open_parts"].get("no_adapter", 0)
            c["lack_text_at_most"] = c["missing"] - c["unrecognised"]
            c["written_lack_text_at_most"] = c["written_missing"] - c["unrecognised"]
            c["repaired"] = x["repaired"]
            # after every counted repair: agenda join, Bern relink, tag_answer, verified text of OPD's own image-only
            # copies, verified fetches (adapters, Bern, Curia Vista); oral answers are typed, not counted as text
            c["after_repair"] = (c["attached"] + c["repaired"]) / c["written"] if c["written"] else None
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
                adapter=corr["adapter_sources"].get(k),
                adapter_counted=adsum.get(k, {}).get("counted_by_action", {}),  # adapter rows in the counted tiers
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
            # + OCR: if the image-only copies with no verified text yet were also read (not done; a separate state)
            c["after_ocr"] = (c["attached"] + c["repaired"] + c["img_open"]) / c["written"] if c["written"] else None
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
        p: dict(written=sum(r["periods"][p]["written"] for r in rows), attached=sum(r["periods"][p]["attached"] for r in rows),
                oral=sum(r["periods"][p]["oral"] for r in rows))
        for p in PERIODS
    }
    oral = oral_reconcile(s, rows)
    for r in rows:
        if r["key"] == "VS":
            r["oral_note"] = oral["vs_sentence"]
    return dict(
        rows=rows,
        fields=fields,
        national=s["national"],
        national_periods=nat,
        gap_share=s["national_gap_share"],
        decomposition=s["gap_prime_decomposition"],
        oral_reconcile=oral,
        question=_j("census/question.json")["national"],
        same_day=[dict(b, label=next((r["label"] for r in rows if r["key"] == b["body"]), b["name"]))
                  for b in _j("census/question.json")["same_day_bodies"]],
        canton_rule=CANTON_RULE,
        source_formats=_source_formats(),
        tier_counts=m["tier_counts"],
        criteria=m["criteria"],
        repair=_j("repair/summary.json")["by_action"],
        corrected=dict(national=corr["national"], sentences=corr["sentences"], listed_unverified=corr["listed_unverified"],
                       tag_answer_by_tier=corr["tag_answer_by_tier"], report=corr["report"], categories=corr["categories"]),
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


def oral_reconcile(s: dict, rows: list[dict]) -> dict:
    """The oral counts inside 'no answer text', each with its definition (U2: Valais 1,008 / 1,016 / 1,017).
    typed_oral (table, dataset): link_status 'oral' = VS '_ANT' stubs by the census length proxy + question-time answers
    with no answer document; vs_stub_proxy: the stubs alone (summary.json gap_oral_split.vs_stub); vs_stub_exact: the stubs
    the repair's exact text rule confirms (the retype_oral list; results/census/vs_reconcile.json)."""
    vr = _j("census/vs_reconcile.json")
    sp = s["gap_oral_split"]
    vs = next((r for r in rows if r["key"] == "VS"), None)
    vs_typed = vs["periods"]["all"]["oral"] if vs else 0
    vs_qt = sp["question_time_by_body"].get("VS", 0)
    assert vs_typed == sp["vs_stub"] + vs_qt, (vs_typed, sp)
    out = dict(
        typed_oral=sp["vs_stub"] + sp["question_time"], vs_stub_proxy=sp["vs_stub"], question_time=sp["question_time"],
        question_time_by_body=sp["question_time_by_body"], vs_typed_oral=vs_typed, vs_question_time=vs_qt,
        vs_stub_exact=vr["canonical"]["value"], vs_proxy_only=vr["only_census"],
        definition="answered orally in the sitting, so no written text is expected: Valais files an '_ANT' oral-answer stub "
                   "in place of a text, and question-time answers (Fragestunde, heure des questions) are in the session "
                   "minutes; counted inside 'no answer text' (the census gap) but not as written answers missing",
    )
    out["vs_sentence"] = (
        f"Valais, all years: {vs_typed:,} interventions are typed oral here and in the dataset: {sp['vs_stub']:,} '_ANT' "
        f"oral-answer stubs found by the census length proxy + {vs_qt} question-time answer; the repair's exact text rule "
        f"confirms {vr['canonical']['value']:,} of the {sp['vs_stub']:,} stubs (the retype list OPD gets; the other "
        f"{vr['only_census']} are documents where proxy and rule disagree, results/census/vs_reconcile.json).")
    return out


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
    # (key in the row's period dict, CSV column suffix). no_answer_text = the census gap (written - attached, includes oral
    # answers); written_missing = no_answer_text - oral, over in_writing = written - oral (columns: interventions_README.md)
    per_cols = [
        ("written", "written"),
        ("attached", "attached"),
        ("agenda", "agenda"),
        ("parentless", "parentless"),
        ("image_only", "image_only"),
        ("oral", "oral"),
        ("absent", "absent"),
        ("missing", "no_answer_text"),
        ("in_writing", "in_writing"),
        ("written_missing", "written_missing"),
        ("written_missing_share", "written_missing_share"),
        ("with_text", "with_text"),
        # derived layer (results/census/corrected.json): where the written answers without attached text are
        ("unrecognised", "in_opd_unrecognised_heading"),
        ("opd_image_only", "in_opd_image_only"),
        ("img_text_verified", "image_only_text_verified"),
        ("fetchable", "fetchable_verified"),
        ("still_open", "still_open"),
        ("written_lack_text_at_most", "written_lack_text_at_most"),
        ("after_repair", "after_repair"),
    ]
    slug = {t: t.lower().replace(" ", "_") for t in TYPE_ORDER}
    head = (cols + [f"{p}_{h}" for p in PERIODS for _, h in per_cols]
            + ["median_days_all_types", "median_flag", "safe_to_say", "coverage"]
            + [f"{p}_{x}_{slug[t]}" for p in PERIODS for t in TYPE_ORDER for x in ("median_days", "n")]
            + ["first_year", "last_year", "all_main_type", "all_median_days_main_type", "date_trust", "date_verified_by"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(head)
        for r in par["rows"]:
            vals = [r[c] for c in cols]
            for p in PERIODS:
                c = r["periods"][p]
                vals += [round(c[x], 4) if isinstance(c[x], float) else c[x] for x, _ in per_cols]
            # per-type medians (n >= TIMES_MIN; blank otherwise and for same-day bodies, whose 'answer' date is no answer date)
            tt = [(r["times"].get(p, {}).get(t) or {}) for p in PERIODS for t in TYPE_ORDER]
            ti = [v for x in tt for v in (x.get("median", ""), x.get("n", ""))]
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
FIELD_CLASS = {  # P8 (eval/prereg9, results/p8) moved submitter, co-signatories, language, addressed body and recommendation
    "date_submission": "shared", "date_decision": "shared", "date_dispatch": "shared", "qa_pairing": "shared",
    "related_affairs": "shared", "documents_usable_text": "shared", "answer_link_status": "shared",
    "date_answer": "shared_with_role_split", "procedural_history": "shared_with_role_split", "type": "shared_with_role_split",
    "procedural_state": "shared_with_role_split", "decision_outcome": "shared_with_role_split",
    "submitter": "shared_with_role_split", "co_signatories": "shared_with_role_split", "language": "shared_with_role_split",
    "addressed_body": "shared_with_role_split", "government_recommendation": "shared_with_role_split",
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


def adapters() -> dict | None:
    """Source adapters (results/repair/adapters/, upgrade U1): coverage, verification tiers, the blind audits and the
    robots.txt audit; per parliament the verified count and its routes (docs/adapters.md, docs/incidents.md)."""
    base = RESULTS / "repair" / "adapters"
    if not (base / "adapters_summary.json").exists():
        return None
    s = json.loads((base / "adapters_summary.json").read_text())
    tiers = s["tiers"]
    t = s["totals"]
    dsum = json.loads((base / "audit" / "design_audit_summary.json").read_text())
    design = dsum["total"]
    fresh = json.loads((base / "audit" / "fresh_audit_precision.json").read_text())
    rob = json.loads((base / "robots_audit.json").read_text()).get("totals", {})
    # per parliament: counted rows only (tiers exact_doc_date, exact_any_printed_date, date_window), by action; the Jura tier is
    # listed separately (not_counted), never inside "verified"
    bodies = sorted(({"key": k, "name": b["label"], "verified": sum(b["counted_by_action"].values()),
                      "not_counted": b["tiers"].get("identity_wording_only", 0), "targets": b["targets"],
                      "review": b["review"], "tag_answer": b["counted_by_action"].get("tag_answer", 0),
                      "extract_tag": b["counted_by_action"].get("extract_tag", 0),
                      "fetch": b["counted_by_action"].get("fetch", 0)}
                     for k, b in s["bodies"].items() if b["counted"] or b["tiers"].get("identity_wording_only")),
                    key=lambda b: -b["verified"])
    return dict(coverage=s["coverage"], n_bodies=len(s["bodies"]),
                tiers={k: dict(n=v["n"], absent=v["absent"], image_only=v["image_only"], counted=v["counted"])
                       for k, v in tiers.items()},
                verified=t["verified"], verified_absent=t["verified_absent"], verified_image_only=t["verified_image_only"],
                review=t["review"], tag_answer=t["verified_by_action"].get("tag_answer", 0),
                design_audit=dict(rows=dsum["rows"], verified=design["verified"]["n"],
                                  verified_no=design["verified"].get("is_answer_no", 0),
                                  all_yes=design["all"]["is_answer_yes"]),
                fresh_audit=dict(n=fresh["n"], yes=fresh["is_answer_yes"], no=fresh["no"], unclear=fresh["unclear"],
                                 precision=fresh["precision"], wilson=fresh["wilson95"]),
                robots=rob, bodies=bodies)


def p5() -> dict | None:
    """P5 (eval/prereg6, LOCK6): Q/A pairing, people, recommendation and reasoning on 40 fresh affairs (results/eval6)."""
    build = "publicai_swiss-ai_apertus-v1.5-8b"
    hp = RESULTS / "eval6" / f"hypotheses6__p5__{build}.json"
    if not hp.exists():
        return None
    h = json.loads(hp.read_text())
    post = _j("eval6/p5_posthoc.json")
    q = _j("eval6/p5_qwen_check.json")
    f = h["fields"]
    names = body_names()
    meta = {b["key"]: b for b in _tsv_gz("bodies")}
    keys = ("questions_recall", "submitter", "recommendation", "reasoning")
    pick = lambda arm: {k: [f[arm][k]["k"], f[arm][k]["n"]] for k in keys}  # noqa: E731
    return dict(n=h["n_affairs"], h1=dict(precision=[h["H1"]["precision"]["k"], h["H1"]["precision"]["n"]],
                                          precision_ci=h["H1"]["precision"]["ci95"],
                                          recall=[h["H1"]["recall"]["k"], h["H1"]["recall"]["n"]],
                                          recall_ci=h["H1"]["recall"]["ci95"], tier=h["H1"]["tier"], holds=h["H1"]["holds"]),
                h2=dict(a=h["H2"]["a_only"], b=h["H2"]["b_only"], p=h["H2"]["p_one_sided"], holds=h["H2"]["holds"]),
                h3=dict(verdict=h["H3"]["verdict"], residue=h["H3"]["residue_recall"]["n"]),
                h4=dict(a=h["H4"]["a_only"], b=h["H4"]["b_only"], p=h["H4"]["p_one_sided"], holds=h["H4"]["holds"],
                        g_precision=[h["H4"]["G_precision"]["k"], h["H4"]["G_precision"]["n"]],
                        g_unlocatable=h["H4"]["G_unlocatable_values"]),
                h5=dict(ok=h["H5"]["recheck"]["R"]["ok"], failed=sum(v["failed"] for v in h["H5"]["recheck"].values()),
                        holds=h["H5"]["holds"]),
                fields=dict(rules=pick("R"), pointer=pick("RA"), free=pick("G")),
                dev_submitter=post["R_dev_vs_p5"]["submitter"]["dev"],
                bodies=sorted((dict(key=k, name=label_of(k, names.get(k, k), meta.get(k, {}).get("type"))[0], n=v["n"],
                                    qa=v["R"]["qa_recall"]) for k, v in post["body"].items()),
                              key=lambda b: -b["qa"][0] / max(b["qa"][1], 1)),
                qwen=dict(valid=q["agreement"]["valid"], n=q["agreement"]["n"],
                          answers=[q["agreement"]["answers_iou05"]["k"], q["agreement"]["answers_iou05"]["n"]],
                          h1_recall=[q["h1_sensitivity"]["R"]["qwen_as_gold"]["recall"]["k"],
                                     q["h1_sensitivity"]["R"]["qwen_as_gold"]["recall"]["n"]],
                          h1_precision=[q["h1_sensitivity"]["R"]["qwen_as_gold"]["precision"]["k"],
                                        q["h1_sensitivity"]["R"]["qwen_as_gold"]["precision"]["n"]]))


def p6() -> dict | None:
    """P6 (eval/prereg7, LOCK7): answer-date reader v2 vs free prompting, v1 and baselines on 68 fresh documents."""
    build = "publicai_swiss-ai_apertus-v1.5-8b"
    hp = RESULTS / "p6" / f"hypotheses7__{build}.json"
    if not hp.exists():
        return None
    h = json.loads(hp.read_text())
    q = _j("p6/qwen7_check.json")
    order = ["free_null", "free_guided", "cascade_v2", "v2", "v1", "cascade_v1", "rules", "free_plain",
             "latest_on_answer_typed", "latest_printed_date", "always_null"]
    arms = {k: dict(exact=h["arms"][k]["exact"], found=h["arms"][k]["dates_found"],
                    answerless=h["arms"][k]["dated_answerless"], fabricated=h["arms"][k]["fabricated"])
            for k in order if k in h["arms"]}
    d = lambda x: dict(a=x["a_only"], b=x["b_only"], p=x["p"])  # noqa: E731
    qs = q["hypotheses_under_qwen_gold"]["qwen_strict"]
    g8 = RESULTS / "p6" / "hypotheses7__gguf_apertus-v1.5-8b-text-q4_k_m.json"  # the real 8B on CPU (exploratory)
    h8 = json.loads(g8.read_text()) if g8.exists() else None
    gguf = (dict(n=h8["n"], arms={k: dict(exact=h8["arms"][k]["exact"], answerless=h8["arms"][k]["dated_answerless"])
                                  for k in ("v2", "v1", "free_null", "cascade_v2", "rules") if k in h8["arms"]})
            if h8 else None)
    return dict(n=h["n"], answered=h["n_answered"], answerless=h["n_answerless"], bodies=h["n_bodies"], order=order, gguf=gguf,
                arms=arms, h1=dict(d(h["H1_v2_vs_free_null"]["doc_level"]), holds=h["H1_v2_vs_free_null"]["holds"]),
                h2=dict(v2=h["H2_answerless"]["v2"], upper=h["H2_answerless"]["wilson95"][1], holds=h["H2_answerless"]["holds"]),
                h3=dict(d(h["H3_v2_vs_v1"]["doc_level"]), holds=h["H3_v2_vs_v1"]["holds"]),
                s3=d(h["S3_cascade_v2_vs_rules_on_answered"]), auroc=h["S4_presence_auroc"]["auroc"],
                qwen=dict(presence_kappa=q["agreement_strict"]["overall"]["answer_present_binary"]["kappa"],
                          date_kappa=q["agreement_strict"]["overall"]["answer_date_exact"]["kappa"],
                          v2=qs["arms"]["v2"]["exact"], free_null=qs["arms"]["free_null"]["exact"],
                          decisions_changed=sum(int(qs[k]["holds"]) != int(h[n]["holds"]) for k, n in
                                                (("H1", "H1_v2_vs_free_null"), ("H2", "H2_answerless"), ("H3", "H3_v2_vs_v1")))))


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
        "government_recommendation": f"{cmp_['government_recommendation']['ambiguous_labels']} of "
                                     f"{cmp_['government_recommendation']['raw_labels']:,} raw labels map to different "
                                     "harmonised recommendations",
    }
    # P8 (eval/prereg9, LOCK9; results/p8/p8_hypotheses.json): where the field's meaning splits, from the documents
    for c in classes.values():
        for x in c.get("fields", []):
            if x.get("p8"):
                ev[x["key"]] = (ev[x["key"]] + "; P8: " if x["key"] in ev else "P8: ") + x["p8"]["where"]
    # whether the field's MEANING was tested across parliaments (data/schema/field_verdict_classes.json `fields`): measured
    # = a statistic in results/census/comparability.json; measured (P8) = the pre-registered meaning test on documents
    # (results/p8/p8_hypotheses.json); otherwise shared by definition, untested (J1, round 5)
    tested = {x["key"]: x for c in classes.values() for x in c.get("fields", [])}
    assert set(tested) == set(FIELD_CLASS) and all(FIELD_CLASS[k] == c["key"] for c in classes.values()
                                                   for k in (x["key"] for x in c.get("fields", []))), "classes out of sync"
    fields = []
    for k, f in m["fields"].items():
        sc = f["status_counts"]
        fields.append(dict(key=k, name=FIELD_NAME.get(k, k.replace("_", " ")), cls=FIELD_CLASS[k], tier=f["tier"],
                           route=f["extraction_route"], eligible=f["eligible_bodies"], metadata=sc["metadata"],
                           mixed=sc["mixed"], pdf=sc["pdf"], no_source=sc["no_source"], evidence=ev.get(k, ""),
                           tested=tested[k]["meaning_tested"], tested_in=tested[k]["evidence"],
                           p8=(dict(verdict=tested[k]["p8"]["verdict"], robust=tested[k]["p8"]["robust"],
                                    roles=tested[k]["p8"]["roles"]) if tested[k].get("p8") else None)))
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
    from ..affair_post import finalize  # product post-processing: no false typed null in the showcase (J1, round 5)

    post = finalize(x["affair"])
    rec = post["affair"]
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
        tested_counts={c: dict(collections.Counter(f["tested"] for f in fields if f["cls"] == c))
                       for c in ("shared", "shared_with_role_split")},
        meaning_measured=sum(f["tested"].startswith("measured") for f in fields),
        meaning_p8=sum(bool(f["p8"]) for f in fields),
        sample=dict(record=rec, suggestions=x.get("suggestions", {}), body_label=label, test="P3b",
                    omitted=post["omitted"], changes=post["changes"],
                    source="results/eval5/p3b__publicai_swiss-ai_apertus-v1.5-8b.json",
                    gold_answer_date=gold["answer_date"], gold_quote=gold.get("answer_date_quote"),
                    gold_page=gold.get("answer_date_page")),
    )


def p7() -> dict | None:
    """P7 (eval/prereg8, LOCK8): Apertus as a closed-set verifier of the adapters' review queue (results/p7,
    results/repair/adapters/p7). The promoted tier is listed next to the counted rows, never inside them."""
    hp = RESULTS / "p7" / "p7_hypotheses.json"
    if not hp.exists():
        return None
    h = json.loads(hp.read_text())
    post = _j("p7/p7_posthoc.json")
    q = _j("repair/adapters/p7/queue_summary.json")
    a = h["arms"]
    arm = lambda k: dict(promoted=_j("p7/test_sample.json")["arms_on_frame"][k],  # noqa: E731
                         precision=a[k]["precision"]["estimate"], dated=a[k]["precision_dated"]["estimate"],
                         recall=a[k]["recall_attainable"]["estimate"])
    return dict(frame=_j("p7/test_sample.json")["frame"], packets=h["packets"],
                h1=dict(correct=h["H1"]["correct"], n=h["H1"]["n"], wilson=h["H1"]["wilson95"], holds=h["H1"]["holds"]),
                h3=dict(correct=h["H3"]["correct"], n=h["H3"]["n"], supported=h["H3"]["supported"]),
                h4=dict(diff=h["H4"]["difference_precision_dated_p7_minus_trivial"]["estimate"],
                        ci=h["H4"]["difference_precision_dated_p7_minus_trivial"]["ci95"], supported=h["H4"]["supported"],
                        unweighted=_j("p7/p7_posthoc_r8.json")["display"]["h4_unweighted_pts"]),
                arms={k: arm(k) for k in ("p7", "free", "trivial")},
                base_rate=post["base_rate"]["yes"], base_rate_dated=post["base_rate"]["yes_dated"],
                qwen=dict(agree=h["qwen_check"]["agree"], n=h["qwen_check"]["n"]),
                review_rows=q["review_rows"], eligible=q["eligible"], promoted=q["promoted"], counted=h["headline"]["counted"],
                by_reason=q["promoted_by_reason"], by_tier=q["promoted_by_date_tier"])


P8_BODY = {"TG": "Thurgau", "VS": "Valais", "351": "Bern city", "261": "Zürich city", "VD": "Vaud", "FR": "Fribourg",
           "5586": "Lausanne", "6643": "Vernier", "5192": "Lugano", "5002": "Bellinzona", "GR": "Graubünden"}


def p8() -> dict | None:
    """P8 (eval/prereg9, LOCK9): does a 'shared' field mean the same thing in every parliament? 66 affairs, 11
    parliaments; registered verdicts, the agreed-labels sensitivity check and the Qwen check (results/p8)."""
    hp = RESULTS / "p8" / "p8_hypotheses.json"
    if not hp.exists():
        return None
    h, q, post, ag = _j("p8/p8_hypotheses.json"), _j("p8/p8_qwen.json"), _j("p8/p8_posthoc.json"), _j("p8/p8_agreement.json")
    classes = {x["key"]: x for c in json.loads((DATA / "schema" / "field_verdict_classes.json").read_text())
               for x in c.get("fields", [])}
    fields = []
    for k, f in h["fields"].items():
        dev = [P8_BODY.get(b, b) for b, r in f["per_parliament"].items() if r["evaluable"] and not r["conforms"]]
        fields.append(dict(key=k, name=FIELD_NAME.get(k, k), verdict=f["verdict"], agreed_only=f["verdict_agreed_only"],
                           qwen_verdict=post["verdicts_on_qwen_labels"][k]["verdict"], n_E=f["pooled"]["n_E"],
                           n=f["pooled"]["n"], ci=f["pooled"]["cluster_ci"], evaluable=f["n_evaluable"], deviating=dev,
                           kappa_a1a2=ag["fields"][k]["kappa"], kappa_qwen=q["fields"][k]["kappa"],
                           robust=classes[k]["p8"]["robust"], where=classes[k]["p8"]["where"],
                           n_conform=sum(bool(r["evaluable"] and r["conforms"]) for r in f["per_parliament"].values()),
                           n_none=sum(r["n_det"] == 0 for r in f["per_parliament"].values())))
    return dict(n=h["n_affairs"], parliaments=h["n_parliaments"], meaning_tested=h["meaning_tested"],
                n_robust=sum(f["robust"] for f in fields),
                n_robust_role_split=sum(f["robust"] and f["verdict"] == "role_split" for f in fields),
                n_robust_body_specific=sum(f["robust"] and f["verdict"] == "body_specific" for f in fields),
                summary=h["summary"], fields=fields, qwen_model=q["model"],
                qwen_usd=_j("p8/p8_qwen_run.json")["usd"], a3_packets=ag["disputed_packets"],
                a3_fields=ag["disputed_fields"],
                joint_as_first=post["qwen_vs_gold_confusion"]["submitter"]["joint_person -> author_person"])


def nights() -> dict | None:
    """The two consecutive real nights in the recommended Docker setup (Actions run 38098822336)."""
    p = RESULTS / "monitor" / "two_nights_docker_38098822336" / "two_nights.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    n1, n2 = d["night1"], d["night2"]
    return dict(run="38098822336", night1_s=n1["wall_s"], night1_bytes=n1["bytes"]["total"], night2_s=n2["wall_s"],
                night2_bytes=n2["bytes"]["total"], night2_bodies=n2["rescanned_bodies"], alerts=n1["alerts"] + n2["alerts"],
                relink=n2["be_repair"]["relink"], fetch=n2["be_repair"]["fetch"])


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
        periods={k: dict(written=v["written"], missing=v["written"] - v["attached"], oral=v["oral"],
                         written_missing=v["written"] - v["attached"] - v["oral"], in_writing=v["written"] - v["oral"])
                 for k, v in par["national_periods"].items()},
        # derived layer: the registered gap minus the answers in OPD with text under an unrecognised heading
        at_most={k: dict(lack_text=v["lack_text_on_affair_at_most"], written=v["written_lack_text_at_most"],
                         unrecognised=v["unrecognised"], after_repair=v["after_repair"])
                 for k, v in par["corrected"]["national"].items()},
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


REPO_URL = "https://github.com/mi11ione/gegenprobe"
# files served from site/downloads/ (copied by `python -m gegenprobe.viewer collect`; the OPD box links them):
# (group, source under track_2a/, what it is)
DOWNLOADS = (
    ("Bern lists", "results/repair/repair_BE_relink.tsv",
     "relink: answers already in OPD under an agenda item, to attach to their affair by the canton's document id"),
    ("Bern lists", "results/repair/repair_BE_fetch.tsv", "fetch: answers OPD does not hold, with the canton's PDF URL"),
    ("Bern lists", "results/repair/repair_BE_review.tsv", "review: rows whose per-row check failed, for a person"),
    ("Bern lists", "results/repair/repair_BE_begin_date.tsv",
     "begin_date: affairs whose begin date is a load timestamp, with the submission event that replaces it"),
    ("Apply plan (dry run)", "results/repair/apply_be/apply_BE_plan.sql.txt",
     "guarded UPDATE statements, one per row, each conditioned on the row's before-state; never executed by us"),
    ("Apply plan (dry run)", "results/repair/apply_be/apply_BE_relink_plan.csv", "relink plan: before and after per row"),
    ("Apply plan (dry run)", "results/repair/apply_be/apply_BE_begin_date_plan.csv",
     "begin_date plan: before and after per row"),
    ("Apply plan (dry run)", "results/repair/apply_be/apply_BE_plan.json",
     "plan summary: rows by status, the export identifier rule and the hash/URL side effect"),
    ("JSON Schemas (v0.1)", "results/schema/affair.schema.json", "Affair: one parliamentary affair with its documents"),
    ("JSON Schemas (v0.1)", "results/schema/doc_extraction.schema.json", "DocExtraction: what the converter writes per document"),
    ("Workbench schema (v0.1)", "schema/gegenprobe_schema.py",
     "schema v0.1 as one Python file for OPD's workbench: pydantic only, no imports from gegenprobe, no I/O; its JSON "
     "Schemas are tested equal to the two above"),
    ("Workbench schema (v0.2)", "schema/gegenprobe_schema_v0_2.py",
     "schema v0.2: v0.1 plus P8's roles (author roles, the instrument's function, the text's language apart from the "
     "tag, submission-date roles, the recommendation's stage); pydantic only, imports the v0.1 file next to it"),
    ("Workbench schema (v0.2)", "results/schema/v0_2/p8_validation.json",
     "the 66 P8 gold affairs converted to v0.2 records, all valid, and the v0.1 samples upgraded losslessly (counts)"),
    ("Federal (Fedlex) list", "results/repair/repair_CHE.tsv.gz",
     "placeholder_replace: federal answers whose OPD document is a placeholder; a work queue (source_url resolved and "
     "verified on a minority of rows; the rest by repair.che backlog)"),
    ("OPD vocabulary errors", "results/census/vocab_bugs.tsv",
     "harmonised labels that are wrong as published, with the affairs carrying them and the census snapshot they were "
     "counted on"),
    ("Apertus-promoted tier (P7)", "results/repair/adapters/p7/promoted_by_apertus.tsv",
     "review rows Apertus promotes, in the adapter-list columns (tier promoted_by_apertus, counted=false): a pre-sorted "
     "batch for a reviewer"),
    ("Apertus-promoted tier (P7)", "results/repair/adapters/p7/promoted.tsv",
     "the same rows as the registered P7 output (P7's own columns)"),
    ("Spot-check kit", "results/opd_spotcheck/spotcheck.csv",
     "30 gold labels (answer dates, P7 promotions, P8 submitter and type) with link, page, span and quote, for anyone to "
     "verify in about an hour; scored by python -m eval.spotcheck score"),
)


def downloads() -> dict:
    """The OPD box's direct downloads (site/downloads/) with size and row count, and the repository URL."""
    files = []
    for group, rel, what in DOWNLOADS:
        p = ROOT / rel
        rows = None
        if p.suffix in (".tsv", ".csv"):
            with open(p, encoding="utf-8") as f:
                rows = sum(1 for line in f if line.strip()) - 1
        files.append(dict(group=group, name=p.name, href=f"downloads/{p.name}", bytes=p.stat().st_size, rows=rows,
                          what=what, source=rel))
    return dict(repo=REPO_URL, files=files, adapter_lists=adapter_lists())


def adapter_lists() -> dict | None:
    """The adapter repair lists the OPD box links (site/downloads/adapters_<BODY>.tsv, written by `viewer collect` via
    census/corrected.write_lists): per parliament the file, rows and counted rows; the manifest says which list wins."""
    from ..census.corrected import MANIFEST

    p = ROOT / "site" / "downloads" / MANIFEST
    if not p.exists():
        return None
    m = json.loads(p.read_text(encoding="utf-8"))
    files = sorted(m["files"], key=lambda f: -f["counted"])
    return dict(manifest=f"downloads/{MANIFEST}", note=m["note"], precedence=m["precedence"], totals=m["totals"],
                files=[dict(body=f["body"], label=f["label"], href=f"downloads/{f['file']}", rows=f["rows"],
                            counted=f["counted"], not_counted=f["not_counted_verified"]) for f in files])


def collect(full_text: bool = False) -> dict:
    par, ev = parliaments(), evaluation()
    ev["p2"] = p2()
    ev["p3"] = p3()
    ev["p3b"] = p3b()
    ev["p4"] = p4()
    ev["p5"] = p5()
    ev["p6"] = p6()
    ev["p7"] = p7()
    ev["p8"] = p8()
    return _finite(
        dict(
            generated=_git("log", "-1", "--format=%h %cI"),
            headline=headline(par, ev),
            documents=documents(full_text),
            parliaments=par,
            evaluation=ev,
            method=method(),
            schema=schema_view(),
            downloads=downloads(),
            adapters=adapters(),
            nights=nights(),
        )
    )
