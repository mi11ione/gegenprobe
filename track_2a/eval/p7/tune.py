"""P7 dev table: every arm's promotions on the dev review rows against the blind dev labels (DEV ONLY).

Written before the dev labels were read (selection rule fixed here):
  gold        per packet, from WORK/p7dev/ann/: `gold.jsonl` when present (A3 tie-break merged), else the annotators'
              common label when all agree, else `disputed`
  correct     a promoted row is correct iff its gold is_answer is `yes` (the audits' precision definition); `date_hit` (the
              chosen date is the gold decision or letter date) is reported alongside
  recall      R_all = correct promotions / gold-yes rows; R_attainable = correct promotions / gold-yes rows for which some
              gold answer date (decision or letter) passes the adapters' date rule (the rows any date-checked promotion
              could reach)
  theta_A     the smallest value on GRID at which no promoted dev row has gold `no`, `unclear` or `disputed`; the
              precision-first choice; reported with every grid point
Arms: rules_only (promote nothing), p7 (is_answer pointer > theta_A and the date choice passes the date rule), free
(free-generation yes + printed date passing the date rule), trivial_exact (some printed date equals an OPD answer event),
a_and_exact (is_answer > theta_A and trivial_exact), oracle_date (is_answer > theta_A and some printed date passes the
rule: the ceiling of a perfect date choice).
"""

from __future__ import annotations

import collections
import functools
import json

from eval.p7 import dev
from gegenprobe.paths import RESULTS
from gegenprobe.repair.adapters import adjudicate as J
from gegenprobe.repair.adapters import targets
from gegenprobe.stats import wilson

GRID = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0]
OUT = RESULTS / "p7"


def _iso(d):
    if not d or d == "null":
        return None
    d = str(d).strip()
    if len(d) == 10 and d[2] == "." and d[5] == ".":
        return f"{d[6:]}-{d[3:5]}-{d[:2]}"
    return d[:10] if len(d) >= 10 and d[4] == "-" else None


def load_ann(workdir=dev.WORKDIR) -> dict[str, dict]:
    ann = workdir / "ann"
    gold = ann / "gold.jsonl"
    if gold.exists():
        return {r["id"]: r for r in map(json.loads, gold.read_text().splitlines()) if r}
    files = sorted(p for p in ann.glob("*.jsonl") if p.name != "gold.jsonl")
    per = collections.defaultdict(list)
    for p in files:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                per[r["id"]].append(r)
    out = {}
    for pid, rs in per.items():
        labs = {r["is_answer"] for r in rs}
        lab = labs.pop() if len(labs) == 1 else "disputed"
        dates = set()
        for r in rs:
            dates |= {x for x in (_iso(r.get("decision_date")), _iso(r.get("letter_date"))) if x}
        out[pid] = dict(id=pid, is_answer=lab, dates=sorted(dates), n_annotators=len(rs))
    return out


def arms_of(f: dict, theta: float, cfg: J.Config | None = None) -> dict[str, tuple[bool, str | None]]:
    """(promote, chosen date) per arm for one feature row."""
    cfg = J.Config(theta_a=theta, theta_b=cfg.theta_b if cfg else 0.0, is_answer=cfg.is_answer if cfg else "a1")
    a = f["a"][cfg.is_answer]["m_yes"] > theta
    d = J.decide(f, cfg)
    fr = f["free"]
    passing = [d for d, (_c, ok) in f["b"]["b1"]["rule_all"].items() if ok]
    return dict(
        rules_only=(False, None),
        p7=(d["promote"], d["date"]),
        free=(fr["answer"] == "yes" and bool(fr["date"]) and fr["rule"][1], fr["date"]),
        trivial_exact=(f["exact_printed"], None),
        a_and_exact=(a and f["exact_printed"], None),
        oracle_date=(a and bool(passing), None),
    )


_ATT: dict = {}


@functools.lru_cache(maxsize=None)
def _targets(body: str) -> dict:
    return {x["id"]: x for x in targets.load(body)}


def _attainable(key, feats, gold) -> set:
    """Gold-yes rows for which some gold answer date passes the adapters' date rule (cached per feature set)."""
    if key not in _ATT:
        s = set()
        for f in feats:
            g = gold.get(f["id"])
            if g and g["is_answer"] == "yes":
                text = J.excerpt_text(f["body"], f["affair_id"])
                if any(J.date_rule(f["body"], text, d, _targets(f["body"])[f["affair_id"]])[1] for d in g["dates"]):
                    s.add(f["id"])
        _ATT[key] = s
    return _ATT[key]


