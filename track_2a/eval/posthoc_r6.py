"""POST HOC (11 Oct 2026, round 6; not pre-registered): evaluation evidence asked for by the round-6 jury (J2, J5). No model
call; nothing here changes a registered decision.

  annotations  the raw A1/A2/A3 label files of P6 and DEV2 (.work/p6{,dev}/ann/<A>/<doc>.json, written by the annotator
               agents) -> data/p6/annotations/{p6,dev2}/<A>.jsonl, one JSON object per line, sorted by doc_id; quotes longer
               than 300 characters are cut (none were). `check` re-merges the committed raw files with the frozen merge rule
               (eval/p6/sample.py:merge, eval/p6/dev2.py:merge) and compares with the committed labels and agreement files.
  cluster      cluster-aware 95% intervals: documents (P2, P6) and answers (P5) are nested in parliaments, so parliaments are
               resampled with replacement (percentile bootstrap, B = 10,000, seed 20261011); for P5 also affairs. For P5-H1
               the registered tier rule is re-applied to the cluster lower bounds. P6 adds the model-free cascade (rules,
               and where the rules abstain the latest printed date on answer-typed documents) and cascade v2 vs rules on
               all 68 documents.
  provenance   values printed nowhere in the document ('fabricated' in eval/score.py) per arm and set (P1 held-out, P2, P6),
               with the free prompt that may return null as the comparator next to the plain prompt.
               -> both into results/eval/posthoc_r6_cluster.json
  p6oracle     agreement of the P6 gold (Claude agents only) with non-LLM sources: OPD written-answer events, OPD affair
               submission dates (order), dates in the publishers' document titles (session dates: a bound, not the answer
               date), decision numbers in titles, the OPD document type, and a string check of every gold quote against
               the extracted document text -> results/eval/posthoc_r6_p6_oracle.json

    PYTHONPATH=src:. python -m eval.posthoc_r6 [annotations|check|cluster|p6oracle|all]
"""

from __future__ import annotations

import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

import numpy as np

from eval.score import outcome
from gegenprobe.paths import DATA, RESULTS, WORK
from gegenprobe.stats import cohen_kappa, wilson

BUILD = "publicai_swiss-ai_apertus-v1.5-8b"
LABEL = "POST HOC (11 Oct 2026, round 6; not pre-registered): no registered decision depends on this file"
B_BOOT = 10_000
SEED = 20261011
QUOTE_MAX = 300
OUT_CLUSTER = RESULTS / "eval" / "posthoc_r6_cluster.json"
OUT_ORACLE = RESULTS / "eval" / "posthoc_r6_p6_oracle.json"
ANN_OUT = DATA / "p6" / "annotations"
RAW = {"p6": WORK / "p6" / "ann", "dev2": WORK / "p6dev" / "ann"}
MERGED = {"p6": (DATA / "p6" / "p6_labels.jsonl", DATA / "p6" / "p6_agreement.json", DATA / "p6" / "p6_docs.jsonl", "p6"),
          "dev2": (DATA / "p6" / "dev2_labels.jsonl", DATA / "p6" / "dev2_agreement.json", DATA / "p6" / "dev2_docs.jsonl",
                   "p6dev2")}


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


# ------------------------------------------------------------------------------------------------------------ annotations
def export_annotations() -> dict:
    out = {}
    for s, src in RAW.items():
        out[s] = {}
        for a in ("A1", "A2", "A3"):
            files = sorted((src / a).glob("*.json"), key=lambda p: int(p.stem)) if (src / a).exists() else []
            if not files:
                out[s][a] = dict(n=0, note="no tie-break was needed" if a == "A3" else "missing")
                continue
            rows, cut = [], []
            for f in files:
                r = json.loads(f.read_text())
                for k, v in r.items():
                    if k.endswith("quote") and isinstance(v, str) and len(v) > QUOTE_MAX:
                        r[k] = v[:QUOTE_MAX]
                        cut.append(dict(doc_id=r["doc_id"], field=k, chars=len(v)))
                rows.append(r)
            p = ANN_OUT / s / f"{a}.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
            longest = max((len(v), k) for r in rows for k, v in r.items() if isinstance(v, str))
            out[s][a] = dict(n=len(rows), quotes_cut=cut, longest_string=dict(chars=longest[0], field=longest[1]))
    return out


