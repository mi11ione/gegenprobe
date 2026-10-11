"""POST HOC (10 Oct 2026): an independent, non-Anthropic annotator for the P1 held-out and P2 gold, and what the
registered headlines become under it. Not pre-registered; proposed in review ("the gold is single-vendor
LLM output").

  annotate p1|p2   Qwen-SEA-LION-v4-32B-IT (AI Singapore; Qwen family, not Anthropic, not Apertus) labels every document
                   blind: it sees only the annotation guide (eval/gold2/GUIDE.md, the guide A1-A3 were given, cut to the
                   answer-presence and answer-date definitions) and the same page-delimited packet text the Claude annotators
                   read (.work/gold{,2}/packets, built by the frozen eval/gold/annotate.py packets; never committed). Calls go
                   through the budget gateway only; the served model name is checked on every call. Raw labels (no text) ->
                   data/gold_audit/qwen_p1.jsonl, qwen_p2.jsonl
  analyse          agreement with the committed gold (κ, per cell / body, every disagreement), sensitivity of the registered
                   headlines, the null-safety recompute proposed in review -> results/eval/posthoc_r5_independent_gold.json
  p2table          P2 table with Wilson CIs per arm + latest-printed-date baselines -> results/eval2/posthoc_r5_p2_table.json

    PYTHONPATH=src:. python -m eval.posthoc_r5 annotate p1      (model calls; replays from the gateway cache are free)
    PYTHONPATH=src:. python -m eval.posthoc_r5 analyse          (no model call)
    PYTHONPATH=src:. python -m eval.posthoc_r5 p2table          (no model call)
"""

from __future__ import annotations

import collections
import concurrent.futures as cf
import hashlib
import json
import re
import sys
import time

from eval.gold2.hypotheses2 import block as p2_block
from eval.score import outcome
from gegenprobe import devpaths
from gegenprobe.convert import lattice
from gegenprobe.paths import DATA, RESULTS, WORK
from gegenprobe.stats import cohen_kappa, wilson

MODEL = "aisingapore/Qwen-SEA-LION-v4-32B-IT"
TAG = "2a-qwen-audit"
TAG_CAP = 1.5
MAX_TOKENS = 700
BUILD = "publicai_swiss-ai_apertus-v1.5-8b"  # the 70B weights served under the -8b name (technical_report §3)
LABEL = "POST HOC (10 Oct 2026; not pre-registered): independent non-Anthropic annotator (Qwen-SEA-LION-v4-32B-IT)"
SETS = {
    "p1": dict(docs=DATA / "gold" / "heldout_docs.jsonl", labels=DATA / "gold" / "heldout_labels.jsonl",
               packets=WORK / "gold" / "packets", res=RESULTS / "eval" / f"heldout__{BUILD}.json"),
    "p2": dict(docs=DATA / "gold2" / "p2_docs.jsonl", labels=DATA / "gold2" / "p2_labels.jsonl",
               packets=WORK / "gold2" / "packets", res=RESULTS / "eval2" / f"p2__{BUILD}.json"),
}
OUT = DATA / "gold_audit"
MAX_CHARS = 60_000  # ~20k tokens; the longest packet is ~17k chars, so nothing is truncated (recorded per document)