def score(feats: list[dict], gold: dict, theta: float, cfg: J.Config | None = None) -> dict:
    out = {}
    attain = _attainable(tuple(f["id"] for f in feats), feats, gold)
    yes = {f["id"] for f in feats if (gold.get(f["id"]) or {}).get("is_answer") == "yes"}
    for arm in ("rules_only", "p7", "free", "trivial_exact", "a_and_exact", "oracle_date"):
        c = collections.Counter()
        for f in feats:
            g = gold.get(f["id"])
            if not g:
                c["unlabelled"] += 1
                continue
            prom, date = arms_of(f, theta, cfg)[arm]
            if not prom:
                continue
            c["promoted"] += 1
            c[f"gold_{g['is_answer']}"] += 1
            if g["is_answer"] == "yes":
                c["correct"] += 1
                c["correct_attainable"] += f["id"] in attain
                if date:
                    c["date_hit"] += date in g["dates"]
                    c["date_checked"] += 1
        n = c["promoted"]
        out[arm] = dict(c, precision=round(c["correct"] / n, 3) if n else None,
                        wilson=[round(v, 3) for v in wilson(c["correct"], n)] if n else None,
                        recall_all=round(c["correct"] / len(yes), 3) if yes else None,
                        recall_attainable=round(c["correct_attainable"] / len(attain), 3) if attain else None)
    return dict(theta=theta, gold_yes=len(yes), attainable=len(attain), arms=out,
                promoted_ids=sorted(f["id"] for f in feats if arms_of(f, theta, cfg)["p7"][0]))


THETA_B = [0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0]


def rule_theta(grid: list[dict]) -> float | None:
    ok = [g["theta"] for g in grid if g["arms"]["p7"].get("promoted") and not any(
        g["arms"]["p7"].get(k) for k in ("gold_no", "gold_unclear", "gold_disputed"))]
    return min(ok) if ok else None


def configs(feats: list[dict], gold: dict) -> list[dict]:
    """Dev round 2 (after the labels; DEV ONLY): for each is_answer variant x theta_B, theta_A by the pre-fixed rule; the
    configuration chosen = most correct p7 promotions at its theta_A, ties to a1, then the smaller theta_B."""
    out = []
    for av in sorted({k for f in feats for k in f["a"]}):
        for tb in THETA_B:
            cfg = J.Config(is_answer=av, theta_b=tb)
            grid = [score(feats, gold, t, cfg) for t in GRID]
            ta = rule_theta(grid)
            at = next((g for g in grid if g["theta"] == ta), None)
            p = at["arms"]["p7"] if at else {}
            out.append(dict(is_answer=av, theta_b=tb, theta_a=ta, promoted=p.get("promoted", 0),
                            correct=p.get("correct", 0), precision=p.get("precision"), wilson=p.get("wilson"),
                            recall_all=p.get("recall_all"), recall_attainable=p.get("recall_attainable"),
                            date_hit=p.get("date_hit"), grid=[dict(theta=g["theta"], **{k: g["arms"]["p7"].get(k)
                                                                   for k in ("promoted", "correct", "gold_no",
                                                                             "gold_unclear")}) for g in grid]))
    return out


def table() -> dict:
    feats = [json.loads(x) for x in (dev.WORKDIR / "features.jsonl").read_text().splitlines() if x.strip()]
    gold = load_ann()
    if not gold:
        raise SystemExit("no dev labels in WORK/p7dev/ann/")
    grid = [score(feats, gold, t) for t in GRID]
    ok = [g["theta"] for g in grid if g["arms"]["p7"].get("promoted") and not any(
        g["arms"]["p7"].get(k) for k in ("gold_no", "gold_unclear", "gold_disputed"))]
    chosen = min(ok) if ok else None
    labels = collections.Counter(g["is_answer"] for g in gold.values())
    by_reason = collections.defaultdict(collections.Counter)
    for f in feats:
        g = gold.get(f["id"])
        by_reason[f["reason"]][g["is_answer"] if g else "unlabelled"] += 1
    cf = configs(feats, gold)
    best = sorted(cf, key=lambda c: (-c["correct"], c["is_answer"] != "a1", c["theta_b"]))[0]
    res = dict(configs=cf, chosen=dict((k, best[k]) for k in ("is_answer", "theta_b", "theta_a")),
               chosen_rule="most correct p7 promotions at the pre-fixed theta_A rule; ties: a1, then smaller theta_B",
               labels=dict(labels), by_reason={k: dict(v) for k, v in by_reason.items()}, theta_a=chosen,
               rule="smallest theta on GRID with no promoted dev row gold no/unclear/disputed", grid=grid,
               at_theta=next((g for g in grid if g["theta"] == chosen), None))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dev_table.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    return res
