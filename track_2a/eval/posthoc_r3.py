"""POST-HOC round-3 analyses (not pre-registered; labelled as such in every output). Offline: reads the committed results
files, the committed hash-keyed model cache (data/model_cache, no model call) and the committed gold/census tables.
Frozen files (eval/naive_baseline.py, eval/arms.py, eval/score.py, convert/*) are imported, never changed.

  naive    The registered naive date parser (eval/naive_baseline.py:to_iso) accepts ISO and what lattice.dates parses; it
           rejects DD-MM-YYYY and DD-<month>-YYYY, and eval/arms.py then scores those answers as null. The stored
           generations are re-parsed with a corrected parser and re-scored with the frozen scorer (eval/score.py summarise).
           -> results/eval/posthoc_r3_naive_reparsed.json
  paired   Paired exact McNemar tests (documents) and body-level sign / cluster-permutation tests of the pointer against the
           strongest baselines (type-gated latest printed date, re-parsed naive_null, rules on all documents); provenance of
           every returned date per arm; θ sensitivity (θ = 0, the PREREG2 secondary); the P1 tie-break audit.
           -> results/eval/posthoc_r3_paired.json
  oracle   Agreement of the agent-made gold with every non-LLM source in the repository: OPD written-answer events, dates
           and decision numbers in the publishers' own document titles, OPD submission events (ordering), OPD document
           type (null class), Bern OGD submission dates (P3, if the canton CSV is present), lock-to-label commit gaps.
           -> results/eval/posthoc_r3_gold_oracle.json

    PYTHONPATH=src:. python -m eval.posthoc_r3 [naive|paired|oracle|all]
"""

from __future__ import annotations

import collections
import csv
import datetime as dt
import itertools
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

from eval import arms
from eval import naive_baseline as nb
from eval.gold import annotate as A
from eval.score import outcome, summarise
from gegenprobe import llm
from gegenprobe.convert import lattice
from gegenprobe.convert.pointer import doc_text
from gegenprobe.paths import DATA, RESULTS, ROOT

LABEL = "POST-HOC (not pre-registered): round-3 jury follow-up, 10 Oct 2026"
BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
CACHE_BUILD, MODEL = "publicai:swiss-ai/apertus-v1.5-8b", "swiss-ai/apertus-v1.5-8b"
SPLITS = {
    "P1": dict(res=RESULTS / "eval" / f"heldout__{BUILD}.json", docs=DATA / "gold" / "heldout_docs.jsonl",
               labels=DATA / "gold" / "heldout_labels.jsonl"),
    "P2": dict(res=RESULTS / "eval2" / f"p2__{BUILD}.json", docs=DATA / "gold2" / "p2_docs.jsonl",
               labels=DATA / "gold2" / "p2_labels.jsonl"),
}
OUT_NAIVE = RESULTS / "eval" / "posthoc_r3_naive_reparsed.json"
OUT_PAIRED = RESULTS / "eval" / "posthoc_r3_paired.json"
OUT_ORACLE = RESULTS / "eval" / "posthoc_r3_gold_oracle.json"


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in open(p, encoding="utf-8")]


# ------------------------------------------------------------------------------------------------ corrected date parser
_ACCENTS = str.maketrans("äàâéèêëîïôöûüç", "aaaeeeeiioouuc")
MONTHS = {}
for _names in nb.MON.values():
    for _i, _n in enumerate(_names):
        MONTHS[_n] = _i + 1
        MONTHS[_n.translate(_ACCENTS)] = _i + 1


def _mk(y: int, m: int, d: int) -> str | None:
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def to_iso_fixed(v) -> tuple[str | None, str]:
    """(ISO date or None, how it was read). Accepts every form the stored naive outputs contain: ISO, DD.MM.YYYY,
    DD-MM-YYYY, DD/MM/YYYY, 'D[.] <month> YYYY', 'DD-<month>-YYYY' (DE/FR/IT month names, '1er'), else lattice.dates.
    A verbal non-answer ('Nicht verfügbar', 'Non disponibile') is a null; a month-year ('09.2001') is not a day date and
    stays null, as in the registered parser."""
    if nb.isnull(v):
        return None, "null"
    s = str(v).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s[:10]):
        return s[:10], "iso"
    m = re.fullmatch(r"(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{4})", s)
    if m:
        return _mk(int(m.group(3)), int(m.group(2)), int(m.group(1))), "d_m_y_numeric"
    m = re.fullmatch(r"(\d{1,2})(?:er|\.)?[\s\-]+([^\W\d_]+)[\s\-.]+(\d{4})", s)
    if m and m.group(2).lower() in MONTHS:
        return _mk(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))), "d_month_y"
    c = lattice.dates([s])
    if c:
        return c[0]["value"], "lattice"
    if not re.search(r"\d", s):
        return None, "verbal_null"
    return None, "not_a_day_date"


