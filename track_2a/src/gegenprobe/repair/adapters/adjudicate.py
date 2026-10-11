"""P7: Apertus as a closed-set verifier for the source adapters' review queue.

The adapters send a row to review when identity holds but the heading or the date check does not (base.Adapter.check):
917 rows that a person would have to read. Blind audit v3 suggests many are real answers (the Claude auditor judged 23 of
30 review decoys to be the executive's answer). P7 asks Apertus two closed-set questions per review row and promotes a
row only when both answers pass and the date passes the adapters' own date rules. Nothing is generated into the data:

  (A) is_answer   one user message (intervention number, title, type; the document view), then the assistant prefix
                  '{"answer":' and two scored continuations ' "yes"}' / ' "no"}'; m_yes = lp(yes) - lp(no)
  (B) date        a lettered choice among the dates printed in the document view (each shown with its printed line) plus
                  one 'none' letter; the argmax letter; the date is a printed value whose span is located by code
  promote         m_yes > THETA_A, (B) chose a printed date d, and base.Adapter.date_check(full text, d, OPD answer
                  events, OPD executive events) passes with a counted date class (eq, eq_gov, window, anywhere): the
                  same rules as every counted row, with d in the place of the date the header regex read

The contrast arm (free generation): one plain user message asking for {"answer": yes/no, "answer_date": ...}; a row
passes when the reply says yes and its date is one of the printed dates and passes the same date rule.

Model calls only through llm.Gateway on the -8b name (serves the 70B weights; accepts the prefill); llm.py refuses a
prefill to any other name and checks the served model on every live call; `served()` re-reads the stored response model
of every cache entry a row used.
"""
from __future__ import annotations

import csv
import dataclasses
import hashlib
import math
import re
import string

from ...paths import DATA, RESULTS
from ...stats import logsumexp
from ..common import parse_dates
from . import base, lists, registry, run

OUT = RESULTS / "repair" / "adapters" / "p7"
HEAD_M, TAIL_M = 9000, 3000  # the model's view of a document: first 9,000 and last 3,000 characters
LETTERS = string.ascii_uppercase
MAX_DATES = len(LETTERS) - 1
LINE_CHARS = 160
LINES_PER_DATE = 2
COUNTED_CLASSES = ("eq", "eq_gov", "window", "anywhere")  # run.TIERS of the counted tiers, latest_in_window excluded
ANSWER_PREFIX = '{"answer":'
YES, NO = ' "yes"}', ' "no"}'  # closing '"}' included: a bare closing quote is an unnatural token
CHOICE_PREFIX = '{"choice":'
# review reasons P7 never promotes: opd_doc_ambiguous (which OPD document is meant is not a content question),
# no_answer_event (no OPD date to check against), and the document-type filters (filters.py: the document's own wording
# types it as something else; a filter only moves a row down and no model answer moves it back up)
INELIGIBLE = ("opd_doc_ambiguous", "no_answer_event", "resolution_reply", "wrong_affair")

# ------------------------------------------------------------------------------------------------------------ prompts
_INTRO = """Here is a document from the website of a Swiss parliament (a canton or a municipality), and a parliamentary \
intervention as recorded in OpenParlData.

Intervention
- number: {number}
- title: {title}
- type: {type}

<document>
{doc}
</document>
"""

IS_ANSWER = {
    "a1": _INTRO + """
Does this document print the executive's written answer to this intervention, that is the answer or position of the \
government (Regierungsrat, Stadtrat, Gemeinderat, Conseil d'État, Conseil communal, Municipalité, Consiglio di Stato, \
Municipio)? Answer "no" if the document is only the intervention's own text as submitted, minutes or a report of the \
parliament that only mention the answer, a commission report, a request for more time, or the answer to a different \
intervention. Rely only on the document. Reply as a JSON object: {{"answer": "yes" or "no"}}""",
    # a2 (dev round 2): the three failure kinds of the dev labels spelled out as checks; written after reading the dev
    # labels (DEV ONLY), the same kinds the annotation guide and the adapters' filters name
    "a2": _INTRO + """
Does this document print the executive's written answer to this intervention? Check three things:
1. Author: the answer is given by the executive itself (the government: Regierungsrat, Stadtrat, Gemeinderat, \
Conseil d'État, Conseil communal, Municipalité, Consiglio di Stato, Municipio), not by a body of the parliament (its \
bureau, Büro, Geschäftsleitung, a commission).
2. Subject: the document is about this intervention; its subject matches the title above, not another intervention \
that carries a similar number.
3. Content: it gives the executive's answer or final position, not only the intervention's own text as submitted, an \
interim report, a request for more time, or minutes or a report that only mention the answer.
Answer "yes" only if all three hold. Rely only on the document. Reply as a JSON object: {{"answer": "yes" or "no"}}""",
}

