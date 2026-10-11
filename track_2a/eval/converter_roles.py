"""Exploratory (after LOCK9): the converter's role rules (gegenprobe.convert.roles) scored against the P8 gold.

    PYTHONPATH=src:. python -m eval.converter_roles dev        score the current rules on the 6 development parliaments
    PYTHONPATH=src:. python -m eval.converter_roles write      write results/schema/v0_2/converter_roles.json and
                                                               converter_roles_per_affair.tsv (no document text)
    PYTHONPATH=src:. python -m eval.converter_roles --check    exit 1 if the committed files differ from a fresh run

Not pre-registered. Written after P8 (eval/prereg9/LOCK9) was locked and labelled, so it is reported as exploratory.
The split was fixed before any held-out label or text was opened (SPLIT_RULE): the 5 of P8's 11 parliaments with the
smallest sha256("gegenprobe-r13A-converter-roles:" + body key) are held out; rules were written on the other 6 (and on
P3/P3b/P5 documents of parliaments outside the held-out five). Held-out and in-sample (development) figures are reported
apart, each with Wilson 95% intervals. Texts: the sha256-verified cached extractions of P8's 132 documents
(gegenprobe.pdftext, WORK/text); nothing of them is written.

Two rule versions are scored, apart:
  * roles-1, FROZEN (results/schema/v0_2/converter_roles_frozen/roles_r13a_heldout.py, sha256 FROZEN_SHA256, a
    byte copy of src/gegenprobe/convert/roles.py when the held-out score was taken): `frozen.held_out` is the
    generalisation estimate (rules never developed on those parliaments); `frozen.in_sample_dev` is in-sample.
  * roles-2, CURRENT (src/gegenprobe/convert/roles.py; what the converter records use): roles-1 plus post-hoc rules
    written after the frozen held-out score, from the held-out parliaments' layouts. Every one of its P8 figures is
    in-sample (`post_hoc.*`); it is reported to say what the records carry, not as a generalisation estimate.

Fields and what counts as correct:
  * authors (affair): the set of (person or body, role) the rules print equals the gold set (P8 parts submitter and
    co_signatories, union) - names matched by gegenprobe.convert.roles.same_person; persons: precision and recall of
    (name, role) pairs pooled over affairs; author_names: the same without the role.
  * author_pattern (affair): the gold's role pattern (sole, joint, first+co, group, ...) reproduced.
  * language_of_text (document): the set of languages equals the gold's languages for that document.
  * instrument_named / instrument_function (affair): equal to the gold value; gold `unclear` function is not
    determinable and left out of the denominator (counted apart).
  * submission dates (pairs): (ISO date, role) with role in signed / lodged / announced / later_step (P8's
    session_lodged = announced; the rules' received = lodged, P8 counts a receipt as lodged); precision and recall pooled.
An abstention (nothing printed by the rules) counts against recall and accuracy, never against precision.
"""
from __future__ import annotations

import collections
import hashlib
import importlib.util
import json
import math
import sys

from gegenprobe.convert import roles as R
from gegenprobe.paths import ROOT, TEXT_CACHE

D8 = ROOT / "data" / "p8"
OUT = ROOT / "results" / "schema" / "v0_2"
PARLIAMENTS = ("261", "351", "5002", "5192", "5586", "6643", "FR", "GR", "TG", "VD", "VS")
SPLIT_SALT = "gegenprobe-r13A-converter-roles:"
SPLIT_RULE = (f'held out = the 5 parliaments with the smallest sha256("{SPLIT_SALT}" + body key); fixed before any '
              "held-out label or text was opened")
FROZEN = OUT / "converter_roles_frozen" / "roles_r13a_heldout.py"
FROZEN_SHA256 = "01a06cc4cf84c0034524ec214c4ec7c81160d13b3b9c857a1ab2f703f01fb8d9"
SUB_ROLES = {"signed": "signed", "lodged": "lodged", "received": "lodged", "session_lodged": "announced",
             "announced": "announced", "later_step": "later_step"}