def registered_pred(stored_date) -> str | None:
    """What eval/arms.py scored: the stored to_iso result, with 'unparseable:…' turned into null."""
    return None if (stored_date is None or str(stored_date).startswith("unparseable")) else stored_date


# --------------------------------------------------------------------------------------- documents and cached generations
def _docs(split: str) -> dict[int, dict]:
    """Labelled documents with page texts, exactly as the frozen runner loaded them (P2 via the run_p2 staging)."""
    if split == "P1":
        return {d["doc_id"]: d for d in arms.load_split("heldout")}
    from eval.gold2 import run_p2

    old = arms.DATA
    arms.DATA = run_p2.staged_data()
    try:
        return {d["doc_id"]: d for d in arms.load_split("heldout")}
    finally:
        arms.DATA = old


def _full_generation(text: str, lang: str, arm: str, seed: int) -> str | None:
    """The full cached generation for exactly the request eval.naive_baseline.run_doc sent (no model call)."""
    payload = dict(model=MODEL, temperature=0.0, max_tokens=200, seed=seed,
                   messages=[{"role": "user", "content": nb.prompt(lang, arm).replace("{doc}", text)}])
    hit = llm.ModelCache(CACHE_BUILD, readonly=True).get(llm.ModelCache.key(CACHE_BUILD, "generate", payload))
    return None if hit is None else hit["text"]


def _quote_check(iso: str | None, beleg, text: str) -> dict:
    """Receipt of a naive answer: the quote occurs verbatim (whitespace-normalised) in the text the model saw, and it
    contains the returned date (any printed form lattice.dates reads, or the frozen date_forms)."""
    if iso is None or nb.isnull(beleg):
        return dict(quote=not nb.isnull(beleg), verbatim=False, contains_date=False)
    b = str(beleg)
    verbatim = nb.norm(b) in nb.norm(text)
    in_quote = iso in {c["value"] for c in lattice.dates([b])} or any(f in nb.norm(b) for f in nb.date_forms(iso))
    return dict(quote=True, verbatim=verbatim, contains_date=in_quote)


def naive_rows(split: str, with_cache: bool = True) -> list[dict]:
    """One row per document: registered and re-parsed naive predictions (plain, null), with the null arm's quote check."""
    res = json.loads(SPLITS[split]["res"].read_text())
    docs = _docs(split) if with_cache else {}
    out = []
    for r in res["per_doc"]:
        row = dict(doc_id=r["doc_id"], cell=r["cell"], gold=r["gold"], lenient=r.get("lenient") or [],
                   doc_dates=r.get("doc_dates") or [])
        d = docs.get(r["doc_id"])
        text = doc_text(d["pages"])[0] if d else None
        for arm in ("plain", "null"):
            st = r[f"naive_{arm}"]
            gen = st["gen"]
            if d is not None:
                full = _full_generation(text, arms._lang(d), arm, r["doc_id"] % 100000)
                if full is None:
                    raise SystemExit(f"model cache miss for {split} {r['doc_id']} naive_{arm}")
                if full[:400] != gen:
                    raise SystemExit(f"cached generation differs from the stored prefix: {split} {r['doc_id']} naive_{arm}")
                gen = full
            parsed = nb.parse(gen)
            raw = parsed.get("antwort_datum")
            fixed, how = to_iso_fixed(raw)
            row[f"naive_{arm}"] = dict(raw=raw, registered=registered_pred(st["date"]), reparsed=fixed, how=how,
                                       registered_receipt_ok=st.get("receipt_ok"))
            if arm == "null" and text is not None:
                row["naive_null"]["receipt"] = _quote_check(fixed, parsed.get("beleg"), text)
        out.append(row)
    return out


# ------------------------------------------------------------------------------------------------------------------ naive
def _score_rows(rows: list[dict], arm: str, which: str) -> list[dict]:
    return [dict(cell=r["cell"], gold=r["gold"], lenient=r["lenient"], doc_dates=r["doc_dates"], pred=r[arm][which],
                 route="apertus") for r in rows]


SUP = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def pstr(p: float) -> str:
    """p-value as printed in the documents: two significant digits, '5.3 × 10⁻⁴' below 0.001, '1' for 1."""
    if p >= 0.9995:
        return "1"
    if p >= 0.001:
        return f"{p:.2g}" if p < 0.1 else f"{p:.2f}"
    m, e = f"{p:.1e}".split("e")
    return f"{m} × 10{str(int(e)).translate(SUP)}"