def _merge(a1: dict, a2: dict, a3: dict, docs: dict, source: str) -> tuple[list[dict], dict]:
    """eval/p6/sample.py:merge and eval/p6/dev2.py:merge (frozen in LOCK7), without writing anything."""
    ids = sorted(set(a1) & set(a2))
    agree = {}
    for f in ("answer_present", "answer_date"):
        x, y = [str(a1[i][f]) for i in ids], [str(a2[i][f]) for i in ids]
        agree[f] = dict(raw=sum(p == q for p, q in zip(x, y)), n=len(ids), kappa=cohen_kappa(x, y))
    rows = []
    for i in ids:
        if a1[i]["answer_date"] == a2[i]["answer_date"]:
            lab, src = a1[i], "A1=A2"
        else:
            lab, src = a3[i], "A3"
        len_ = sorted(set((a1[i].get("answer_date_lenient") or []) + (a2[i].get("answer_date_lenient") or []))
                      | ({a1[i]["answer_date"], a2[i]["answer_date"]} - {None, lab["answer_date"]}))
        rows.append(dict(doc_id=i, source=source, cell=docs[i]["cell"], dtype=docs[i]["dtype"], body=docs[i]["body"],
                         labeller=f"claude-agents:{src}", answer_present=lab["answer_present"], answer_date=lab["answer_date"],
                         role=lab.get("role"), answer_date_page=lab.get("answer_date_page"),
                         answer_date_quote=(lab.get("answer_date_quote") or "")[:200],
                         answer_date_lenient=[x for x in len_ if x], decision_number=lab.get("decision_number")))
    return rows, dict(agreement=agree, decided_by_A3=sum(r["labeller"].endswith("A3") for r in rows))


def check_annotations() -> dict:
    """Committed raw annotator files -> merged labels and agreement, compared with the committed files."""
    out = {}
    for s, (labels_p, agree_p, docs_p, source) in MERGED.items():
        raw = {}
        for a in ("A1", "A2", "A3"):
            p = ANN_OUT / s / f"{a}.jsonl"
            raw[a] = {int(r["doc_id"]): r for r in _jsonl(p)} if p.exists() else {}
        docs = {d["doc_id"]: d for d in _jsonl(docs_p)}
        rows, agr = _merge(raw["A1"], raw["A2"], raw["A3"], docs, source)
        committed = _jsonl(labels_p)
        ca = json.loads(agree_p.read_text())
        same_agreement = agr["decided_by_A3"] == ca["decided_by_A3"] and all(
            agr["agreement"][f]["raw"] == ca["agreement"][f]["raw"] and agr["agreement"][f]["n"] == ca["agreement"][f]["n"]
            and abs(agr["agreement"][f]["kappa"] - ca["agreement"][f]["kappa"]) < 1e-12 for f in ca["agreement"])
        out[s] = dict(n=len(rows), labels_equal=rows == committed,
                      agreement_equal=same_agreement,  # kappa within 1e-12: its sum runs over a set (hash order)
                      n_raw={a: len(v) for a, v in raw.items()}, decided_by_A3=agr["decided_by_A3"])
    return out


# ------------------------------------------------------------------------------------------------------------ bootstrap
def _boot(table: np.ndarray, stat, b: int = B_BOOT, seed: int = SEED) -> dict:
    """table: clusters x columns of per-cluster sums; stat: column sums (array) -> value or None.
    Percentile 95% interval over resamples of clusters; resamples where stat is undefined are dropped and counted."""
    rng = np.random.default_rng(seed)
    k = table.shape[0]
    idx = rng.integers(0, k, size=(b, k))
    sums = table[idx].sum(axis=1)
    vals = [stat(s) for s in sums]
    ok = np.array([v for v in vals if v is not None], dtype=float)
    lo, hi = (float(np.percentile(ok, 2.5)), float(np.percentile(ok, 97.5))) if len(ok) else (None, None)
    return dict(ci95=[lo, hi], n_clusters=k, b=b, undefined_resamples=b - len(ok))


def _ratio(i: int, j: int):
    return lambda s: (float(s[i] / s[j]) if s[j] else None)