def frozen_rules():
    """The frozen roles-1 module, loaded from its committed byte copy (verified by sha256) inside gegenprobe.convert."""
    got = hashlib.sha256(FROZEN.read_bytes()).hexdigest()
    if got != FROZEN_SHA256:
        raise SystemExit(f"{FROZEN}: sha256 {got} is not the frozen {FROZEN_SHA256}")
    name = "gegenprobe.convert._roles_r13a_frozen"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, FROZEN)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


def split() -> dict[str, str]:
    order = sorted(PARLIAMENTS, key=lambda k: hashlib.sha256((SPLIT_SALT + k).encode()).hexdigest())
    return {k: ("held_out" if i < 5 else "dev") for i, k in enumerate(order)}


def wilson(k: int, n: int, z: float = 1.959963984540054) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def _jsonl(p) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def pages_of(sha: str, image_only: bool = False) -> list[str] | None:
    """The cached extraction (OCR when the document is image-only and an OCR text exists)."""
    ps = sorted(TEXT_CACHE.glob(f"{sha}.*.json"))
    if not ps:
        return None
    ocr = [p for p in ps if ".tesseract-" in p.name]
    pick = ocr[0] if (image_only and ocr) else next((p for p in ps if ".pdftotext-" in p.name), ps[0])
    return json.loads(pick.read_text(encoding="utf-8"))["pages"]


def gold_people(g: dict) -> list[dict]:
    seen, out = set(), []
    for p in g["parts"]["submitter"]["people"] + g["parts"]["co_signatories"]["people"]:
        k = (p["name"], p["role"])
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def _pattern(roles: list[str]) -> str:
    c = collections.Counter(roles)
    if not c:
        return "none"
    keys = sorted(c)
    return "+".join(f"{k}{'*' if c[k] > 1 else ''}" for k in keys)


def gold_dates(g: dict, dl: dict) -> set[tuple[str, str]]:
    letters = {d["letter"]: d["date"] for d in dl["dates"]}
    out = set()
    for k, rs in g["parts"]["date_submission"]["dates"].items():
        for r in rs:
            if r in SUB_ROLES:
                out.add((letters[k], SUB_ROLES[r]))
    for e in g["parts"]["date_submission"]["extra_dates"]:
        for r in e["roles"]:
            if r in SUB_ROLES:
                out.add((e["date"], SUB_ROLES[r]))
    return out


def _match(pred: list[tuple[str, str]], gold: list[tuple[str, str]], with_role: bool = True, rules=R) -> int:
    """Greedy one-to-one matches of (name, role) pairs."""
    used, n = set(), 0
    for pn, pr in pred:
        for i, (gn, gr) in enumerate(gold):
            if i in used:
                continue
            if rules.same_person(pn, gn) and (not with_role or pr == gr):
                used.add(i)
                n += 1
                break
    return n


def score_affair(g: dict, aff: dict, dl: dict, rules=R) -> dict:
    docs = {d["role"]: d for d in aff["docs"]}
    q = pages_of(docs["question"]["sha256"], docs["question"]["image_only"])
    a = pages_of(docs["answer"]["sha256"], docs["answer"]["image_only"])
    if q is None or a is None:
        raise SystemExit(f"{g['id']}: document text not cached (run the P8 fetch through gegenprobe.pdftext first)")
    x = rules.extract(q, a, aff["body"])
    pred = [(p["name"]["value"], p["role"]) for p in x["actors"]]
    gp = [(p["name"], p["role"]) for p in gold_people(g)]
    m_role, m_name = _match(pred, gp, rules=rules), _match(pred, gp, with_role=False, rules=rules)
    authors_ok = m_role == len(pred) == len(gp)
    gl = g["parts"]["language"]["languages"]
    lang = {r: (sorted(x["language_of_text"][r] or []), sorted(gl.get(r) or [])) for r in ("question", "answer")}
    fn_gold = g["parts"]["type"]["function"]["value"]
    named_gold = (g["parts"]["type"].get("instrument_named") or {}).get("value") or "none"
    ins = x["instrument"]
    fn_pred = ins["function"]["value"] if ins else None
    named_pred = ins["named"]["value"] if ins else "none"
    pd = {(d["value"], SUB_ROLES[d["role"]]) for d in x["dates"] if d["role"] in SUB_ROLES}
    gd = gold_dates(g, dl)
    return dict(
        id=g["id"], affair_id=g["affair_id"], body=aff["body"],
        n_gold_people=len(gp), n_pred_people=len(pred), matched_role=m_role, matched_name=m_name, authors_ok=authors_ok,
        pattern_gold=_pattern([r for _, r in gp]), pattern_pred=_pattern([r for _, r in pred]),
        author_rules=sorted({p["name"]["rule"] for p in x["actors"]}),
        lang_q_pred=lang["question"][0], lang_q_gold=lang["question"][1],
        lang_a_pred=lang["answer"][0], lang_a_gold=lang["answer"][1],
        named_pred=named_pred, named_gold=named_gold, function_pred=fn_pred, function_gold=fn_gold,
        dates_pred=sorted(pd), dates_gold=sorted(gd), dates_matched=len(pd & gd),
    )