def ci_pct(ci: list) -> list:
    return [round(100 * ci[0], 1), round(100 * ci[1], 1)]


def _headline(s: dict) -> dict:
    a = s["ALL"]
    return {k: a[k] for k in ("n", "exact", "correct", "correct_null", "false_null", "misattributed", "fabricated",
                              "invented", "invented_on_null", "n_gold_null", "n_gold_value", "exact_ci")}


def naive() -> dict:
    out = dict(label=LABEL, defect=(
        "eval/naive_baseline.py:to_iso (lines 91-99) accepts ISO or what lattice.dates parses; lattice does not read "
        "DD-MM-YYYY or DD-<month>-YYYY, so to_iso returns 'unparseable:…' and eval/arms.py:169 scores the answer as null. "
        "The prompts ask for JJJJ-MM-TT / AAAA-MM-JJ / AAAA-MM-GG; Apertus sometimes answered DD-MM-YYYY instead."),
        parser="eval/posthoc_r3.py:to_iso_fixed", scorer="eval/score.py:summarise (frozen, strict and lenient)", splits={})
    for split, cfg in SPLITS.items():
        res = json.loads(cfg["res"].read_text())
        rows = naive_rows(split)
        blk = dict(n=len(rows))
        for arm in ("naive_plain", "naive_null"):
            reg = summarise(_score_rows(rows, arm, "registered"), True)
            if _headline(reg) != _headline(res["arms"][arm]["strict"]):
                raise SystemExit(f"registered {split} {arm} not reproduced")
            fixed_rows = _score_rows(rows, arm, "reparsed")
            fix_s, fix_l = summarise(fixed_rows, True), summarise(fixed_rows, False)
            changed = []
            for r in rows:
                a = r[arm]
                if a["registered"] != a["reparsed"]:
                    o1 = outcome(a["registered"], r["gold"], set(r["doc_dates"]), r["lenient"], True)
                    o2 = outcome(a["reparsed"], r["gold"], set(r["doc_dates"]), r["lenient"], True)
                    changed.append(dict(doc_id=r["doc_id"], cell=r["cell"], raw=a["raw"], how=a["how"], gold=r["gold"],
                                        registered=o1, reparsed=o2))
            agree_parsed = sum(r[arm]["registered"] == r[arm]["reparsed"] for r in rows if r[arm]["registered"] is not None)
            n_parsed = sum(r[arm]["registered"] is not None for r in rows)
            unread = [dict(doc_id=r["doc_id"], raw=r[arm]["raw"], how=r[arm]["how"]) for r in rows
                      if r[arm]["reparsed"] is None and r[arm]["how"] not in ("null",)]
            fabricated = [dict(doc_id=r["doc_id"], cell=r["cell"], pred=r[arm]["reparsed"], gold=r["gold"]) for r in rows
                          if outcome(r[arm]["reparsed"], r["gold"], set(r["doc_dates"]), r["lenient"], True) == "fabricated"]
            blk[arm] = dict(
                registered=_headline(reg), reparsed=_headline(fix_s), reparsed_lenient=_headline(fix_l),
                registered_exact=[reg["ALL"]["exact"], len(rows)], reparsed_exact=[fix_s["ALL"]["exact"], len(rows)],
                registered_exact_ci_pct=ci_pct(reg["ALL"]["exact_ci"]), reparsed_exact_ci_pct=ci_pct(fix_s["ALL"]["exact_ci"]),
                reparsed_per_cell={c: [v["exact"], v["n"]] for c, v in fix_s.items() if c != "ALL"},
                changed_documents=changed, n_changed=len(changed),
                parser_agrees_on_registered_values=[agree_parsed, n_parsed],
                not_read_as_a_date=unread,
                fabricated_after_reparse=fabricated, n_fabricated_after_reparse=len(fabricated),
            )
        out["splits"][split] = blk
    OUT_NAIVE.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


# ----------------------------------------------------------------------------------------------------------------- paired
def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n)


def _ok(pred, r) -> bool:
    return outcome(pred, r["gold"], set(r["doc_dates"]), r.get("lenient"), True) in ("correct", "correct_null")