def _diff(i: int, j: int, n: int):
    return lambda s: (float((s[i] - s[j]) / s[n]) if s[n] else None)


def _mcnemar(b: int, c: int) -> float:
    import math
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def _ok(pred, r) -> bool:
    return outcome(pred, r["gold"], set(r["doc_dates"]), r.get("lenient"), True) in ("correct", "correct_null")


def doc_level_block(rows: list[dict], arms: list[str], pairs: list[tuple], cluster_key: str = "body",
                    subsets: dict | None = None) -> dict:
    """Exact accuracy per arm and paired differences, with document-level (Wilson / exact McNemar) and parliament-cluster
    bootstrap intervals."""
    clusters = sorted({r[cluster_key] for r in rows})
    out = dict(n=len(rows), n_parliaments=len(clusters), arms={}, paired={})
    cols = ["n"] + arms
    tab = np.zeros((len(clusters), len(cols)))
    for r in rows:
        c = clusters.index(r[cluster_key])
        tab[c, 0] += 1
        for j, a in enumerate(arms, start=1):
            tab[c, j] += _ok(r[a], r)
    for j, a in enumerate(arms, start=1):
        k = int(tab[:, j].sum())
        out["arms"][a] = dict(exact=[k, len(rows)], rate=k / len(rows), doc_level_wilson95=list(wilson(k, len(rows))),
                              cluster_bootstrap95=_boot(tab, _ratio(j, 0))["ci95"])
    for a, b, *sel in pairs:
        rs = [r for r in rows if not sel or sel[0](r)]
        name = f"{a} vs {b}" + (f" ({sel[1]})" if sel else "")
        x = sum(_ok(r[a], r) and not _ok(r[b], r) for r in rs)
        y = sum(_ok(r[b], r) and not _ok(r[a], r) for r in rs)
        cl = sorted({r[cluster_key] for r in rs})
        t = np.zeros((len(cl), 3))
        for r in rs:
            i = cl.index(r[cluster_key])
            t[i, 0] += _ok(r[a], r)
            t[i, 1] += _ok(r[b], r)
            t[i, 2] += 1
        bt = _boot(t, _diff(0, 1, 2))
        per = {c: int(t[i, 0] - t[i, 1]) for i, c in enumerate(cl)}
        out["paired"][name] = dict(
            n=len(rs), a_only=x, b_only=y, mcnemar_exact_p=_mcnemar(x, y),
            accuracy_difference=(x - y) / len(rs), cluster_bootstrap95=bt["ci95"], n_parliaments=len(cl),
            cluster_interval_excludes_0=bt["ci95"][0] is not None and (bt["ci95"][0] > 0 or bt["ci95"][1] < 0),
            parliaments_a_better=sum(v > 0 for v in per.values()), parliaments_b_better=sum(v < 0 for v in per.values()),
            parliaments_tied=sum(v == 0 for v in per.values()),
            parliament_sign_test_p=_mcnemar(sum(v > 0 for v in per.values()), sum(v < 0 for v in per.values())))
    return out


