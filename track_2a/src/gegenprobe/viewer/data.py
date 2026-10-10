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


def parliaments() -> dict:
    s = _j("census/summary.json")
    q = {b["body"]: b for b in _j("census/question.json")["bodies"]}
    rep = _j("repair/summary.json")["by_body"]
    m = _j("census/matrix.json")
    bodies_meta = {b["key"]: b for b in _tsv_gz("bodies")}
    names = body_names()
    cells = collections.defaultdict(dict)
    for c in m["cells"]:
        cells[c["body"]][c["field"]] = dict(st=c["status"], r=c["route"], meta=c["meta"], doc=c["doc"], n=c["n"])
    rows = []
    empty = dict(n=0, ev_answer=0, any_answer_txt=0, gap=0, gap_after_agenda_join=0)
    for k in sorted(set(s["by_body"]) | set(cells)):
        v = s["by_body"].get(k, empty)
        bm = bodies_meta.get(k, {})
        qq = q.get(k, {})
        rows.append(
            dict(
                key=k,
                name=names.get(k, k),
                type=bm.get("type"),
                canton=bm.get("canton") or (k if len(k) == 2 else ""),
                lang=bm.get("lang"),
                n=v["n"],
                written=v["ev_answer"],
                with_text=v["any_answer_txt"],
                gap=v["gap"],
                gap_after_agenda=v["gap_after_agenda_join"],
                link={
                    x: v.get(f"link_{x}", 0)
                    for x in ("attached", "agenda", "parentless", "image_only", "oral", "absent", "not_applicable")
                },
                median_days=qq.get("median_days"),
                same_day=qq.get("same_day_share"),
                share_now=qq.get("text_share_now"),
                share_after=qq.get("text_share_after_relink"),
                repair=rep.get(k, {}),
                fields=cells.get(k, {}),
                in_scope=k in s["by_body"],
            )
        )
    rows.sort(key=lambda r: (-r["written"], -r["n"]))
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
    return dict(
        rows=rows,
        fields=fields,
        national=s["national"],
        gap_share=s["national_gap_share"],
        decomposition=s["gap_prime_decomposition"],
        question=_j("census/question.json")["national"],
        tier_counts=m["tier_counts"],
        criteria=m["criteria"],
        repair=_j("repair/summary.json")["by_action"],
        findings=[
            dict(id=f["id"], statement=f["statement"], count=f.get("count"), share=f.get("share"))
            for f in _j("census/findings.json")["findings"]
        ],
    )


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
    deviations = re.findall(r"^## (D\d+) \(([^)]*)\): (.+)$", dev, re.M)
    lab_commit = _git("log", "-1", "--format=%h %cI", "--", "data/gold/heldout_labels.jsonl")
    lock_commit = _git("log", "--diff-filter=A", "-1", "--format=%h %cI", "--", "eval/prereg/LOCK")
    eight = RESULTS / "eval" / "heldout__gguf_apertus-v1.5-8b-text-q4_k_m.json"
    return dict(
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