DATE_MCQ = {
    "b1": _INTRO + """
These dates are printed in the document, each with the line it is printed in:
{options}

Which of these dates is the date of the government's answer to this intervention: the date on which the executive \
decided its answer (for example «Regierungsratsbeschluss vom …», «Sitzung vom …», «séance du …», «seduta del …») or the \
date of its answer letter? Not meant: the date the intervention was submitted, dates of debates in parliament, and any \
other date. If none of the listed dates is such a date, choose {null_label}. Rely only on the document. Reply as a JSON \
object: {{"choice": "letter"}}""",
}
NONE_OPTION = "none of these dates is the date of the government's answer"

FREEGEN = _INTRO + """
Does this document print the executive's written answer to this intervention (the answer or position of the \
government: Regierungsrat, Stadtrat, Gemeinderat, Conseil d'État, Conseil communal, Municipalité, Consiglio di Stato, \
Municipio)? Answer "no" if the document is only the intervention's own text as submitted, minutes or a report of the \
parliament that only mention the answer, a commission report, a request for more time, or the answer to a different \
intervention. If it is the answer, also give the date of the government's answer (its decision or its answer letter) as \
printed in the document. Rely only on the document. Reply with one JSON object only: {{"answer": "yes" or "no", \
"answer_date": "DD.MM.YYYY" or null}}"""


def prompt_id(name: str, tmpl: str) -> str:
    return f"p7/{name}@{hashlib.sha256(tmpl.encode()).hexdigest()[:12]}"


# ------------------------------------------------------------------------------------------------------------ views
def model_view(text: str) -> tuple[str, int]:
    """(the text the model reads, the offset in the full text where the tail part starts, or -1 if not cut)."""
    if len(text) <= HEAD_M + TAIL_M:
        return text, -1
    cut = len(text) - TAIL_M
    return text[:HEAD_M] + "\n[…]\n" + text[cut:], cut


def view_to_full(pos: int, text: str) -> int:
    """Offset in the model view -> offset in the full text."""
    if len(text) <= HEAD_M + TAIL_M or pos < HEAD_M:
        return pos
    return len(text) - TAIL_M + (pos - HEAD_M - len("\n[…]\n"))


