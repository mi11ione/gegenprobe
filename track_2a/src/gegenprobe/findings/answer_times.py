"""Cross-parliament answer times on the answer document's own date (post hoc, descriptive; no model, no network).

The census median per parliament (results/census/question.json `bodies[].median_days`) measures submission -> OPD's
'answer' event. What that event date is differs by parliament (results/census/date_trust.json): a decision date, a weekly
sitting, a publication or registration date, or in 7 bodies the submission date itself. This module recomputes answer
times for the affairs whose answer a source adapter verified (results/repair/adapters/adapters_*.tsv, `counted=true`,
after the logged re-tierings of repair/adapters/retier.py: results/repair/adapters/retier/retier_r18.json moves Valais's
140 date-window rows to review, so 6,473 counted answers in 27 parliaments) on the date the answer document carries, and
compares the per-parliament ranking with OPD's plain medians. `retiered` reports what the 140 rows contributed before.

Answer date per adapter row (`adapter_date`):
  * `check_decision_date`, the document's own date (header or place-date line) as the adapter read it; it was checked
    against OPD's events (equal, or within the parliament's documented window: docs/adapters.md);
  * else, for rows verified by `date_match=anywhere` (a date printed in the document equals an OPD answer event; mostly
    OCR'd Ticino letters whose title reads 'Risposta del CdS del …'), that OPD answer event date when the affair has
    exactly one; with several answer events the printed date is one of them but which one is not recorded, so the row is
    excluded and counted (`ambiguous_event_date`).
Submission date: the census rule (results/census/interventions.tsv.gz `submitted`: earliest 'Eingereicht'-type event,
else OPD `begin_date`); Bern import-artefact rows have no duration in the census and are excluded. Durations < 0 or
> 3,650 days are excluded and counted, as in the census.

Comparison: parliaments with >= MIN_N adapter durations and a census median (>= 20 dated answers in the census). Three
medians per parliament: OPD plain (census, every answered intervention), OPD on the same affairs (census rule, the affairs
of the adapter sample), adapter date (same affairs). Rankings by Spearman's rho (average ranks for ties). The adapter
sample is the census gap (answers OPD lacks text for), so its type mix and years differ from the whole parliament: the
same-affairs median separates that sample effect from the date-role effect.

    python -m gegenprobe.findings.answer_times   -> results/findings/answer_times.json
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import random
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from ..repair.adapters import retier

ROOT = Path(__file__).resolve().parents[3]
ADAPTERS = ROOT / "results" / "repair" / "adapters"
CENSUS = ROOT / "results" / "census"
OUT = ROOT / "results" / "findings" / "answer_times.json"
MIN_N = 20          # adapter durations per parliament to enter the ranking
MAX_DAYS = 3650     # census rule
PERM = 20000        # permutations for the two-sided p of rho
SEED = 20261011


def _date(s: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def _stat(v: list[float]) -> dict:
    q = statistics.quantiles(v, n=4) if len(v) >= 4 else [None, None, None]
    return dict(n=len(v), median=statistics.median(v) if v else None, q1=q[0], q3=q[2])


def _ranks(x: list[float]) -> list[float]:
    order = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def _pearson(a: list[float], b: list[float]) -> float:
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return num / den if den else float("nan")


def spearman(a: list[float], b: list[float], perm: int = PERM, seed: int = SEED) -> dict:
    ra, rb = _ranks(a), _ranks(b)
    rho = _pearson(ra, rb)
    rng = random.Random(seed)
    rb2 = list(rb)
    hits = 0
    for _ in range(perm):
        rng.shuffle(rb2)
        if abs(_pearson(ra, rb2)) >= abs(rho) - 1e-12:
            hits += 1
    return dict(rho=round(rho, 3), n=len(a), p_permutation=round((hits + 1) / (perm + 1), 4), permutations=perm,
                seed=seed)


def load_rows(apply_retier: bool = True) -> tuple[list[dict], dict]:
    moved = retier.overrides() if apply_retier else {}
    iv = {(r["body"], r["affair_id"]): r
          for r in csv.DictReader(gzip.open(CENSUS / "interventions.tsv.gz", "rt", encoding="utf-8"), delimiter="\t")}
    rows, excl, excl_body, counted_bodies = [], Counter(), defaultdict(Counter), set()
    for f in sorted(ADAPTERS.glob("adapters_*.tsv")):
        for r in csv.DictReader(open(f, encoding="utf-8"), delimiter="\t"):
            if r["counted"] != "true":
                continue
            if moved.get((r["body"], int(r["affair_id"])), {}).get("counted") is False:
                excl["retiered_rows"] += 1
                continue
            excl["counted_rows"] += 1
            counted_bodies.add(r["body"])
            c = iv.get((r["body"], r["affair_id"]))
            if c is None:
                excl["not_in_census"] += 1
                continue
            m = re.search(r"date_match=([^;]*)", r["check_detail"])
            match = m.group(1) if m else ""
            d, src = _date(r["check_decision_date"]), "document_date"
            if d is None:
                evs = [x for x in (_date(s) for s in r["check_answer_event_dates"].split()) if x]
                if match == "anywhere" and len(set(evs)) == 1:
                    d, src = evs[0], "printed_date_equals_single_opd_answer_event"
                else:
                    excl["ambiguous_event_date"] += 1
                    excl_body[r["body"]]["ambiguous_event_date"] += 1
                    continue
            sub = _date(c["submitted"])
            if c["be_load_date"] == "1" or sub is None:
                excl["no_submission_date"] += 1
                excl_body[r["body"]]["no_submission_date"] += 1
                continue
            days = (d - sub).days
            if days < 0 or days > MAX_DAYS:
                k = "negative" if days < 0 else "over_3650_days"
                excl[k] += 1
                excl_body[r["body"]][k] += 1
                continue
            opd = int(c["days_to_answer"]) if c["days_to_answer"] != "" else None
            rows.append(dict(body=r["body"], affair_id=r["affair_id"], type=c["type"], tier=r["tier"], date_source=src,
                             days=days, opd_days=opd, date_trust=c["date_trust"]))
    excl["counted_parliaments"] = len(counted_bodies)
    excl["by_body"] = {b: dict(v) for b, v in sorted(excl_body.items())}
    return rows, dict(excl)


def opd_plain_by_type() -> dict:
    """Census durations (days_to_answer, census rule) per (parliament, type) over every answered intervention."""
    v = defaultdict(list)
    for r in csv.DictReader(gzip.open(CENSUS / "interventions.tsv.gz", "rt", encoding="utf-8"), delimiter="\t"):
        if r["days_to_answer"] != "":
            v[(r["body"], r["type"])].append(int(r["days_to_answer"]))
    return v


def retiered_effect(rows: list[dict]) -> dict:
    """What the re-tiered rows contributed: Valais's durations with and without them (the lists as committed vs after
    retier_r18.json), by type and tier; and Kriens's tiers, which no re-tiering touches."""
    moved = retier.overrides()
    before, _ = load_rows(apply_retier=False)
    gone = [r for r in before if moved.get((r["body"], int(r["affair_id"])), {}).get("counted") is False]
    vs_before = [r for r in before if r["body"] == "VS"]
    vs_after = [r for r in rows if r["body"] == "VS"]
    kr = [r for r in rows if r["body"] == "1059"]
    return dict(
        file=str(retier.OUT.relative_to(ROOT)) if retier.OUT.exists() else None,
        rows_moved=len(moved), durations_moved=len(gone),
        durations_moved_by_body=dict(Counter(r["body"] for r in gone)),
        valais_before=dict(_stat([r["days"] for r in vs_before]), types=dict(Counter(r["type"] for r in vs_before)
                                                                              .most_common())),
        valais_moved=dict(_stat([r["days"] for r in gone if r["body"] == "VS"]),
                          types=dict(Counter(r["type"] for r in gone if r["body"] == "VS").most_common())),
        valais_after=dict(_stat([r["days"] for r in vs_after]), types=dict(Counter(r["type"] for r in vs_after)
                                                                            .most_common()),
                          tiers=dict(Counter(r["tier"] for r in vs_after).most_common()),
                          in_ranking=len(vs_after) >= MIN_N),
        kriens_tiers=dict(Counter(r["tier"] for r in kr).most_common()),
        note="the re-tiered rows (Valais date-window fetch rows) are review rows after retier_r18.json and are not "
             "counted here; valais_before is the finding as it stood on the lists as committed",
    )