# ------------------------------------------------------------------------------------------------------------ P5
def p5_cluster() -> dict:
    from eval.gold6.score6 import gold_view, iou
    res = json.loads((RESULTS / "eval6" / f"p5__{BUILD}.json").read_text())
    gold = {r["affair_id"]: gold_view(r) for r in _jsonl(DATA / "gold6" / "p5_labels.jsonl")}
    from eval.gold6.posthoc6 import LANG
    meta = {a["affair_id"]: a for a in _jsonl(DATA / "gold6" / "p5_affairs.jsonl")}
    per = []
    for p in res["per_affair"]:
        if p["affair_id"] not in gold:
            continue
        g, v = gold[p["affair_id"]], p["R"]["view"]
        pa = {x["n"]: x["span"] for x in v.get("answers") or []}
        gnn = {x["n"]: x["span"] for x in g["answers"] if x["span"] is not None}
        pnn = {n: s for n, s in pa.items() if s is not None}
        c = sum(iou(s, pnn.get(n)) >= 0.5 for n, s in gnn.items())
        m = meta[p["affair_id"]]
        per.append(dict(affair=p["affair_id"], body=m["body"], lang=m["lang"] or LANG.get(m["body"], "?"),
                        c=c, p=len(pnn), g=len(gnn)))

    def block(key: str) -> dict:
        cl = sorted({r[key] for r in per})
        t = np.zeros((len(cl), 3))
        for r in per:
            i = cl.index(r[key])
            t[i] += (r["c"], r["p"], r["g"])
        return dict(n_clusters=len(cl), precision=_boot(t, _ratio(0, 1))["ci95"], recall=_boot(t, _ratio(0, 2))["ci95"])

    c, p, g = (sum(r[k] for r in per) for k in ("c", "p", "g"))
    by_body, by_aff = block("body"), block("affair")

    def tier(plo, rlo):
        return ("per-question pairing extractable unattended" if plo >= 0.85 and rlo >= 0.60 else
                "partial" if plo >= 0.70 and rlo >= 0.40 else "not yet")

    per_group = {}
    for key in ("lang", "body"):
        per_group[key] = {}
        for v in sorted({r[key] for r in per}):
            rs = [r for r in per if r[key] == v]
            cc, pp, gg = (sum(r[k] for r in rs) for k in ("c", "p", "g"))
            per_group[key][v] = dict(affairs=len(rs), recall=[cc, gg], precision=[cc, pp])
    return dict(
        what="P5-H1 (rules-only Q/A pairing, arm R): correct pairs / predicted (precision) and / gold non-null (recall)",
        n_affairs=len(per), n_parliaments=len({r["body"] for r in per}),
        precision=dict(k=c, n=p, rate=c / p, doc_level_wilson95=list(wilson(c, p)),
                       parliament_cluster95=by_body["precision"], affair_cluster95=by_aff["precision"]),
        recall=dict(k=c, n=g, rate=c / g, doc_level_wilson95=list(wilson(c, g)),
                    parliament_cluster95=by_body["recall"], affair_cluster95=by_aff["recall"]),
        registered_tier=dict(
            rule="PREREG6 H1: partial if precision lower bound >= 0.70 and recall lower bound >= 0.40 (unattended: 0.85/0.60)",
            with_wilson=tier(wilson(c, p)[0], wilson(c, g)[0]),
            with_parliament_cluster=tier(by_body["precision"][0], by_body["recall"][0]),
            with_affair_cluster=tier(by_aff["precision"][0], by_aff["recall"][0])),
        per_language=per_group["lang"], per_parliament=per_group["body"],
    )


# ------------------------------------------------------------------------------------------------------------ P2 / P1
def _p12_rows(split: str) -> list[dict]:
    from eval.replay_all import _arm_rows
    res_p, lab_p, docs_p = {
        "P1": (RESULTS / "eval" / f"heldout__{BUILD}.json", DATA / "gold" / "heldout_labels.jsonl",
               DATA / "gold" / "heldout_docs.jsonl"),
        "P2": (RESULTS / "eval2" / f"p2__{BUILD}.json", DATA / "gold2" / "p2_labels.jsonl", DATA / "gold2" / "p2_docs.jsonl"),
    }[split]
    res = json.loads(res_p.read_text())
    labels = {x["doc_id"]: x for x in _jsonl(lab_p)}
    body = {d["doc_id"]: d["body"] for d in _jsonl(docs_p)}
    rows, _, bad = _arm_rows(res["per_doc"], labels)
    assert not bad, bad[:3]
    out = []
    for i, r in enumerate(res["per_doc"]):
        row = dict(doc_id=r["doc_id"], body=body[r["doc_id"]], gold=labels[r["doc_id"]]["answer_date"],
                   lenient=labels[r["doc_id"]].get("answer_date_lenient") or [], doc_dates=r.get("doc_dates") or [])
        for a, rs in rows.items():
            row[a] = rs[i]["pred"]
        out.append(row)
    return out


def p2_cluster() -> dict:
    rows = _p12_rows("P2")
    blk = doc_level_block(rows, ["rules", "pointer", "cascade", "naive_null", "naive_plain"],
                          [("pointer", "rules"), ("pointer", "naive_null"), ("cascade", "rules"),
                           ("cascade", "naive_null")])
    blk["arm_names"] = dict(pointer="Apertus closed-set pointer (registered P2 arm)", naive_null="free prompt, null allowed",
                            naive_plain="free prompt, plain", cascade="rules, then pointer")
    return blk