def _clip(text: str, start: int, end: int) -> str:
    a = text.rfind("\n", 0, start) + 1
    b = text.find("\n", end)
    line = re.sub(r"\s+", " ", text[a:b if b >= 0 else len(text)]).strip()
    if len(line) <= LINE_CHARS:
        return line
    raw = re.sub(r"\s+", " ", text[start:end])
    i = max(0, line.find(raw))
    lo = max(0, min(i - LINE_CHARS // 2, len(line) - LINE_CHARS))
    return ("…" if lo > 0 else "") + line[lo:lo + LINE_CHARS] + ("…" if lo + LINE_CHARS < len(line) else "")


def options(view: str) -> tuple[list[str], list[str], list[tuple[str, int, int]]]:
    """(distinct ISO dates printed in the view, in reading order, at most MAX_DATES; one option line per date with up to
    LINES_PER_DATE printed lines; every occurrence (iso, start, end) in the view). Dates are read with the adapters'
    own parser (repair.common.parse_dates), so the chosen value is in the space the date rules compare."""
    occ = parse_dates(view)
    values = list(dict.fromkeys(d for d, _, _ in occ))[:MAX_DATES]
    lines = []
    for v in values:
        seen: list[str] = []
        for d, s, e in occ:
            if d == v:
                ln = _clip(view, s, e)
                if ln and ln not in seen:
                    seen.append(ln)
            if len(seen) >= LINES_PER_DATE:
                break
        lines.append(f"{v[8:10]}.{v[5:7]}.{v[:4]} — " + " | ".join(f"«{s}»" for s in seen))
    return values, lines, occ


def span(iso: str, occ: list[tuple[str, int, int]], view: str, text: str) -> dict | None:
    """Provenance of a chosen date: its first printed occurrence (located by code), mapped to full-text offsets."""
    hits = [(s, e) for d, s, e in occ if d == iso]
    if not hits:
        return None
    s, e = hits[0]
    fs, fe = view_to_full(s, text), view_to_full(e, text)
    return dict(char_start=fs, char_end=fe, printed=text[fs:fe], line=_clip(text, fs, fe)[:200],
                occurrence_rule="first_occurrence", n_occurrences=len(hits))


def fill(tmpl: str, x: dict, view: str, **kw) -> str:
    out = tmpl.format(number=x.get("number") or "", title=(x.get("title") or "").strip() or "(none)",
                      type=x.get("type") or "(none)", doc="{doc}", options="{options}", null_label="{null_label}")
    for k, v in kw.items():
        out = out.replace("{" + k + "}", v)
    return out.replace("{doc}", view)


# ------------------------------------------------------------------------------------------------------------ calls
def ask_is_answer(be, x: dict, view: str, variant: str = "a1") -> dict:
    tmpl = IS_ANSWER[variant]
    lp_yes, lp_no = be.score(fill(tmpl, x, view), ANSWER_PREFIX, [YES, NO])
    return dict(lp_yes=lp_yes, lp_no=lp_no, m_yes=lp_yes - lp_no, prompt_id=prompt_id(variant, tmpl))


def ask_date(be, x: dict, view: str, variant: str = "b1") -> dict:
    tmpl = DATE_MCQ[variant]
    values, lines, _ = options(view)
    if not values:
        return dict(values=[], lps=[], lp_none=0.0, choice=None, m_none=math.inf, prompt_id=prompt_id(variant, tmpl))
    none = LETTERS[len(values)]
    opts = "\n".join(f"{LETTERS[i]}: {s}" for i, s in enumerate(lines)) + f"\n{none}: {NONE_OPTION}"
    lps = be.score(fill(tmpl, x, view, options=opts, null_label=none), CHOICE_PREFIX,
                   [f' "{LETTERS[i]}"}}' for i in range(len(values) + 1)])
    best = max(range(len(values)), key=lambda i: lps[i])
    m_none = lps[-1] - logsumexp(lps[:-1])
    return dict(values=values, lps=lps[:-1], lp_none=lps[-1], m_none=m_none,
                choice=values[best] if lps[best] > lps[-1] else None, prompt_id=prompt_id(variant, tmpl))


def _json_field(g: str, key: str):
    from ...convert.pointer_v2 import _json_field as jf
    return jf(g, key)


def ask_free(be, x: dict, view: str, seed: int = 0, max_tokens: int = 80) -> dict:
    """The contrast arm: free generation, read back; the date counts only if it is printed in the view."""
    from ...convert.pointer_v2 import read_date
    g = be.generate(fill(FREEGEN, x, view), max_tokens=max_tokens, seed=seed)
    ans = str(_json_field(g, "answer") or "").strip().lower()
    iso = read_date(_json_field(g, "answer_date"))
    values, _, _ = options(view)
    return dict(answer=ans if ans in ("yes", "no") else "invalid", date=iso if iso in values else None, iso=iso,
                printed=iso in values, raw=g[:300], prompt_id=prompt_id("free", FREEGEN))


# ------------------------------------------------------------------------------------------------------------ decision
@dataclasses.dataclass
class Config:
    theta_a: float = 0.0  # promote only if m_yes > theta_a
    theta_b: float = 0.0  # the date choice names its argmax printed date iff m_none = lp(none) - logsumexp(lp(dates)) <= theta_b
    is_answer: str = "a1"
    date: str = "b1"
    name: str = "p7"


def date_rule(body: str, text: str, d: str | None, x: dict) -> tuple[str | None, bool]:
    """(date class, passes) of the adapters' own date check with `d` as the document's date."""
    if not d:
        return None, False
    ad = registry.get(body)
    ad._submit = x.get("submit_dates") or []
    match, _eq, ok = ad.date_check(text, d, x.get("answer_dates") or [], x.get("gov_dates"))
    cls = re.sub(r"\(.*", "", match or "")
    return match, bool(ok) and cls in COUNTED_CLASSES


def decide(f: dict, cfg: Config) -> dict:
    """f: a feature row (features()). Returns promote, reason, date, date class."""
    a = f["a"][cfg.is_answer]
    b = f["b"][cfg.date]
    if a["m_yes"] <= cfg.theta_a:
        return dict(promote=False, why="is_answer_below_theta", date=None, date_class=None)
    d = date_choice(b, cfg.theta_b)
    if not d:
        return dict(promote=False, why="no_date_chosen", date=None, date_class=None)
    cls, ok = b["rule_all"][d]
    if not ok:
        return dict(promote=False, why="date_rule_fails", date=d, date_class=cls)
    return dict(promote=True, why="promoted", date=d, date_class=cls)


def date_choice(b: dict, theta_b: float) -> str | None:
    """The argmax printed date of the lettered choice, or None when the 'none' letter leads by more than theta_b."""
    if not b["values"] or b["m_none"] > theta_b:
        return None
    return b["values"][max(range(len(b["values"])), key=lambda i: b["lps"][i])]


def tier_for(date_class: str | None) -> str | None:
    """The counted tier the date class would carry (run.tier_of), recorded as the promoted row's sub-tier."""
    try:
        return run.tier_of(date_class)
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------------------------ the queue
def review_rows() -> list[dict]:
    """Every review row of the committed adapter lists, with its reason class and eligibility."""
    out = []
    for p in sorted(run.OUT.glob(f"{lists.PREFIX}*.tsv")):
        body = p.stem[len(lists.PREFIX):]
        with open(p, encoding="utf-8") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                if r["tier"] != "review":
                    continue
                cls = run._reason_key(r["review_reason"])
                out.append(dict(body=body, affair_id=int(r["affair_id"]), affair_number=r["affair_number"],
                                reason=cls, proposed_action=r["proposed_action"], opd_doc_id=r["opd_doc_id"],
                                text_sha256=r["text_sha256"], eligible=cls not in INELIGIBLE
                                and base.excerpt_path(body, int(r["affair_id"])).exists()))
    return out


def excerpt_text(body: str, aid: int) -> str:
    raw = base.excerpt_path(body, aid).read_text(encoding="utf-8")
    return raw.split("\n\n", 1)[1] if "\n\n" in raw else raw


def features(be, row: dict, x: dict, a_variants=("a1",), b_variants=("b1",), free: bool = True) -> dict:
    """Every model answer a decision needs for one review row; the only document text kept is each printed date's line
    (span, at most 200 characters), as in the adapter lists' quotes."""
    text = excerpt_text(row["body"], row["affair_id"])
    assert hashlib.sha256(text.encode()).hexdigest() == row["text_sha256"], (row["body"], row["affair_id"])
    view, _ = model_view(text)
    values, _, occ = options(view)
    f = dict(body=row["body"], affair_id=row["affair_id"], reason=row["reason"], n_dates=len(values),
             chars=len(text), truncated=len(view) < len(text), a={}, b={})
    for v in a_variants:
        f["a"][v] = ask_is_answer(be, x, view, v)
    for v in b_variants:
        q = ask_date(be, x, view, v)
        q["rule"] = list(date_rule(row["body"], text, q["choice"], x))
        q["spans"] = {d: span(d, occ, view, text) for d in values}
        q["rule_all"] = {d: list(date_rule(row["body"], text, d, x)) for d in values}
        f["b"][v] = q
    if free:
        g = ask_free(be, x, view, seed=row["affair_id"] % 100000)
        g["rule"] = list(date_rule(row["body"], text, g["date"], x))
        f["free"] = g
    # baselines without a model: (iii) some printed date equals an OPD answer event exactly; the row's own date check
    ev = set(x.get("answer_dates") or [])
    f["exact_printed"] = any(d in ev for d, _, _ in parse_dates(text))
    f["printed_dates"] = values
    return f


# ------------------------------------------------------------------------------------------------------------ frozen
CONFIG = DATA / "p7" / "p7_config.json"
QUEUE_SPEC = "gateway:swiss-ai/apertus-v1.5-8b:2a-p7-queue:2.0"
TIER = "promoted_by_apertus"
PROMOTED_COLS = ["body", "affair_id", "affair_number", "tier", "counted", "date_tier", "date_class", "answer_date",
                 "span_char_start", "span_char_end", "span_line", "m_yes", "m_none", "review_reason", "proposed_action",
                 "opd_doc_id", "text_sha256", "prompt_is_answer", "prompt_date", "model"]


def load_config() -> Config:
    import json
    d = json.loads(CONFIG.read_text())
    return Config(theta_a=d["theta_a"], theta_b=d["theta_b"], is_answer=d["is_answer"], date=d["date"], name=d["name"])


def backend(spec: str):
    """llm.Gateway on the -8b name only (prefill allowed there; the 70B name is never sent a prefill)."""
    from ... import llm
    _, model, tag, cap = spec.split(":", 3)
    if model != "swiss-ai/apertus-v1.5-8b" or not tag.startswith("2a-p7"):
        raise ValueError(f"P7 runs only on swiss-ai/apertus-v1.5-8b with a 2a-p7* tag, not {spec}")
    be = llm.Gateway(model, tag=tag, cap_usd=float(cap), build=f"publicai:{model}")
    served: list = []
    orig = be._cached_call

    def rec(kind, payload):
        o = orig(kind, payload)
        m = (o.get("resp") or {}).get("model")
        if m != be.model:  # every call, cached or live
            raise llm.ServedModelMismatch(f"requested {be.model}, served {m}")
        served.append(m)
        return o

    be._cached_call = rec
    be.served_log = served
    return be


def run_rows(be, rows: list[dict], cfg: Config, free: bool, workers: int = 4) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor

    from . import targets
    tg = {}
    for b in sorted({r["body"] for r in rows}):
        tg.update({(b, x["id"]): x for x in targets.load(b)})

    def one(r):
        f = features(be, r, tg[(r["body"], r["affair_id"])], (cfg.is_answer,), (cfg.date,), free=free)
        f.update(id=r.get("id"), decision=decide(f, cfg))
        return f

    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, rows))