def compute() -> dict:
    rows, excl = load_rows()
    q = json.loads((CENSUS / "question.json").read_text(encoding="utf-8"))
    census = {b["body"]: b for b in q["bodies"]}
    trust = {}
    for r in csv.DictReader(gzip.open(CENSUS / "interventions.tsv.gz", "rt", encoding="utf-8"), delimiter="\t"):
        trust.setdefault(r["body"], r["date_trust"])
    by = defaultdict(list)
    for r in rows:
        by[r["body"]].append(r)
    per = {}
    for b, rs in sorted(by.items()):
        cb = census.get(b, {})
        same = [r["opd_days"] for r in rs if r["opd_days"] is not None]
        diffs = [r["days"] - r["opd_days"] for r in rs if r["opd_days"] is not None]
        per[b] = dict(
            name=cb.get("name", b), date_trust=trust.get(b), same_day_share=cb.get("same_day_share"),
            adapter=_stat([r["days"] for r in rs]),
            opd_same_affairs=_stat(same),
            adapter_minus_opd_same_affairs=dict(_stat(diffs), equal_share=round(sum(x == 0 for x in diffs) / len(diffs), 3)
                                                if diffs else None),
            opd_plain=dict(n=cb.get("n_durations"), median=cb.get("median_days"), q1=cb.get("q1_days"),
                           q3=cb.get("q3_days")) if cb else None,
            types=dict(Counter(r["type"] for r in rs).most_common()),
            date_source=dict(Counter(r["date_source"] for r in rs)),
            in_ranking=len(rs) >= MIN_N and bool(cb) and cb.get("median_days") is not None,
        )
    rk = [b for b, v in per.items() if v["in_ranking"]]
    plain = [float(per[b]["opd_plain"]["median"]) for b in rk]
    adap = [float(per[b]["adapter"]["median"]) for b in rk]
    same = [float(per[b]["opd_same_affairs"]["median"]) for b in rk]
    r_plain, r_adap, r_same = _ranks(plain), _ranks(adap), _ranks(same)
    # rank 1 = fastest
    table = []
    for i, b in enumerate(rk):
        v = per[b]
        table.append(dict(body=b, name=v["name"], date_trust=v["date_trust"], n_adapter=v["adapter"]["n"],
                          opd_plain_median=v["opd_plain"]["median"], opd_plain_n=v["opd_plain"]["n"],
                          opd_same_affairs_median=v["opd_same_affairs"]["median"],
                          adapter_median=v["adapter"]["median"], adapter_q1=v["adapter"]["q1"],
                          adapter_q3=v["adapter"]["q3"], rank_opd_plain=r_plain[i], rank_adapter=r_adap[i],
                          rank_opd_same_affairs=r_same[i], rank_move=r_plain[i] - r_adap[i]))
    table.sort(key=lambda t: (t["adapter_median"], t["body"]))
    moves = sorted(table, key=lambda t: (-abs(t["rank_move"]), t["body"]))
    # type-matched: within one intervention type, parliaments with >= MIN_N adapter durations of that type
    plain_t = opd_plain_by_type()
    cells = defaultdict(list)
    for r in rows:
        cells[(r["body"], r["type"])].append(r["days"])
    by_type = {}
    for ty in sorted({t for _, t in cells}):
        bs = sorted(b for (b, t), v in cells.items() if t == ty and len(v) >= MIN_N and len(plain_t[(b, ty)]) >= MIN_N)
        if len(bs) < 3:
            continue
        pm = [float(statistics.median(plain_t[(b, ty)])) for b in bs]
        am = [float(statistics.median(cells[(b, ty)])) for b in bs]
        rp, ra = _ranks(pm), _ranks(am)
        by_type[ty] = dict(
            parliaments=len(bs), spearman_opd_plain_vs_adapter=spearman(pm, am),
            table=sorted([dict(body=b, name=per[b]["name"], n_adapter=len(cells[(b, ty)]), opd_plain_n=len(plain_t[(b, ty)]),
                               opd_plain_median=pm[i], adapter_median=am[i], rank_opd_plain=rp[i], rank_adapter=ra[i],
                               rank_move=rp[i] - ra[i]) for i, b in enumerate(bs)],
                         key=lambda t: (t["adapter_median"], t["body"])))
    no_same_day = [i for i, b in enumerate(rk) if per[b]["date_trust"] != "same_day"]
    pooled_adapter = _stat([r["days"] for r in rows])
    sp = spearman(plain, adap)
    vs_neg = excl.get("by_body", {}).get("VS", {}).get("negative", 0)
    moved = retier.overrides()
    vs_counted = sum(1 for f in [ADAPTERS / "adapters_VS.tsv"] if f.exists()
                     for r in csv.DictReader(open(f, encoding="utf-8"), delimiter="\t") if r["counted"] == "true"
                     and moved.get((r["body"], int(r["affair_id"])), {}).get("counted") is not False)
    headline = dict(
        counted_rows=excl.get("counted_rows"), parliaments=excl.get("counted_parliaments"), durations=len(rows),
        ranked_parliaments=len(rk), rho_opd_plain_vs_adapter=sp["rho"],
        rho_without_same_day=spearman([plain[i] for i in no_same_day], [adap[i] for i in no_same_day])["rho"],
        rho_same_affairs_vs_adapter=spearman(same, adap)["rho"],
        rho_question_type_matched=by_type.get("Question", {}).get("spearman_opd_plain_vs_adapter", {}).get("rho"),
        question_type_parliaments=by_type.get("Question", {}).get("parliaments"),
        vs_motions_submission_after_answer_document=vs_neg, vs_counted_rows=vs_counted,
        opd_date_equals_document_date_ge_90pct=sorted(
            b for b in rk if (per[b]["adapter_minus_opd_same_affairs"] or {}).get("equal_share", 0) >= 0.9),
        opd_date_differs_from_document_date=sorted(
            b for b in rk if (per[b]["adapter_minus_opd_same_affairs"] or {}).get("equal_share", 0) < 0.9),
    )
    return dict(
        headline=headline,
        label="Answer times per parliament on the answer document's own date (adapter-verified) vs OPD's plain medians; "
              "post hoc, descriptive",
        sample=dict(
            source="results/repair/adapters/adapters_*.tsv, counted=true (the three tiers with a date check)",
            counted_rows=excl.get("counted_rows"), parliaments_with_counted_rows=excl.get("counted_parliaments"),
            durations=len(rows), parliaments_with_durations=len(by), excluded={k: v for k, v in excl.items()
                                                                               if k not in ("counted_rows",
                                                                                            "counted_parliaments")},
            date_source=dict(Counter(r["date_source"] for r in rows)),
            tiers=dict(Counter(r["tier"] for r in rows)),
            definition="adapter date = the document's own date as read by the adapter (check_decision_date), else for "
                       "'anywhere' rows the single OPD answer event date the printed date equals; submission = census "
                       "rule (interventions.tsv.gz `submitted`); durations < 0 or > 3,650 days excluded",
        ),
        min_n=MIN_N,
        pooled_adapter=pooled_adapter,
        pooled_opd_same_affairs=_stat([r["opd_days"] for r in rows if r["opd_days"] is not None]),
        ranking=dict(
            parliaments=len(rk),
            spearman_opd_plain_vs_adapter=sp,
            spearman_opd_plain_vs_adapter_without_same_day=spearman([plain[i] for i in no_same_day],
                                                                    [adap[i] for i in no_same_day]),
            spearman_opd_same_affairs_vs_adapter=spearman(same, adap),
            spearman_opd_plain_vs_opd_same_affairs=spearman(plain, same),
            note="rank 1 = shortest median; rank_move = rank on OPD's plain median minus rank on the adapter date "
                 "(negative = the parliament looks faster on OPD's date than on its answer documents)",
            table=table,
            biggest_moves=[dict(body=t["body"], name=t["name"], rank_opd_plain=t["rank_opd_plain"],
                                rank_adapter=t["rank_adapter"], opd_plain_median=t["opd_plain_median"],
                                adapter_median=t["adapter_median"], date_trust=t["date_trust"]) for t in moves[:6]],
        ),
        type_matched=dict(
            note="within one intervention type: OPD plain = census durations of that type in that parliament (every "
                 "answered intervention); adapter = the adapter sample of that type; types with >= 3 parliaments (rho on "
                 "3 parliaments is shown but says little)",
            by_type=by_type),
        per_parliament=per,
        retiered=retiered_effect(rows),
        caveat="The adapter sample is the census gap (answers OPD holds without text, or not at all), not every answer of "
               "a parliament, and its type mix differs (per_parliament.types). The document date is the government's "
               "decision or letter date in most parliaments (Neuchâtel: the date the answer was transmitted to the Grand "
               "Conseil). Medians mix intervention types; compare a parliament with itself, or within one type.",
    )


def main() -> dict:
    r = compute()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return r


if __name__ == "__main__":
    r = main()
    s = r["sample"]
    print("durations", s["durations"], "parliaments", s["parliaments_with_durations"], "excluded", s["excluded"])
    rk = r["ranking"]
    print("ranked", rk["parliaments"], "rho plain vs adapter", rk["spearman_opd_plain_vs_adapter"],
          "| w/o same-day", rk["spearman_opd_plain_vs_adapter_without_same_day"],
          "| same-affairs vs adapter", rk["spearman_opd_same_affairs_vs_adapter"])
    for t in rk["table"]:
        print(f"{t['body']:5s} {t['name'][:22]:22s} {t['date_trust']:11s} n={t['n_adapter']:5d} "
              f"plain {t['opd_plain_median']!s:>6} same {t['opd_same_affairs_median']!s:>6} "
              f"adapter {t['adapter_median']!s:>6} rank {t['rank_opd_plain']:>4} -> {t['rank_adapter']:>4}")