# ------------------------------------------------------------------------------------------------------------ P6
def _p6_rows() -> list[dict]:
    from eval.p6 import hypotheses7 as H
    from eval.p6 import sample as S
    res = json.loads((RESULTS / "p6" / f"p6__{BUILD}.json").read_text())
    labels = {r["doc_id"]: r for r in _jsonl(S.LABELS)}
    rows = H.flatten(res, labels)
    status = {d["doc_id"]: d["rules"]["status"] for d in res["per_doc"]}
    for r in rows:
        s = status[r["doc_id"]]
        # model-free cascade: the rules decide when they return a value or a typed null; where they abstain, the latest
        # printed date on documents OPD types as answers (null on interventions)
        r["model_free_cascade"] = r["rules"] if s in ("value", "null") else r["latest_on_answer_typed"]
        r["rules_status"] = s
    return rows


def p6_cluster() -> dict:
    rows = _p6_rows()
    ans = (lambda r: r["gold"] is not None, "answered documents only")
    blk = doc_level_block(
        rows, ["rules", "model_free_cascade", "v1", "v2", "cascade_v2", "free_null", "free_guided", "free_plain",
               "latest_on_answer_typed"],
        [("cascade_v2", "rules"), ("cascade_v2", "rules", *ans), ("v2", "rules"), ("free_null", "rules"),
         ("cascade_v2", "model_free_cascade"), ("free_null", "model_free_cascade"), ("v2", "free_null"),
         ("cascade_v2", "free_null"), ("v2", "v1")])
    blk["arm_names"] = dict(
        model_free_cascade="rules; where they abstain, the latest printed date on answer-typed documents (no model)",
        cascade_v2="rules; where they abstain, pointer v2", free_null="free prompt, null allowed (registered H1 comparator)",
        latest_on_answer_typed="latest printed date on answer-typed documents, null on interventions")
    blk["rules_status_counts"] = dict(collections.Counter(r["rules_status"] for r in rows))
    blk["note"] = ("8 parliaments: a cluster bootstrap with 8 clusters is coarse (few distinct resamples); read the interval "
                   "as 'how much the headline depends on which parliaments were drawn', not as an exact 95% coverage")
    return blk


# ------------------------------------------------------------------------------------------------------------ provenance
def provenance() -> dict:
    sets = {"P1 held-out": (_p12_rows("P1"), ["rules", "pointer", "cascade", "naive_null", "naive_plain"]),
            "P2": (_p12_rows("P2"), ["rules", "pointer", "cascade", "naive_null", "naive_plain"]),
            "P6": (_p6_rows(), ["rules", "model_free_cascade", "v1", "cascade_v1", "v2", "cascade_v2", "free_null",
                                "free_guided", "free_plain", "latest_printed_date", "latest_on_answer_typed"])}
    out = dict(
        definition=("printed nowhere = a value that is neither the gold date nor any date the frozen lattice finds in the "
                    "document ('fabricated' in eval/score.py); printed but wrong = 'misattributed'; dated answerless = a "
                    "value on a document whose gold is null. Parser: as registered (results files)."),
        sets={})
    for name, (rows, arms) in sets.items():
        out["sets"][name] = {}
        for a in arms:
            c = collections.Counter(outcome(r[a], r["gold"], set(r["doc_dates"]), r.get("lenient"), True) for r in rows)
            nul = [r for r in rows if r["gold"] is None]
            out["sets"][name][a] = dict(n=len(rows), values=sum(r[a] is not None for r in rows),
                                        printed_nowhere=c["fabricated"], printed_but_wrong=c["misattributed"],
                                        dated_answerless=[sum(r[a] is not None for r in nul), len(nul)])
    names = {"P1 held-out": ("naive_null", "naive_plain"), "P2": ("naive_null", "naive_plain"), "P6": ("free_null", "free_plain")}
    out["summary"] = dict(
        free_prompt_null_allowed_printed_nowhere={s: out["sets"][s][a]["printed_nowhere"] for s, (a, _) in names.items()},
        free_prompt_plain_printed_nowhere={s: out["sets"][s][b]["printed_nowhere"] for s, (_, b) in names.items()},
        closed_set_arms_printed_nowhere={s: {a: v["printed_nowhere"] for a, v in out["sets"][s].items()
                                             if a in ("pointer", "cascade", "v1", "cascade_v1", "v2", "cascade_v2")}
                                         for s in out["sets"]},
    )
    rp = RESULTS / "eval" / "posthoc_r3_naive_reparsed.json"
    if rp.exists():  # P1/P2 free prompts under the corrected date parser (round 3)
        r3 = json.loads(rp.read_text())["splits"]
        out["corrected_parser_p1_p2"] = {s: {a: r3[s][a]["reparsed"]["fabricated"] for a in ("naive_null", "naive_plain")
                                             if a in r3[s]} for s in ("P1", "P2") if s in r3}
    return out