def promoted_row(r: dict, f: dict, cfg: Config) -> dict:
    d = f["decision"]
    sp = (f["b"][cfg.date].get("spans") or {}).get(d["date"]) or {}
    return dict(body=r["body"], affair_id=r["affair_id"], affair_number=r["affair_number"], tier=TIER, counted="false",
                date_tier=tier_for(d["date_class"]), date_class=d["date_class"], answer_date=d["date"],
                span_char_start=sp.get("char_start"), span_char_end=sp.get("char_end"), span_line=sp.get("line"),
                m_yes=round(f["a"][cfg.is_answer]["m_yes"], 3), m_none=round(f["b"][cfg.date]["m_none"], 3),
                review_reason=r["reason"], proposed_action=r["proposed_action"], opd_doc_id=r["opd_doc_id"],
                text_sha256=r["text_sha256"], prompt_is_answer=f["a"][cfg.is_answer]["prompt_id"],
                prompt_date=f["b"][cfg.date]["prompt_id"], model="swiss-ai/apertus-v1.5-8b (70B weights, Public AI)")


def apply(spec: str = QUEUE_SPEC) -> dict:
    """The frozen P7 configuration over every eligible review row of the committed lists -> OUT/promoted.tsv (tier
    promoted_by_apertus, counted=false) + OUT/queue_summary.json. Whether the tier enters a headline is decided by the
    registered hypothesis (eval/p7/hypotheses8.py), never here."""
    import collections
    import json
    cfg = load_config()
    rows = review_rows()
    elig = [r for r in rows if r["eligible"]]
    be = backend(spec)
    feats = run_rows(be, elig, cfg, free=False)
    prom = [promoted_row(r, f, cfg) for r, f in zip(elig, feats) if f["decision"]["promote"]]
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "promoted.tsv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, PROMOTED_COLS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for p in sorted(prom, key=lambda p: (p["body"], p["affair_id"])):
            w.writerow({k: "" if p[k] is None else p[k] for k in PROMOTED_COLS})
    why = collections.Counter(f["decision"]["why"] for f in feats)
    res = dict(review_rows=len(rows), eligible=len(elig),
               ineligible=dict(collections.Counter(r["reason"] for r in rows if not r["eligible"])),
               promoted=len(prom), decisions=dict(why),
               promoted_by_reason=dict(collections.Counter(p["review_reason"] for p in prom)),
               promoted_by_body=dict(collections.Counter(p["body"] for p in prom)),
               promoted_by_date_tier=dict(collections.Counter(p["date_tier"] for p in prom)),
               eligible_by_reason=dict(collections.Counter(r["reason"] for r in elig)),
               calls=len(be.served_log), served=sorted(set(be.served_log)), config=dataclasses.asdict(cfg),
               tier=TIER, counted=False,
               note="promoted rows are listed in their own tier and are not part of any counted total unless the "
                    "registered hypothesis P7-H1 holds (results/p7/p7_hypotheses.json)")
    (OUT / "queue_summary.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    return res


def main(argv: list[str]) -> int:
    import json
    if argv[:1] == ["apply"]:
        print(json.dumps(apply(argv[1] if len(argv) > 1 else QUEUE_SPEC), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
