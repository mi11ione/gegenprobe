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
import re
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


def label_of(key: str, name: str, btype: str | None) -> tuple[str, str]:
    """(display label, level): 'Bern (canton)' vs 'Bern (city)'; OPD's body names are German proper nouns, kept as they are."""
    if key == "CHE":
        return "Federal Assembly", "federal"
    if key == "LIE":
        return "Liechtenstein (Landtag)", "country"
    level = {"canton": "canton", "city": "city", "municipality": "municipality"}.get(btype or "", btype or "")
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


def safe_say(r: dict) -> str:
    """One sentence a journalist can quote, with its caveat, generated from the row (never typed by hand)."""
    a, n = r["periods"]["all"], r["periods"]["y2425"]
    if a["written"] < 20:
        return f"Too few written answers in OPD ({a['written']}) to say anything about this parliament."
    miss = lambda c: c["written"] - c["attached"]  # noqa: E731
    out = []
    if n["written"] >= 20:
        out.append(
            f"In 2024–25, {miss(n):,} of {n['written']:,} written government answers ({_pc(miss(n), n['written'])}) have no "
            f"answer text attached in OpenParlData"
        )
        if abs(miss(a) / a["written"] - miss(n) / n["written"]) > 0.15:
            out.append(
                f"over all years it is {100 * miss(a) / a['written']:.0f}%, so older interventions dominate the all-years figure"
            )
    else:
        out.append(
            f"Over all years, {miss(a):,} of {a['written']:,} written answers ({_pc(miss(a), a['written'])}) have no answer text "
            f"attached in OpenParlData; 2024–25 has too few to compare"
        )
    m = max(1, miss(a))
    if m < 20:
        pass
    elif a["parentless"] + a["agenda"] > 0.5 * m:
        out.append(
            "most of the missing answers are in OpenParlData but not linked to their intervention, an aggregator issue "
            "that OPD has confirmed, not the parliament's"
        )
    elif a["oral"] > 0.3 * m:
        out.append("many 'missing' answers were given orally, so they are not missing")
    elif a["image_only"] > 0.3 * m:
        out.append("most of the missing answers are scans without a text layer, which OCR recovers")
    elif a["absent"] > 0.5 * m:
        out.append("the missing answers are not in OpenParlData; whether the parliament publishes them elsewhere was not checked")
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
    for r in rows:
        r["safe_say"] = safe_say(r)
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
        same_day=_j("census/question.json")["same_day_bodies"],
        tier_counts=m["tier_counts"],
        criteria=m["criteria"],
        repair=_j("repair/summary.json")["by_action"],
        findings=findings,
        attribution=fj.get("opd_attribution"),
        bern=bern,
        snapshot=_snapshot(),
        n_bodies=len(rows),
        periods=PERIOD_LABEL,
    )


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
    head = cols + [f"{p}_{c}" for p in PERIODS for c in per_cols] + ["median_days", "median_flag", "safe_to_say"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(head)
        for r in par["rows"]:
            vals = [r[c] for c in cols]
            for p in PERIODS:
                c = r["periods"][p]
                vals += [round(c[x], 4) if isinstance(c[x], float) else c[x] for x in per_cols]
            w.writerow(vals + [r["median"]["days"], r["median"]["flag"] or "", r["safe_say"]])


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
    eight = RESULTS / "eval" / "heldout__gguf_apertus-v1.5-8b-text-q4_k_m.json"
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
        eight=(json.loads(eight.read_text())["arms"] if eight.exists() else None),
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
    return dict(
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
    ev["p4"] = p4()
    return _finite(
        dict(
            generated=_git("log", "-1", "--format=%h %cI"),
            headline=headline(par, ev),
            documents=documents(full_text),
            parliaments=par,
            evaluation=ev,
            method=method(),
        )
    )