def cluster() -> dict:
    out = dict(label=LABEL, method=dict(
        bootstrap="percentile, resampling parliaments (bodies) with replacement; P5 also affairs",
        b=B_BOOT, seed=SEED, scorer="eval/score.py outcome (strict) for P1/P2/P6; eval/gold6/score6.py IoU >= 0.5 for P5"),
        p5_h1=p5_cluster(), p2=p2_cluster(), p6=p6_cluster(), provenance=provenance())
    OUT_CLUSTER.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


# ------------------------------------------------------------------------------------------------------------ P6 oracle
TITLE_DATE_P6 = [  # session/meeting dates in P6 publishers' file names (Lyss 306, Interlaken 581, Conthey 6023, Zug city)
    ("yyyymmdd; (Lyss: session)", re.compile(r"^(\d{4})(\d{2})(\d{2});"), "ymd"),
    ("ggr yyyymmdd (Interlaken: session)", re.compile(r"ggr ?(\d{4})(\d{2})(\d{2})"), "ymd"),
    ("yyyy-xx-xx (Conthey: council)", re.compile(r"(?:^|-)(\d{4})-(\d{2})-(\d{2})-"), "ambiguous"),
    ("vom d. Monat yyyy", re.compile(r"vom (\d{1,2})\. (Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|"
                                     r"November|Dezember) (\d{4})"), "dmy_de"),
]
MONTHS_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
             "Dezember"]