def _pair(rows: list[dict], a: str, b: str) -> dict:
    out = {}
    for name, sel in (("all", rows), ("gold_value", [r for r in rows if r["gold"] is not None]),
                      ("gold_null", [r for r in rows if r["gold"] is None])):
        x = sum(_ok(r["pred"][a], r) and not _ok(r["pred"][b], r) for r in sel)
        y = sum(_ok(r["pred"][b], r) and not _ok(r["pred"][a], r) for r in sel)
        out[name] = dict(n=len(sel), **{f"{a}_only": x, f"{b}_only": y}, p_mcnemar_exact=mcnemar_exact(x, y),
                         p_str=pstr(mcnemar_exact(x, y)),
                         exact=[sum(_ok(r["pred"][a], r) for r in sel), sum(_ok(r["pred"][b], r) for r in sel)])
    # body level, all documents: per body (a_only - b_only); sign test; exact cluster permutation (joint flip per body)
    per = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        per[r["body"]][0] += _ok(r["pred"][a], r) and not _ok(r["pred"][b], r)
        per[r["body"]][1] += _ok(r["pred"][b], r) and not _ok(r["pred"][a], r)
    diffs = [x - y for x, y in per.values() if x or y]
    pos, neg = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
    nn = pos + neg
    sign_p = min(1.0, 2 * sum(math.comb(nn, i) for i in range(min(pos, neg) + 1)) / 2**nn) if nn else 1.0
    obs = sum(diffs)
    flips = [sum(s * d for s, d in zip(sg, diffs)) for sg in itertools.product((1, -1), repeat=len(diffs))]
    perm_p = sum(abs(f) >= abs(obs) for f in flips) / len(flips)
    out["bodies"] = dict(n_bodies=len(per), **{f"favour_{a}": pos, f"favour_{b}": neg},
                         tied_with_discordance=sum(1 for d in diffs if d == 0), sign_p_two_sided=sign_p,
                         cluster_permutation_p_two_sided=perm_p, sign_p_str=pstr(sign_p), cluster_permutation_p_str=pstr(perm_p),
                         per_body={k: dict(zip((f"{a}_only", f"{b}_only"), v)) for k, v in sorted(per.items()) if any(v)})
    return out


def _theta0(p: dict):
    v = p.get("value")
    return None if (v is not None and p.get("margin") is not None and p["margin"] > 0) else v


def paired_rows(split: str, naive: list[dict]) -> list[dict]:
    cfg = SPLITS[split]
    res = json.loads(cfg["res"].read_text())
    meta = {d["doc_id"]: d for d in _jsonl(cfg["docs"])}
    nv = {r["doc_id"]: r for r in naive}
    rows = []
    for r in res["per_doc"]:
        dd = r.get("doc_dates") or []
        latest = max(dd) if dd else None
        dtype = meta[r["doc_id"]]["dtype"]
        st = r["rules"]["status"]
        cas0 = r["rules"]["value"] if st == "value" else (None if st == "null" else _theta0(r["pointer"]))
        pred = dict(
            rules=r["rules"].get("value") if st == "value" else None,
            pointer=r["pointer"].get("value"),
            pointer_theta0=_theta0(r["pointer"]),
            cascade=r["cascade"].get("value"),
            cascade_theta0=cas0,
            naive_null_registered=nv[r["doc_id"]]["naive_null"]["registered"],
            naive_null_reparsed=nv[r["doc_id"]]["naive_null"]["reparsed"],
            naive_plain_reparsed=nv[r["doc_id"]]["naive_plain"]["reparsed"],
            latest_date_gated_by_doc_type=None if dtype == "intervention" else latest,
            latest_date_on_answer_docs_only=latest if dtype == "answer" else None,
        )
        rows.append(dict(doc_id=r["doc_id"], cell=r["cell"], body=meta[r["doc_id"]]["body"], dtype=dtype, gold=r["gold"],
                         lenient=r.get("lenient") or [], doc_dates=dd, pred=pred,
                         receipt=nv[r["doc_id"]]["naive_null"].get("receipt")))
    return rows


def _provenance(rows: list[dict], arm: str) -> dict:
    vals = [r for r in rows if r["pred"][arm] is not None]
    printed = [r for r in vals if r["pred"][arm] in set(r["doc_dates"])]
    wrong = [r for r in vals if not _ok(r["pred"][arm], r)]
    out = dict(values=len(vals), printed_in_document=len(printed), not_printed=len(vals) - len(printed),
               wrong_values=len(wrong), values_on_gold_null=sum(r["gold"] is None for r in vals))
    if arm.startswith("naive_null"):
        rc = [r["receipt"] for r in vals if r.get("receipt")]
        out["quote_given"] = sum(x["quote"] for x in rc)
        out["quote_verbatim_in_text"] = sum(x["verbatim"] for x in rc)
        out["quote_verbatim_and_contains_date"] = sum(x["verbatim"] and x["contains_date"] for x in rc)
        out["wrong_values_passing_quote_check"] = sum(
            bool(r.get("receipt")) and r["receipt"]["verbatim"] and r["receipt"]["contains_date"] for r in wrong)
    return out