# eval/gold2/GUIDE.md (identical to the guide the P1 annotators got, .work/gold/GUIDE.md), cut to the two fields audited;
# definitions verbatim, output format changed to one JSON object in the reply (no files, no self-check command).
PROMPT = """# Annotation guide: Swiss parliamentary documents (held-out gold set)

You label what a document itself PRINTS. Never use outside knowledge, metadata or memory. The document below is a
page-delimited text (`=== PAGE n ===` markers) extracted from a PDF of a Swiss parliament (federal, cantonal or municipal) in
German, French or Italian; some are OCR of scans (expect OCR noise).

Reply with exactly one JSON object and nothing else:

{"answer_present": "yes" | "no" | "oral" | "unclear",
 "answer_date": "DD.MM.YYYY" | null,
 "role": "decision" | "dispatch" | null,
 "answer_date_page": 1 | null,
 "answer_date_quote": "verbatim text from that page containing the date" | null}

## Definitions
- **answer_present**: `yes` if this document contains the executive's (government's: Bundesrat, Regierungsrat,
  Conseil d'État, Conseil-exécutif, Consiglio di Stato, Stadtrat, Gemeinderat, Municipalité, Municipio, Conseil communal…)
  answer to, or decision on, the parliamentary affair. A text that only asks (motion, postulate, interpellation, question
  as lodged by members) is `no`, even if it has an empty "RRB-Nr.: … vom" template field. A parliamentary
  committee report or minutes page that does not contain the executive's answer is `no`. `oral` if the document says the
  answer was given orally. `unclear` only if you truly cannot tell.
- **answer_date**: the date of the executive's answer AS PRINTED in this document, written as DD.MM.YYYY.
  - Prefer the **decision** date: the date the executive decided/adopted it, e.g. "RRB-Nr.: 879/2024 vom 28. August 2024",
    "Auszug aus dem Protokoll des Regierungsrates … Sitzung vom 3. Juli 2024", "Regierungsratsbeschluss vom …",
    "N° ACE … du …", "Ainsi adopté en séance du …", "Arrêté du Conseil-exécutif … du …", "RG n. … del …", "ris. mun. … del …".
    Then `role` = "decision".
  - If no decision date is printed, use the **dispatch** date of the answer: the place-date line or signature date of the
    answer letter (e.g. "Basel, 3. März 2025", "Lausanne, le 12 mai 2023", "Bellinzona, 4 aprile 2022"). Then `role` = "dispatch".
  - NEVER a footer/print/version/filing date ("Letzte Bearbeitung", "Version", "Dok.-Nr.", "Druck", page footers), never
    the date the members lodged the affair ("Eingereicht am", "déposé le", "presentata il"), never dates of laws, other
    affairs, sessions or events mentioned in the text.
  - If answer_present is not `yes`, answer_date is null.
  - `answer_date_quote` must be copied VERBATIM from the page given in `answer_date_page` (a short line or phrase,
    max 200 characters, containing the date). It is checked by code; whitespace differences are tolerated, nothing else.

## Procedure
1. Read the whole document text before answering.
2. Decide answer_present first, then the date.

## Document
"""

DMY = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$")


def norm(s) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def docs(s: str) -> list[dict]:
    return [json.loads(x) for x in open(SETS[s]["docs"])]


def labels(s: str) -> dict[int, dict]:
    return {r["doc_id"]: r for r in map(json.loads, open(SETS[s]["labels"]))}


def pages(s: str, doc_id: int) -> list[str]:
    txt = (SETS[s]["packets"] / f"{doc_id}.txt").read_text(encoding="utf-8")
    return re.split(r"(?:^|\n)=== PAGE \d+ ===\n", txt)[1:] if txt.startswith("=== PAGE") else [txt]


def to_iso(v) -> str | None:
    if v is None:
        return None
    m = DMY.match(str(v))
    if m:
        d, mo, y = map(int, m.groups())
        if 1 <= d <= 31 and 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}-{d:02d}"
        return "invalid"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", str(v)):  # tolerated: ISO instead of DD.MM.YYYY
        return str(v)
    return "invalid"