def rows(which: set[str], rules=R) -> list[dict]:
    sp = split()
    gold = {g["affair_id"]: g for g in _jsonl(D8 / "p8_gold.jsonl")}
    affs = {a["affair_id"]: a for a in _jsonl(D8 / "p8_affairs.jsonl")}
    dls = {d["id"]: d for d in _jsonl(D8 / "p8_datelists.jsonl")}
    out = []
    for aid in sorted(gold, key=lambda k: gold[k]["id"]):
        g = gold[aid]
        if sp[g["body"]] not in which:
            continue
        r = score_affair(g, affs[aid], dls[g["id"]], rules=rules)
        r["split"] = sp[g["body"]]
        r["rules"] = rules.RULES_VERSION
        out.append(r)
    return out


def _rate(k: int, n: int) -> dict:
    return dict(k=k, n=n, rate=round(k / n, 4) if n else None, wilson95=wilson(k, n))


def summarise(rs: list[dict]) -> dict:
    n = len(rs)
    pred_p = sum(r["n_pred_people"] for r in rs)
    gold_p = sum(r["n_gold_people"] for r in rs)
    m_role = sum(r["matched_role"] for r in rs)
    m_name = sum(r["matched_name"] for r in rs)
    lang_docs = [(r["lang_q_pred"], r["lang_q_gold"]) for r in rs] + [(r["lang_a_pred"], r["lang_a_gold"]) for r in rs]
    fn = [r for r in rs if r["function_gold"] != "unclear"]
    dp = sum(len(r["dates_pred"]) for r in rs)
    dg = sum(len(r["dates_gold"]) for r in rs)
    dm = sum(r["dates_matched"] for r in rs)
    return dict(
        n_affairs=n, n_parliaments=len({r["body"] for r in rs}), parliaments=sorted({r["body"] for r in rs}),
        authors_affair_exact=_rate(sum(r["authors_ok"] for r in rs), n),
        authors_affair_with_any_prediction=_rate(sum(r["n_pred_people"] > 0 for r in rs), n),
        author_pattern=_rate(sum(r["pattern_gold"] == r["pattern_pred"] for r in rs), n),
        author_pairs_precision=_rate(m_role, pred_p), author_pairs_recall=_rate(m_role, gold_p),
        author_names_precision=_rate(m_name, pred_p), author_names_recall=_rate(m_name, gold_p),
        language_of_text_documents=_rate(sum(set(p) == set(g) for p, g in lang_docs), len(lang_docs)),
        language_of_text_abstained=sum(not p for p, _ in lang_docs),
        instrument_named=_rate(sum(r["named_pred"] == r["named_gold"] for r in rs), n),
        instrument_function=_rate(sum(r["function_pred"] == r["function_gold"] for r in fn), len(fn)),
        instrument_function_gold_unclear=n - len(fn),
        instrument_function_abstained=sum(r["function_pred"] is None for r in fn),
        submission_dates_precision=_rate(dm, dp), submission_dates_recall=_rate(dm, dg),
        submission_dates_affair_exact=_rate(sum(set(map(tuple, r["dates_pred"])) == set(map(tuple, r["dates_gold"]))
                                                for r in rs), n),
    )