def tie_breaks() -> dict:
    """Which annotator's label the tie-break agent A3 chose (key = answer date + recommendation, the frozen merge key)."""
    out = {}
    for split, d, order in (("P1", DATA / "gold" / "annotations", "A1 always shown as X"),
                            ("P2", DATA / "gold2" / "annotations", "seeded random X/Y order (PREREG2)")):
        a1, a2, a3 = ({x["doc_id"]: x for x in _jsonl(d / f"{k}.jsonl")} for k in ("A1", "A2", "A3"))
        c = collections.Counter()
        date_dis = collections.Counter()
        for i, x in a3.items():
            if i not in a1 or i not in a2 or A.key(a1[i]) == A.key(a2[i]):
                continue
            side = "A1" if A.key(x) == A.key(a1[i]) else ("A2" if A.key(x) == A.key(a2[i]) else "neither")
            c[side] += 1
            what = "date" if a1[i]["answer_date"] != a2[i]["answer_date"] else "recommendation_only"
            c[what] += 1
            if what == "recommendation_only" and {a1[i]["recommendation"], a2[i]["recommendation"]} == {"none", "not_applicable"}:
                c["recommendation_none_vs_not_applicable"] += 1
            if what == "date":
                date_dis[side] += 1
        out[split] = dict(order=order, tie_breaks=c["A1"] + c["A2"] + c["neither"], sided_with_A1=c["A1"],
                          sided_with_A2=c["A2"], neither=c["neither"], differing_in_answer_date=c["date"],
                          differing_only_in_recommendation=c["recommendation_only"],
                          of_which_none_vs_not_applicable=c["recommendation_none_vs_not_applicable"],
                          answer_date_ties_sided=dict(date_dis))
    return out


def paired() -> dict:
    out = dict(label=LABEL, correctness="frozen eval/score.py outcome, strict; exact = correct or correct_null",
               tests="exact two-sided McNemar on documents; bodies: two-sided sign test and exact cluster permutation "
                     "(all joint flips of a body's documents), all documents", splits={})
    for split in SPLITS:
        rows = paired_rows(split, naive_rows(split))
        base = json.loads((RESULTS / "eval" / "baselines_dates.json").read_text())["P1_heldout" if split == "P1" else "P2_unseen"]
        for b in ("latest_date_gated_by_doc_type", "latest_date_on_answer_docs_only"):
            if sum(_ok(r["pred"][b], r) for r in rows) != base[b]["exact"]:
                raise SystemExit(f"{split} {b} does not reproduce results/eval/baselines_dates.json")
        arms_ = list(rows[0]["pred"])
        exact = {a: [sum(_ok(r["pred"][a], r) for r in rows), len(rows)] for a in arms_}
        comps = {}
        for a, b in (("pointer", "rules"), ("pointer", "latest_date_gated_by_doc_type"),
                     ("pointer", "latest_date_on_answer_docs_only"), ("pointer", "naive_null_reparsed"),
                     ("pointer", "naive_null_registered"), ("pointer_theta0", "naive_null_reparsed"),
                     ("cascade", "rules"), ("cascade", "naive_null_reparsed"), ("rules", "naive_null_reparsed"),
                     ("rules", "latest_date_on_answer_docs_only")):
            comps[f"{a}~{b}"] = _pair(rows, a, b)
        gold_bodies = collections.Counter(r["body"] for r in rows if r["gold"] is not None)
        out["splits"][split] = dict(
            n=len(rows), exact=exact, comparisons=comps,
            gold_value_documents=sum(gold_bodies.values()), gold_value_bodies=len(gold_bodies),
            bodies_in_split=len({r["body"] for r in rows}), gold_values_per_body=dict(sorted(gold_bodies.items())),
            provenance={a: _provenance(rows, a) for a in ("rules", "pointer", "cascade", "naive_plain_reparsed",
                                                          "naive_null_reparsed")},
            theta_sensitivity=dict(
                note="θ = 10.40 was fitted on P1 dev and frozen; θ = 0 is PREREG2's registered secondary on P2 (no decision "
                     "attached) and a sensitivity on P1. θ = 0 decisions from the same cached margins: a value is kept iff its "
                     "margin <= 0.",
                pointer_theta_10_40=exact["pointer"], pointer_theta_0=exact["pointer_theta0"],
                cascade_theta_10_40=exact["cascade"], cascade_theta_0=exact["cascade_theta0"],
                pointer_values_on_gold_null=[sum(r["pred"]["pointer"] is not None for r in rows if r["gold"] is None),
                                             sum(r["gold"] is None for r in rows)],
                pointer_theta0_values_on_gold_null=[sum(r["pred"]["pointer_theta0"] is not None for r in rows
                                                        if r["gold"] is None), sum(r["gold"] is None for r in rows)],
            ),
        )
    h2 = json.loads((RESULTS / "eval2" / f"hypotheses2__{BUILD}.json").read_text())["subsets"]["all"]
    out["splits"]["P2"]["theta_sensitivity"]["registered_hypotheses2_theta_0_pointer_exact"] = \
        h2["theta_0"]["arms"]["pointer"]["exact"]
    out["tie_breaks"] = tie_breaks()
    OUT_PAIRED.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