def parse_reply(text: str) -> dict | None:
    t = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip())
    m = re.search(r"\{.*\}", t, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def verify(a: dict, pgs: list[str]) -> dict:
    """Quote check as in eval/gold/annotate.py `check` (whitespace-normalised substring), on the stated page and anywhere in
    the document. A date is `verified` when its quote occurs verbatim in the document. `date_in_quote` (reported, not
    required) says whether the lattice parses the stated date from the quote: it fails on OCR-damaged or spelled-out dates
    ("6 avrfl 2023", "treize janvier deux mille vingt-six") that are nonetheless printed."""
    iso = a.get("date_iso")
    q = norm(a.get("quote"))
    pg = a.get("page")
    on_page = bool(q) and isinstance(pg, int) and 1 <= pg <= len(pgs) and q in norm(pgs[pg - 1])
    anywhere = bool(q) and any(q in norm(p) for p in pgs)
    in_quote = bool(q) and iso is not None and iso in {c["value"] for c in lattice.dates([a.get("quote") or ""])}
    return dict(quote_on_page=on_page, quote_in_doc=anywhere, date_in_quote=in_quote,
                verified=(iso is None) or anywhere)


def annotate_one(s: str, d: dict) -> dict:
    gw = devpaths.import_gw("posthoc_r5 Qwen annotation")  # budget gateway, GP_GATEWAY_DIR; key handling stays inside it

    pgs = pages(s, d["doc_id"])
    body = "".join(f"\n=== PAGE {i} ===\n{p}" for i, p in enumerate(pgs, 1)).lstrip("\n")
    truncated = len(body) > MAX_CHARS
    msg = [{"role": "user", "content": PROMPT + body[:MAX_CHARS]}]
    for attempt in range(6):  # the shared host answers 504 under load; the gateway caches every completed call
        try:
            choice, meta = gw.chat(msg, model=MODEL, max_tokens=MAX_TOKENS, temperature=0.0, tag=TAG, tag_cap_usd=TAG_CAP,
                                   full=True)
            break
        except OSError as e:  # HTTPError / URLError / timeouts; budget refusals (RuntimeError) propagate
            if attempt == 5:
                raise
            print(f"retry {d['doc_id']}: {e}", file=sys.stderr)
            time.sleep(20 * (attempt + 1))
    resp = meta.get("resp") or {}
    if resp.get("model") != MODEL:
        raise SystemExit(f"ABORT: served model {resp.get('model')!r} != requested {MODEL!r} (doc {d['doc_id']})")
    text = choice["message"]["content"]
    a = parse_reply(text) or {}
    ap = a.get("answer_present")
    rec = dict(
        doc_id=d["doc_id"],
        answer_present=ap if ap in ("yes", "no", "oral", "unclear") else "unparseable",
        date=a.get("answer_date"),
        date_iso=to_iso(a.get("answer_date")),
        role=a.get("role"),
        page=a.get("answer_date_page"),
        quote=(a.get("answer_date_quote") or None) and str(a.get("answer_date_quote"))[:200],
    )
    rec.update(verify(rec, pgs))
    print(f"{s} {d['doc_id']} {rec['answer_present']} {rec['date_iso']} cached={bool(meta.get('cached'))} "
          f"secs={meta.get('secs')}", file=sys.stderr, flush=True)
    rec.update(model=resp.get("model"), fingerprint=resp.get("system_fingerprint"), response_id=resp.get("id"),
               finish_reason=choice.get("finish_reason"), prompt_tokens=meta.get("prompt_tokens"),
               completion_tokens=meta.get("completion_tokens"), usd=round(meta.get("usd") or 0, 6),
               cached=bool(meta.get("cached")), truncated=truncated, chars_sent=min(len(body), MAX_CHARS),
               prompt_sha256=hashlib.sha256(PROMPT.encode()).hexdigest()[:16], parsed=bool(a))
    return rec


def annotate(s: str, workers: int = 8) -> list[dict]:
    ds = docs(s)
    with cf.ThreadPoolExecutor(workers) as ex:
        out = list(ex.map(lambda d: annotate_one(s, d), ds))
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"qwen_{s}.jsonl", "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    c = collections.Counter(r["answer_present"] for r in out)
    print(s, len(out), dict(c), "unverified dates:", sum(not r["verified"] for r in out),
          "usd(new):", round(sum(r["usd"] for r in out if not r["cached"]), 4))
    return out


# ------------------------------------------------------------------------------------------------------------- analysis
def qwen(s: str) -> dict[int, dict]:
    return {r["doc_id"]: r for r in map(json.loads, open(OUT / f"qwen_{s}.jsonl"))}


def q_date(q: dict, strict: bool = True) -> str | None:
    """Qwen's answer date as used for scoring: a date only if answer_present = yes and the date is valid; with strict (the
    primary reading, as the Claude protocol voids unverifiable labels) also only if its quote is verified."""
    if q["answer_present"] != "yes" or q["date_iso"] in (None, "invalid") or (strict and not q["verified"]):
        return None
    return q["date_iso"]


def present2(v: str) -> str:
    return "yes" if v == "yes" else "no"  # binary: an executive answer with a printed text is present, everything else not


def agreement(s: str, strict: bool = True) -> dict:
    G, Q = labels(s), qwen(s)
    meta = {d["doc_id"]: d for d in docs(s)}
    ids = sorted(G)
    assert set(ids) == set(Q), f"{s}: Qwen labels missing for {sorted(set(G) - set(Q))}"
    group = "cell" if s == "p1" else "body"

    def stats(sel):
        gp = [G[i]["answer_present"] for i in sel]
        qp = [Q[i]["answer_present"] for i in sel]
        gb, qb = [present2(x) for x in gp], [present2(x) for x in qp]
        gd = [str(G[i]["answer_date"]) for i in sel]
        qd = [str(q_date(Q[i], strict)) for i in sel]
        both = [i for i in sel if G[i]["answer_date"] and q_date(Q[i], strict)]
        exact_both = sum(G[i]["answer_date"] == q_date(Q[i], strict) for i in both)
        lenient_both = sum(q_date(Q[i], strict) in {G[i]["answer_date"], *(G[i].get("answer_date_lenient") or [])} for i in both)
        lenient_all = sum(
            (q_date(Q[i], strict) is None and G[i]["answer_date"] is None)
            or (q_date(Q[i], strict) is not None
                and q_date(Q[i], strict) in {G[i]["answer_date"], *(G[i].get("answer_date_lenient") or [])})
            for i in sel)
        return dict(
            n=len(sel),
            answer_present_4way=dict(raw=sum(a == b for a, b in zip(gp, qp)), kappa=_k(gp, qp)),
            answer_present_binary=dict(raw=sum(a == b for a, b in zip(gb, qb)), kappa=_k(gb, qb),
                                       gold_yes=gb.count("yes"), qwen_yes=qb.count("yes")),
            answer_date_exact=dict(raw=sum(a == b for a, b in zip(gd, qd)), kappa=_k(gd, qd)),
            answer_date_lenient=dict(raw=lenient_all),
            dates_where_both_give_one=dict(n=len(both), exact=exact_both, lenient=lenient_both),
        )

    per = collections.defaultdict(list)
    for i in ids:
        per[str(meta[i].get(group))].append(i)
    from eval.gold import annotate as A  # OPD written-answer event dates: a non-LLM reference, shown, never used to decide

    oracle = A.opd_answer_dates({meta[i]["affair_id"] for i in ids if meta[i].get("affair_id")})
    dis = []
    for i in ids:
        g, q = G[i], Q[i]
        gd, qd = g["answer_date"], q_date(q, strict)
        if present2(g["answer_present"]) != present2(q["answer_present"]) or gd != qd:
            kind = ("presence" if present2(g["answer_present"]) != present2(q["answer_present"]) else "date")
            dis.append(dict(doc_id=i, kind=kind, cell=meta[i]["cell"], body=meta[i].get("body"), dtype=meta[i]["dtype"],
                            gold_present=g["answer_present"], qwen_present=q["answer_present"], gold_date=gd,
                            gold_lenient=g.get("answer_date_lenient") or [], qwen_date=q["date_iso"], qwen_date_used=qd,
                            qwen_verified=q["verified"], qwen_in_gold_lenient=qd in (g.get("answer_date_lenient") or []),
                            gold_labeller=g["labeller"], gold_quote=g.get("answer_date_quote") or None,
                            qwen_quote=q.get("quote"),
                            opd_written_answer_dates=sorted(set(oracle.get(meta[i].get("affair_id")) or []))))
    return dict(
        overall=stats(ids),
        **{f"per_{group}": {k: stats(v) for k, v in sorted(per.items())}},
        qwen_unverified_dates=[i for i in ids if not Q[i]["verified"]],
        qwen_unparseable=[i for i in ids if Q[i]["answer_present"] == "unparseable"],
        disagreements=dis,
    )


def _k(a, b):
    k = cohen_kappa(a, b)
    return round(k, 4)


def _ok(pred, r) -> bool:
    return outcome(pred, r["gold"], set(r["doc_dates"]), r.get("lenient"), True) in ("correct", "correct_null")


def p1_headlines(rows: list[dict]) -> dict:
    """The registered P1 numbers recomputed on `rows` (same definitions as eval/hypotheses.py and eval/score.py, strict)."""
    nulls = [r for r in rows if r["gold"] is None]
    k = sum(r["cascade"].get("value") is not None for r in nulls)
    lo, hi = wilson(k, len(nulls)) if nulls else (None, None)
    per_cell = collections.Counter(r["cell"] for r in nulls if r["cascade"].get("value") is not None)
    out = dict(n=len(rows), H1_cascade_values_on_null=[k, len(nulls)], H1_upper=hi, H1_pass_pooled=hi is not None and hi <= 0.10,
               H1_max_per_cell=max(per_cell.values(), default=0), H1_pass_per_cell=max(per_cell.values(), default=0) <= 1)
    for arm in ("rules", "pointer", "cascade"):
        out[f"{arm}_exact"] = [sum(_ok(r[arm].get("value") if (arm != "rules" or r[arm]["status"] == "value") else None, r)
                                   for r in rows), len(rows)]
    return out


def p2_headlines(rows: list[dict]) -> dict:
    b = p2_block(rows, False)
    return dict(n=len(rows), n_gold_value=b["n_gold_value"],
                H2_pointer_only=b["H2_pointer_vs_rules"]["pointer_only"], H2_rules_only=b["H2_pointer_vs_rules"]["rules_only"],
                H2_p=b["H2_pointer_vs_rules"]["p"], pointer_exact=b["arms"]["pointer"]["exact"],
                rules_exact=b["arms"]["rules"]["exact"], cascade_exact=b["arms"]["cascade"]["exact"],
                H3_cascade_values_on_null=[b["H3_cascade_values_on_null"]["k"], b["H3_cascade_values_on_null"]["n"]])


def sensitivity(s: str, strict: bool = True) -> dict:
    res = json.loads(SETS[s]["res"].read_text())
    rows = res["per_doc"]
    Q = qwen(s)
    G = labels(s)
    f = p1_headlines if s == "p1" else p2_headlines
    agree = [r for r in rows if q_date(Q[r["doc_id"]], strict) == r["gold"]]
    replaced = []
    for r in rows:
        qd = q_date(Q[r["doc_id"]], strict)
        if qd == r["gold"]:
            replaced.append(r)
        else:  # Qwen's date (or null) becomes the gold; lenient alternatives kept only if Qwen also has a date
            replaced.append(dict(r, gold=qd, lenient=(r.get("lenient") or []) if qd else []))
    assert all(r["gold"] == G[r["doc_id"]]["answer_date"] for r in rows)
    return dict(committed_gold=f(rows), a_subset_where_qwen_agrees=f(agree),
                b_gold_replaced_by_qwen_where_they_differ=f(replaced))


def h1_j2() -> dict:
    """P1-H1 (cascade values on gold-null documents) with A2's (Sonnet's) labels instead of the merged gold, and with
    documents typed 'report' excluded (dtype from data/gold/heldout_docs.jsonl)."""
    rows = json.loads(SETS["p1"]["res"].read_text())["per_doc"]
    a2 = {r["doc_id"]: r for r in map(json.loads, open(DATA / "gold" / "annotations" / "A2.jsonl"))}
    a1 = {r["doc_id"]: r for r in map(json.loads, open(DATA / "gold" / "annotations" / "A1.jsonl"))}
    dtype = {d["doc_id"]: d["dtype"] for d in docs("p1")}
    Q = qwen("p1")

    def h1(rs, gold_of):
        nul = [r for r in rs if gold_of(r) is None]
        k = [r["doc_id"] for r in nul if r["cascade"].get("value") is not None]
        lo, hi = wilson(len(k), len(nul))
        return dict(k=len(k), n=len(nul), upper=hi, pass_pooled=hi <= 0.10, doc_ids=k)

    committed = lambda r: r["gold"]  # noqa: E731
    sonnet = lambda r: a2[r["doc_id"]]["answer_date"]  # noqa: E731
    opus = lambda r: a1[r["doc_id"]]["answer_date"]  # noqa: E731
    qw = lambda r: q_date(Q[r["doc_id"]])  # noqa: E731
    qw_all = lambda r: q_date(Q[r["doc_id"]], False)  # noqa: E731
    nore = [r for r in rows if dtype[r["doc_id"]] != "report"]
    k7 = h1(rows, committed)["doc_ids"]
    return dict(
        note="POST HOC. Same H1 definition as eval/hypotheses.py: cascade values on documents whose gold "
             "answer date is null, pooled, Wilson 95% upper bound <= 10% to pass.",
        committed_gold=h1(rows, committed),
        a2_sonnet_labels=h1(rows, sonnet),
        a1_opus_labels=h1(rows, opus),
        qwen_labels=h1(rows, qw),
        qwen_labels_all_dates=h1(rows, qw_all),
        committed_gold_without_reports=h1(nore, committed),
        a2_sonnet_without_reports=h1(nore, sonnet),
        qwen_without_reports=h1(nore, qw),
        n_reports=len(rows) - len(nore),
        the_7_committed=[dict(doc_id=i, dtype=dtype[i], gold_labeller=labels("p1")[i]["labeller"],
                              a1_date=a1[i]["answer_date"], a2_date=a2[i]["answer_date"],
                              cascade_value=next(r["cascade"]["value"] for r in rows if r["doc_id"] == i),
                              qwen_present=Q[i]["answer_present"], qwen_date=q_date(Q[i])) for i in k7],
    )


def analyse() -> dict:
    out = dict(label=LABEL, model=MODEL, gateway_tag=TAG,
               method="Blind single-pass annotation (temperature 0) with the A1-A3 guide cut to answer presence and date; "
                      "packet text identical to the Claude annotators'; a Qwen date counts only if answer_present = yes, "
                      "its quote occurs verbatim (whitespace-normalised) in the document; otherwise it is treated as null and "
                      "listed as unverified (primary reading). The *_all_qwen_dates blocks keep unverified dates too. "
                      "No adjudication.")
    for s in ("p1", "p2"):
        Q = qwen(s)
        out[s] = dict(
            n=len(Q),
            fingerprints=dict(collections.Counter(str(q["fingerprint"]) for q in Q.values())),
            served_models=sorted({q["model"] for q in Q.values()}),
            truncated=sum(q["truncated"] for q in Q.values()),
            usd=round(sum(q["usd"] for q in Q.values()), 4),
            agreement=agreement(s),
            sensitivity=sensitivity(s),
            agreement_all_qwen_dates=agreement(s, strict=False)["overall"],
            sensitivity_all_qwen_dates=sensitivity(s, strict=False),
        )
    out["usd_total"] = round(out["p1"]["usd"] + out["p2"]["usd"], 4)
    out["n_calls"] = out["p1"]["n"] + out["p2"]["n"]
    out["p1_h1_j2_recompute"] = h1_j2()
    p = RESULTS / "eval" / "posthoc_r5_independent_gold.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


# ----------------------------------------------------------------------------------------------------------- P2 table
def p2table() -> dict:
    from eval.gold2.hypotheses2 import decisions

    meta = {d["doc_id"]: d for d in docs("p2")}
    res70 = json.loads(SETS["p2"]["res"].read_text())
    b8 = "gguf_apertus-v1.5-8b-text-q4_k_m"
    res8 = json.loads((RESULTS / "eval2" / f"p2__{b8}.json").read_text())

    def latest(r):
        dd = r.get("doc_dates") or []
        return max(dd) if dd else None

    def preds(r):
        dec = decisions(r, False)
        lt = latest(r)
        dt = meta[r["doc_id"]]["dtype"]
        p = {a: dec[a] for a in ("rules", "pointer", "cascade", "naive_plain", "naive_null") if a in dec}
        p["latest_printed_date"] = lt
        p["latest_date_gated_by_doc_type"] = None if dt == "intervention" else lt
        p["latest_date_on_answer_docs_only"] = lt if dt == "answer" else None
        p["always_null"] = None
        return p

    def table(rows):
        P = {r["doc_id"]: preds(r) for r in rows}
        arms = list(next(iter(P.values())))
        val = [r for r in rows if r["gold"] is not None]
        nul = [r for r in rows if r["gold"] is None]
        out = {}
        for a in arms:
            oc = collections.Counter(outcome(P[r["doc_id"]][a], r["gold"], set(r["doc_dates"]), r.get("lenient"), True)
                                     for r in rows)
            ex = oc["correct"] + oc["correct_null"]
            found = sum(_ok(P[r["doc_id"]][a], r) for r in val)
            on_null = sum(P[r["doc_id"]][a] is not None for r in nul)
            out[a] = dict(exact=[ex, len(rows)], exact_ci_pct=_pct(wilson(ex, len(rows))),
                          dates_found=[found, len(val)], dates_found_ci_pct=_pct(wilson(found, len(val))),
                          wrong_printed_date=oc["misattributed"], fabricated=oc["fabricated"], missed=oc["false_null"],
                          values_on_answerless=[on_null, len(nul)], values_on_answerless_ci_pct=_pct(wilson(on_null, len(nul))))
        return out

    r8 = {r["doc_id"] for r in res8["per_doc"]}
    rows52 = [r for r in res70["per_doc"] if r["doc_id"] in r8]
    t62 = table(res70["per_doc"])
    t52 = table(rows52)
    t52_8b = {k: v for k, v in table(res8["per_doc"]).items() if k in ("rules", "pointer", "cascade")}

    def pair(rows, a, b, answered_only):
        """exact McNemar: a_only / b_only = documents right only under a / only under b."""
        from eval.gold2.hypotheses2 import mcnemar_exact

        P = {r["doc_id"]: preds(r) for r in rows}
        sel = [r for r in rows if r["gold"] is not None] if answered_only else rows
        x = sum(_ok(P[r["doc_id"]][a], r) and not _ok(P[r["doc_id"]][b], r) for r in sel)
        y = sum(_ok(P[r["doc_id"]][b], r) and not _ok(P[r["doc_id"]][a], r) for r in sel)
        return dict(n=len(sel), a_only=x, b_only=y, p=mcnemar_exact(x, y))

    rows8 = res8["per_doc"]
    comparisons = {
        "70b_pointer_vs_latest_printed_date_answered_29": pair(res70["per_doc"], "pointer", "latest_printed_date", True),
        "70b_pointer_vs_latest_printed_date_all_62": pair(res70["per_doc"], "pointer", "latest_printed_date", False),
        "70b_pointer_vs_latest_gated_all_62": pair(res70["per_doc"], "pointer", "latest_date_gated_by_doc_type", False),
        "70b_pointer_vs_latest_gated_answerless_33": pair([r for r in res70["per_doc"] if r["gold"] is None], "pointer",
                                                          "latest_date_gated_by_doc_type", False),
        "8b_pointer_vs_latest_printed_date_answered_21": pair(rows8, "pointer", "latest_printed_date", True),
        "70b_pointer_vs_latest_printed_date_answered_21": pair(rows52, "pointer", "latest_printed_date", True),
    }
    out = dict(
        label="POST HOC (10 Oct 2026): P2 table with Wilson 95% CIs per arm (percent) and the ungated latest-printed-"
              "date baseline; strict scoring (eval/score.py outcome), θ = 10.40, recomputed from the per-document files.",
        sources=[str(SETS["p2"]["res"].relative_to(RESULTS.parent)), f"results/eval2/p2__{b8}.json", "data/gold2/p2_docs.jsonl"],
        all_62_70b=t62, reachable_52_70b=t52, reachable_52_8b=t52_8b, comparisons=comparisons,
        baseline_definitions=dict(
            latest_printed_date="max of the dates the lattice finds anywhere in the document (no gate)",
            latest_date_gated_by_doc_type="the same, null where OPD types the document as a member's text (intervention)",
            latest_date_on_answer_docs_only="the same, only where OPD types the document as an answer"),
    )
    p = RESULTS / "eval2" / "posthoc_r5_p2_table.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


def _pct(ci):
    return [round(100 * ci[0], 1), round(100 * ci[1], 1)]


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "annotate":
        annotate(sys.argv[2])
    elif cmd == "one":  # dry check on one document: python -m eval.posthoc_r5 one p1 <doc_id>
        d = next(x for x in docs(sys.argv[2]) if x["doc_id"] == int(sys.argv[3]))
        print(json.dumps(annotate_one(sys.argv[2], d), ensure_ascii=False, indent=1))
    elif cmd == "analyse":
        o = analyse()
        for s in ("p1", "p2"):
            print(s, json.dumps(o[s]["agreement"]["overall"]), json.dumps(o[s]["sensitivity"], indent=0)[:1500])
        print(json.dumps({k: v for k, v in o["p1_h1_j2_recompute"].items() if k != "the_7_committed"}))
    elif cmd == "p2table":
        p2table()