def _mk(y, m, d) -> str | None:
    try:
        return dt.date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def _title_dates(name: str) -> tuple[list[str], str | None]:
    from eval.posthoc_r3 import _title_date
    t = _title_date(name or "")
    if t:
        return [t], "TI/BE decision date"
    for label, rx, kind in TITLE_DATE_P6:
        m = rx.search(name or "")
        if not m:
            continue
        if kind == "ymd":
            v = [_mk(*m.groups())]
        elif kind == "dmy_de":
            v = [_mk(m.group(3), MONTHS_DE.index(m.group(2)) + 1, m.group(1))]
        else:  # Conthey writes both yyyy-mm-dd and yyyy-dd-mm
            v = [_mk(m.group(1), m.group(2), m.group(3)), _mk(m.group(1), m.group(3), m.group(2))]
        v = sorted({x for x in v if x})
        if v:
            return v, label
    return [], None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def p6oracle() -> dict:
    from eval.posthoc_r3 import TITLE_NUMBER, _date_check, _opd_events
    from eval.p6 import run_p6
    from eval.p6 import sample as S
    from gegenprobe.census import tables
    from gegenprobe.convert import lattice

    docs = {d["doc_id"]: d for d in _jsonl(S.DOCS)}
    labs = {x["doc_id"]: x for x in _jsonl(S.LABELS)}
    # affair of each document: the sample's affair_id, else OPD's document table
    aff = {i: d.get("affair_id") for i, d in docs.items()}
    for r in tables.rows("docs"):
        i = tables.i(r["id"])
        if i in aff and not aff[i] and r["affair"]:
            aff[i] = tables.i(r["affair"])
    begin, number = {}, {}
    affs = {a for a in aff.values() if a}
    for r in tables.rows("affairs"):
        a = tables.i(r["id"])
        if a in affs:
            number[a] = r["number"]
            if r["begin"]:
                begin[a] = r["begin"][:10]
    written, submitted = _opd_events(affs)
    events = collections.defaultdict(list)
    for e in tables.rows("events"):
        a = tables.i(e["affair"])
        if a in affs and e["date"]:
            events[a].append((e["date"][:10], tables.i(e["hid"]), e["title"][:40]))
    val = [x for x in labs.values() if x["answer_date"]]
    out = dict(label=LABEL, scope=(
        "Every P6 label was set by Claude agents (A1 Opus, A2 Sonnet, A3 Opus on 1 disagreement); no human labelled. These "
        "non-LLM sources can confirm or contradict a label; none was used to set one."),
        n_documents=len(labs), gold_dated=len(val), documents_with_opd_affair=sum(1 for a in aff.values() if a))
    out["answer_date_vs_opd_written_answer_event"] = _date_check(
        [(x["doc_id"], x["answer_date"], written.get(aff[x["doc_id"]]) or [], x.get("answer_date_quote")) for x in val])
    # order: an answer cannot predate the affair's submission (OPD 'begin' or the harmonised submission event)
    order, bad = collections.Counter(), []
    for x in val:
        a = aff[x["doc_id"]]
        sd = sorted(set(submitted.get(a) or []) | ({begin[a]} if a in begin else set()))
        if not sd:
            order["no_submission_date"] += 1
            continue
        order["checked"] += 1
        if x["answer_date"] >= min(sd):
            order["holds"] += 1
        else:
            tn = re.match(r"\s*(\d{3,5})\b", docs[x["doc_id"]]["name"] or "")
            bad.append(dict(doc_id=x["doc_id"], body=docs[x["doc_id"]]["body"], gold=x["answer_date"], opd_submitted=sd,
                            opd_events=sorted(events.get(a, [])), opd_affair_number=number.get(a),
                            opd_affair_number_is_title_number=bool(tn and (number.get(a) or "").startswith(tn.group(1)))))
    out["answer_not_before_opd_submission"] = dict(
        checked=order["checked"], holds=order["holds"], no_submission_date=order["no_submission_date"], violations=bad,
        violations_submission_equals_agenda_event=sum(
            1 for v in bad if any(e[0] == v["opd_submitted"][0] and e[1] == 24 for e in v["opd_events"])),
        violations_opd_affair_is_the_executive_vorlage=sum(1 for v in bad if v["opd_affair_number_is_title_number"]),
        reading=("an OPD 'submission' on the same day as the agenda event (hid 24 'Traktandiert'), or the submission of an "
                 "OPD affair whose number is the document's own Vorlage number (the executive's answer filed in "
                 "parliament), dates the answer's arrival in parliament, not the question; such rows bound nothing"))
    # publisher titles: session / council dates bound the answer from above (the answer is dated on or before the session)
    tchk, c = [], collections.Counter()
    for x in val:
        td, kind = _title_dates(docs[x["doc_id"]]["name"])
        if not td:
            c["no_title_date"] += 1
            continue
        c["checked"] += 1
        g = x["answer_date"]
        exact = g in td
        days = min(((dt.date.fromisoformat(t) - dt.date.fromisoformat(g)).days for t in td), key=abs)
        within = any(0 <= (dt.date.fromisoformat(t) - dt.date.fromisoformat(g)).days <= 120 for t in td)
        c["exact"] += exact
        c["gold_on_or_before_title_date_within_120_days"] += within
        tchk.append(dict(doc_id=x["doc_id"], body=docs[x["doc_id"]]["body"], title_kind=kind, title_dates=td, gold=g,
                         title_minus_gold_days=days, exact=exact, consistent=within))
    out["answer_date_vs_publisher_title_date"] = dict(
        meaning=("Lyss, Interlaken and Conthey prefix file names with the date of the parliament or council session that "
                 "handled the answer; the answer letter is dated on or before it. 'consistent' = gold date on or up to 120 "
                 "days before a title date; Conthey writes yyyy-mm-dd and yyyy-dd-mm, both readings are kept"),
        checked=c["checked"], exact=c["exact"], consistent=c["gold_on_or_before_title_date_within_120_days"],
        no_title_date=c["no_title_date"], rows=tchk)
    nul_title = [dict(doc_id=i, dtype=docs[i]["dtype"], title_dates=_title_dates(docs[i]["name"])[0],
                      answer_present=x["answer_present"])
                 for i, x in labs.items() if not x["answer_date"] and _title_dates(docs[i]["name"])[0]]
    out["title_date_on_gold_null_documents"] = nul_title
    nums = []
    for x in labs.values():
        name = docs[x["doc_id"]]["name"] or ""
        m = TITLE_NUMBER.match(name)
        g = re.sub(r"\D", "", str(x.get("decision_number") or ""))
        if m or (g and len(g) >= 2):
            nums.append(dict(doc_id=x["doc_id"], gold=x.get("decision_number"), title_rrb_number=m.group(1) if m else None,
                             gold_digits_in_title=bool(g) and g in re.sub(r"\D", " ", name).split()))
    out["decision_number_vs_publisher_title"] = dict(
        gold_decision_numbers=sum(1 for x in labs.values() if x.get("decision_number")),
        titles_with_rrb_number=sum(1 for n in nums if n["title_rrb_number"]),
        gold_number_found_in_title=sum(n["gold_digits_in_title"] for n in nums), rows=nums)
    xt = collections.Counter(f"{docs[i]['dtype']}|{x['answer_present']}" for i, x in labs.items())
    out["opd_document_type_vs_gold_presence"] = dict(
        counts=dict(sorted(xt.items())),
        agree=xt["answer|yes"] + xt["intervention|no"],
        n=len(labs),
        meaning="OPD's own document type (from the publisher's category) vs the agents' answer_present")
    # string check of every gold quote against the extracted text (deterministic; the agents read the same text)
    text = {d["doc_id"]: d["pages"] for d in run_p6.load()}
    q = collections.Counter()
    qrows = []
    for x in val:
        pages = text[x["doc_id"]]
        quote = _norm(x.get("answer_date_quote"))
        pg = x.get("answer_date_page")
        on_page = bool(quote) and pg is not None and 1 <= pg <= len(pages) and quote in _norm(pages[pg - 1])
        in_doc = bool(quote) and any(quote in _norm(p) for p in pages)
        parsed = sorted({c["value"] for c in lattice.dates([x.get("answer_date_quote") or ""])})
        printed = x["answer_date"] in {c["value"] for c in lattice.dates(pages)}
        q["checked"] += 1
        q["quote_on_stated_page"] += on_page
        q["quote_in_document"] += in_doc
        q["quote_parses_to_gold_date"] += x["answer_date"] in parsed
        q["gold_date_printed_in_document"] += printed
        if not (on_page and x["answer_date"] in parsed and printed):
            qrows.append(dict(doc_id=x["doc_id"], gold=x["answer_date"], page=pg, quote_on_page=on_page, quote_in_doc=in_doc,
                              quote_dates=parsed, gold_printed=printed))
    out["gold_quote_string_check"] = dict(q, exceptions=qrows, meaning=(
        "the gold quote (whitespace-normalised) occurs on the stated page of the extracted text, the frozen date lattice "
        "reads the gold date from the quote, and the gold date is among the dates printed in the document"))
    out["summary"] = dict(
        opd_written_answer_event=[out["answer_date_vs_opd_written_answer_event"]["agree"],
                                  out["answer_date_vs_opd_written_answer_event"]["checked"]],
        submission_order=[order["holds"], order["checked"]],
        title_date_exact=[c["exact"], c["checked"]],
        title_date_consistent=[c["gold_on_or_before_title_date_within_120_days"], c["checked"]],
        opd_type_agrees=[out["opd_document_type_vs_gold_presence"]["agree"], len(labs)],
        quote_on_page_and_parses=[q["checked"] - len(qrows), q["checked"]],
        gold_dated_with_any_non_llm_date_source=[sum(1 for x in val if (written.get(aff[x["doc_id"]]) or
                                                                         _title_dates(docs[x["doc_id"]]["name"])[0])),
                                                 len(val)],
    )
    OUT_ORACLE.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


def main(cmd: str) -> None:
    if cmd in ("annotations", "all"):
        print(json.dumps(export_annotations(), indent=1))
    if cmd in ("annotations", "check", "all"):
        print(json.dumps(check_annotations(), indent=1))
    if cmd in ("cluster", "all"):
        o = cluster()
        print(json.dumps(dict(p5=o["p5_h1"]["registered_tier"], prov=o["provenance"]["summary"]), indent=1))
    if cmd in ("p6oracle", "all"):
        print(json.dumps(p6oracle()["summary"], indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