# ----------------------------------------------------------------------------------------------------------------- oracle
TITLE_DATE = [  # publisher titles that name the answer's decision date (TI 'Risposta del CdS del …', BE 'RRB-dd.mm.yyyy')
    re.compile(r"Risposta del CdS del (\d{2})\.(\d{2})\.(\d{4})"),
    re.compile(r"\bRRB-(\d{2})\.(\d{2})\.(\d{4})"),
]
TITLE_NUMBER = re.compile(r"^RRB[ _-]?(\d{1,5})[ _]")


def _title_date(name: str) -> str | None:
    for rx in TITLE_DATE:
        m = rx.search(name or "")
        if m:
            return _mk(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _days(a: str, b: str) -> int:
    return (dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days


def _opd_events(affairs: set[int]) -> tuple[dict, dict]:
    """affair -> written-answer event dates (census definition, as annotate.opd_answer_dates); affair -> submission dates
    (harmonised event id 1, 'Eingereicht'/'Dépôt')."""
    from gegenprobe.census import defs, tables

    written, submitted = collections.defaultdict(list), collections.defaultdict(list)
    for e in tables.rows("events"):
        a = tables.i(e["affair"])
        if a not in affairs or not e["date"]:
            continue
        if defs.classify_event(e["title"], tables.i(e["hid"])) == "written":
            written[a].append(e["date"][:10])
        if tables.i(e["hid"]) == 1:
            submitted[a].append(e["date"][:10])
    return written, submitted


def _date_check(items: list[tuple]) -> dict:
    """items: (id, gold, [oracle dates], quote). agree = gold equals an oracle date; near = within 7 days (decision vs
    dispatch/publication); far = otherwise."""
    c, ex = collections.Counter(), []
    for i, gold, od, quote in items:
        if not od:
            c["no_oracle"] += 1
            continue
        c["checked"] += 1
        if gold in od:
            c["agree"] += 1
            continue
        dmin = min((_days(o, gold) for o in od), key=abs)
        k = "disagree_within_7_days" if abs(dmin) <= 7 else "disagree_more_than_7_days"
        c[k] += 1
        ex.append(dict(id=i, gold=gold, oracle=od, nearest_offset_days=dmin, gold_quote=quote))
    return dict(checked=c["checked"], agree=c["agree"], disagree_within_7_days=c["disagree_within_7_days"],
                disagree_more_than_7_days=c["disagree_more_than_7_days"], no_oracle=c["no_oracle"], disagreements=ex)


def _bern_ogd() -> dict[str, dict]:
    p = Path(os.environ.get("GP_BE_OGD", Path.home() / "Desktop/hackapertus/spikes/recovery/data/be_ogd")) / "geschaeft.csv"
    if not p.exists():
        return {}
    return {r["geschaeft_nr"]: r for r in csv.DictReader(open(p, encoding="utf-8"))}


def _git_added(rel: str) -> str | None:
    try:
        r = subprocess.run(["git", "log", "--diff-filter=A", "--format=%h %cI", "--", rel], cwd=ROOT, capture_output=True,
                           text=True, timeout=30)
        lines = r.stdout.strip().splitlines()
        return lines[-1] if lines else None
    except Exception:
        return None


def oracle() -> dict:
    out = dict(label=LABEL, scope=(
        "Every gold label in P1-P4 was set by Claude agents (A1 Opus, A2 Sonnet, A3 Opus on disagreements); no human "
        "labelled or adjudicated. These are the non-LLM sources in the repository that can confirm or contradict a label. "
        "None of them was used to set a label."), splits={})
    p1d = {d["doc_id"]: d for d in _jsonl(SPLITS["P1"]["docs"])}
    p2d = {d["doc_id"]: d for d in _jsonl(SPLITS["P2"]["docs"])}
    p3a = {a["affair_id"]: a for a in _jsonl(DATA / "gold3" / "p3_affairs.jsonl")}
    p3l = {x["affair_id"]: x for x in _jsonl(DATA / "gold3" / "p3_labels.jsonl")}
    affairs = {d.get("affair_id") for d in list(p1d.values()) + list(p2d.values()) if d.get("affair_id")} | set(p3a)
    written, submitted = _opd_events(affairs)
    covered_any = {}
    for split, docs in (("P1", p1d), ("P2", p2d)):
        labs = _jsonl(SPLITS[split]["labels"])
        val = [x for x in labs if x["answer_date"]]
        opd = _date_check([(x["doc_id"], x["answer_date"], written.get(docs[x["doc_id"]].get("affair_id")) or [],
                            x.get("answer_date_quote")) for x in val])
        title = _date_check([(x["doc_id"], x["answer_date"], [t] if (t := _title_date(docs[x["doc_id"]]["name"])) else [],
                              x.get("answer_date_quote")) for x in val])
        title_on_null = [dict(doc_id=x["doc_id"], body=docs[x["doc_id"]]["body"], title=docs[x["doc_id"]]["name"],
                              title_date=_title_date(docs[x["doc_id"]]["name"]), answer_present=x["answer_present"],
                              dtype=x.get("dtype"))
                         for x in labs if not x["answer_date"] and _title_date(docs[x["doc_id"]]["name"])]
        nums = []
        for x in labs:
            m = TITLE_NUMBER.match(docs[x["doc_id"]]["name"] or "")
            if m:
                g = re.sub(r"\D", "", str(x.get("decision_number") or ""))
                nums.append(dict(doc_id=x["doc_id"], title=docs[x["doc_id"]]["name"][:60], title_number=m.group(1),
                                 gold=x.get("decision_number"), agree=g == m.group(1)))
        order = collections.Counter()
        order_bad = []
        for x in val:
            sd = submitted.get(docs[x["doc_id"]].get("affair_id")) or []
            if not sd:
                order["no_submission_event"] += 1
                continue
            order["checked"] += 1
            if x["answer_date"] >= min(sd):
                order["answer_not_before_submission"] += 1
            else:
                order_bad.append(dict(doc_id=x["doc_id"], gold=x["answer_date"], opd_submitted=sorted(sd)))
        xt = collections.Counter((docs[x["doc_id"]]["dtype"], "date" if x["answer_date"] else "null") for x in labs)
        cov = {x["doc_id"] for x in val if (written.get(docs[x["doc_id"]].get("affair_id"))
                                            or _title_date(docs[x["doc_id"]]["name"]))}
        exact_any = {x["doc_id"] for x in val if x["answer_date"] in (written.get(docs[x["doc_id"]].get("affair_id")) or [])
                     or x["answer_date"] == _title_date(docs[x["doc_id"]]["name"])}
        covered_any[split] = [len(cov), len(val)]
        out["splits"][split] = dict(
            n_documents=len(labs), gold_value_documents=len(val),
            answer_date_vs_opd_written_answer_event=opd,
            answer_date_vs_publisher_title_date=title,
            title_date_on_gold_null_documents=title_on_null,
            gold_value_documents_with_any_non_llm_date=[len(cov), len(val)],
            gold_value_documents_confirmed_exactly_by_a_non_llm_source=[len(exact_any), len(val)],
            decision_number_vs_publisher_title=dict(checked=len(nums), agree=sum(n["agree"] for n in nums),
                                                    disagreements=[n for n in nums if not n["agree"]]),
            answer_not_before_opd_submission=dict(checked=order["checked"],
                                                  holds=order["answer_not_before_submission"],
                                                  no_submission_event=order["no_submission_event"], violations=order_bad),
            opd_doc_type_vs_gold_class={f"{a}|{b}": n for (a, b), n in sorted(xt.items())},
        )
    # P3: whole affairs (answer date, submission date)
    be = _bern_ogd()
    val = [x for x in p3l.values() if x.get("answer_date")]
    opd3 = _date_check([(x["affair_id"], x["answer_date"], written.get(x["affair_id"]) or [], x.get("answer_date_quote"))
                        for x in val])

    def _ans_title(aid):
        for d in p3a[aid]["docs"]:
            if d["role"] == "answer" and _title_date(d.get("name") or ""):
                return _title_date(d["name"])
        return None

    title3 = _date_check([(x["affair_id"], x["answer_date"], [t] if (t := _ans_title(x["affair_id"])) else [],
                           x.get("answer_date_quote")) for x in val])
    sub = [x for x in p3l.values() if x.get("submitted")]
    opd_sub = _date_check([(x["affair_id"], x["submitted"], submitted.get(x["affair_id"]) or [], x.get("submitted_quote"))
                           for x in sub])
    be_items = []
    for x in sub:
        a = p3a[x["affair_id"]]
        if a["body"] == "BE" and be:
            g = be.get(x.get("number") or "")
            be_items.append((x["affair_id"], x["submitted"], [g["geschaeft_vorstoss_eingereicht_datum"][:10]]
                             if g and g.get("geschaeft_vorstoss_eingereicht_datum") else [], x.get("submitted_quote")))
    out["splits"]["P3"] = dict(
        n_affairs=len(p3l), gold_answer_dates=len(val), gold_submitted_dates=len(sub),
        answer_date_vs_opd_written_answer_event=opd3, answer_date_vs_publisher_title_date=title3,
        submitted_vs_opd_submission_event=opd_sub,
        submitted_vs_bern_ogd=(_date_check(be_items) if be else "Bern OGD geschaeft.csv not present (GP_BE_OGD)"),
        caveat="P3 arm C reads OPD metadata, so OPD agreement here is also what arm C would return; it is a check of the "
               "gold, not of the extractor.",
    )
    # timing: lock commit vs first label commit (git), and whether annotation files carry any time field
    timing = {}
    for name, lock, lab in (("P1", "eval/prereg/LOCK", "data/gold/heldout_labels.jsonl"),
                            ("P2", "eval/prereg2/LOCK2", "data/gold2/p2_labels.jsonl"),
                            ("P3", "eval/prereg3/LOCK3", "data/gold3/p3_labels.jsonl"),
                            ("P4", "eval/prereg4/LOCK4", "data/gold4/p4_heldout_labels.jsonl")):
        lk, lb = _git_added(lock), _git_added(lab)
        gap = None
        if lk and lb:
            t1, t2 = (dt.datetime.fromisoformat(s.split()[1]) for s in (lk, lb))
            gap = round((t2 - t1).total_seconds())
        timing[name] = dict(lock_commit=lk, label_commit=lb, gap_seconds=gap,
                            gap_str=None if gap is None else f"{gap // 60} min {gap % 60} s")
    keys = set()
    for d in ("gold", "gold2", "gold3"):
        for f in (DATA / d / "annotations").glob("A*.jsonl"):
            for x in _jsonl(f):
                keys |= set(x)
    timing["annotation_fields"] = sorted(keys)
    timing["annotation_files_have_time_fields"] = any(re.search(r"(^|_)(ts|time|timestamp|created|written)($|_)", k)
                                                      for k in keys)
    timing["what_the_clock_shows"] = ("the LOCK commit precedes the commit that adds the labels; lock.py also refuses to "
                                      "write a LOCK while a label file exists in the working tree. It does not show when "
                                      "annotation started: annotation files carry no timestamps.")
    out["lock_to_label_commit"] = timing
    out["summary"] = dict(
        P1_opd_event=[out["splits"]["P1"]["answer_date_vs_opd_written_answer_event"]["agree"],
                      out["splits"]["P1"]["answer_date_vs_opd_written_answer_event"]["checked"]],
        P2_opd_event=[out["splits"]["P2"]["answer_date_vs_opd_written_answer_event"]["agree"],
                      out["splits"]["P2"]["answer_date_vs_opd_written_answer_event"]["checked"]],
        P1_title_date=[out["splits"]["P1"]["answer_date_vs_publisher_title_date"]["agree"],
                       out["splits"]["P1"]["answer_date_vs_publisher_title_date"]["checked"]],
        covered_any=covered_any,
    )
    OUT_ORACLE.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


def main(cmd: str) -> None:
    if cmd in ("naive", "all"):
        r = naive()
        for s, b in r["splits"].items():
            for a in ("naive_plain", "naive_null"):
                print(s, a, "registered", b[a]["registered_exact"], "reparsed", b[a]["reparsed_exact"],
                      "fabricated", b[a]["n_fabricated_after_reparse"])
    if cmd in ("paired", "all"):
        r = paired()
        for s, b in r["splits"].items():
            for k, v in b["comparisons"].items():
                print(s, k, {x: v["all"][x] for x in v["all"] if x != "n"}, "bodies", v["bodies"]["sign_p_two_sided"])
    if cmd in ("oracle", "all"):
        r = oracle()
        print(json.dumps(r["summary"]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