TSV_COLS = ("rules", "split", "id", "affair_id", "body", "authors_ok", "pattern_gold", "pattern_pred", "n_gold_people",
            "n_pred_people", "matched_role", "matched_name", "author_rules", "lang_q_gold", "lang_q_pred", "lang_a_gold",
            "lang_a_pred", "named_gold", "named_pred", "function_gold", "function_pred", "dates_gold", "dates_pred",
            "dates_matched")


def _cell(v) -> str:
    if isinstance(v, list):
        return ";".join(",".join(x) if isinstance(x, (list, tuple)) else str(x) for x in v)
    return "" if v is None else str(v)


def render() -> dict[str, str]:
    sp = split()
    fr = frozen_rules()
    out = {}
    for tag, rules in (("frozen", fr), ("post_hoc", R)):
        rs = rows({"dev", "held_out"}, rules=rules)
        out[tag] = dict(rows=rs, held=[r for r in rs if r["split"] == "held_out"],
                        dev=[r for r in rs if r["split"] == "dev"])
    res = dict(
        status="exploratory: not pre-registered; written after eval/prereg9/LOCK9 (P8 locked and labelled)",
        command="PYTHONPATH=src:. python -m eval.converter_roles write",
        gold="data/p8/p8_gold.jsonl (66 affairs, 11 parliaments)",
        split_rule=SPLIT_RULE, split=dict(held_out=sorted(k for k, v in sp.items() if v == "held_out"),
                                          dev=sorted(k for k, v in sp.items() if v == "dev")),
        exposure=("before the split the agent saw the gold submitter labels of P8-001 (VD) and P8-002 (5192), both held "
                  "out; no held-out document text was read before the frozen held-out score"),
        scoring=__doc__.split("Fields and what counts as correct:")[1].strip(),
        language_method=R.LANG_METHOD,
        frozen=dict(rules_version=fr.RULES_VERSION, rules=FROZEN.relative_to(ROOT).as_posix(), rules_sha256=FROZEN_SHA256,
                    note="generalisation estimate = held_out; in_sample_dev is the development set",
                    held_out=summarise(out["frozen"]["held"]), in_sample_dev=summarise(out["frozen"]["dev"])),
        post_hoc=dict(rules_version=R.RULES_VERSION, rules="src/gegenprobe/convert/roles.py",
                      rules_sha256=hashlib.sha256((ROOT / "src" / "gegenprobe" / "convert" / "roles.py").read_bytes())
                      .hexdigest(),
                      note=("in-sample on all 66: roles-2 adds rules written after the frozen held-out score from the "
                            "held-out parliaments' layouts; this is what the converter's v0.2 records carry"),
                      all_in_sample=summarise(out["post_hoc"]["rows"]),
                      held_out_parliaments_in_sample=summarise(out["post_hoc"]["held"]),
                      dev_parliaments_in_sample=summarise(out["post_hoc"]["dev"])),
        per_affair="results/schema/v0_2/converter_roles_per_affair.tsv",
    )
    rs = out["frozen"]["rows"] + out["post_hoc"]["rows"]
    tsv = "\t".join(TSV_COLS) + "\n" + "".join("\t".join(_cell(r[c]) for c in TSV_COLS) + "\n" for r in rs)
    return {"converter_roles.json": json.dumps(res, ensure_ascii=False, indent=1) + "\n",
            "converter_roles_per_affair.tsv": tsv}


def main(argv: list[str]) -> int:
    if argv[:1] == ["dev"]:
        rs = rows({"dev"})
        print(json.dumps(summarise(rs), indent=1))
        for r in rs:
            print("\t".join(_cell(r[c]) for c in TSV_COLS))
        return 0
    files = render()
    if "--check" in argv:
        bad = [n for n, t in files.items() if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != t]
        print("converter roles:", "differs: " + ", ".join(bad) if bad else "committed files current")
        return 1 if bad else 0
    if argv[:1] != ["write"]:
        print(__doc__)
        return 2
    for n, t in files.items():
        (OUT / n).write_text(t, encoding="utf-8")
        print(OUT / n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
