"""EXPLORATORY (round 16, not registered in PREREG10): a cross-vendor check of the P10 gold. Qwen-SEA-LION-v4-32B-IT
(AI Singapore; another model family, never Apertus, never Anthropic) labels the 40 P10 packets blind, exactly as the P8
check (eval/p8/qwen9.py) did: the same model, the same gateway path and settings (temperature 0, 1,500 output tokens,
served model checked on every call), the same instructions for the keys P10 labels (question_doc, answer_doc, people:
P8's item text, verbatim, cut before its date keys, so the role definitions are word for word the P8 guide's that
GUIDE_P10.md reuses) and the same packet view (the member text's first 14,000 characters, the answer's first 8,000 and
last 3,000). Quotes are not asked for (Qwen's quotes failed the verbatim check on P5). It changes no gold label and no
decision.

    PYTHONPATH=src:. .venv/bin/python -m eval.p10.qwen10 run     -> WORK/p10/ann/qwen.jsonl (raw replies; tag 2a-p10-qwen,
                                                                    cap USD 1.0), data/p10/annotations/QWEN.jsonl (the
                                                                    parsed labels: names, kinds, roles; no text), and
                                                                    results/p10/p10_qwen_run.json (spend, served model)
    PYTHONPATH=src:. .venv/bin/python -m eval.p10.qwen10 score   -> results/p10/p10_qwen_check.json (no model call; from
                                                                    committed files only)

`score` reports, against the merged gold (data/p10/p10_gold.jsonl) and, for reference, A1 vs A2: pair F1 ((name, role)
pairs matched one-to-one by the frozen eval/p10/score.py `match`), name F1 (names only), packets whose two lists agree
(eval/p10/annotate.py `agree`), and Cohen's kappa of the role on the names both lists print. Then the registered
decisions (eval/p10/score.py `hypotheses`, frozen: same arms, seed and resamples) recomputed on the committed arm outputs
with the gold replaced:
  qwen_replaces_A2   the registered merge with Qwen in A2's place: A1's list where A1 and Qwen agree; where they do not,
                     A3's tie-break where A3 labelled that packet, else (no tie-break exists) A1's list
                     (`unresolved_to_A1`) or Qwen's (`unresolved_to_qwen`), both reported;
  qwen_as_gold       Qwen's lists as the gold;
  consensus          only the packets where Qwen's list agrees with the merged gold.
"""

from __future__ import annotations

import collections
import json
import sys

from eval.p8 import common as C8
from eval.p8 import qwen9
from eval.p10 import common as C
from gegenprobe.stats import cohen_kappa

LABEL = ("EXPLORATORY (round 16; not registered in PREREG10): cross-vendor check of the P10 gold with Qwen-SEA-LION; "
         "changes no gold label and no decision")
QWEN = C8.QWEN  # aisingapore/Qwen-SEA-LION-v4-32B-IT, the model of every earlier Qwen check
TAG = "2a-p10-qwen"
CAP_USD = 1.0
MAX_TOKENS = qwen9.MAX_TOKENS  # 1500
RAW = C.ANN / "qwen.jsonl"  # WORK: raw replies (may quote document text; never committed)
LABELS = C.ANN_COMMITTED / "QWEN.jsonl"  # committed: parsed labels without text
RUN = C.R10 / "p10_qwen_run.json"
OUT = C.R10 / "p10_qwen_check.json"

_CUT = '- "dates":'
ITEM = qwen9.ITEM[:qwen9.ITEM.index(_CUT)] + '- "notes": ""\n\n' + qwen9.ITEM[qwen9.ITEM.index("DOCUMENTS (extracted"):]
ROLE_KEYS = ("name", "kind", "role")


def view(pid: str) -> str:
    """The P8 check's view (eval/p8/qwen9.py `view`) of a P10 packet; P10 packets carry no date list."""
    from eval.p10 import packets as P

    pages = P.packet_pages(pid)
    q = "\n".join(pages["question"])
    a = "\n".join(pages["answer"])
    q = q if len(q) <= 14000 else q[:14000] + "\n[...]"
    a = a if len(a) <= 11000 else a[:8000] + "\n[...]\n" + a[-3000:]
    return f"=== DOCUMENT question ===\n{q}\n=== DOCUMENT answer ===\n{a}\n"


def clean(pid: str, lab: dict | None) -> dict:
    """The committed form of a Qwen label: the closed-vocabulary keys and each person's name, kind and role."""
    if not isinstance(lab, dict):
        return dict(id=pid, valid=False, people=[])
    people = []
    for p in lab.get("people") or []:
        if isinstance(p, dict) and isinstance(p.get("name"), str) and p.get("name").strip():
            people.append({k: p.get(k) for k in ROLE_KEYS})
    return dict(id=pid, valid=True, question_doc=lab.get("question_doc"), answer_doc=lab.get("answer_doc"),
                people=people)


def run() -> dict:
    from eval.p10 import packets as P
    from gegenprobe.devpaths import import_gw

    gw = import_gw("the P10 Qwen check")
    key = P.load_key()
    RAW.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(x)["id"] for x in RAW.read_text().splitlines() if x.strip()} if RAW.exists() else set()
    served, usd, calls = collections.Counter(), 0.0, 0
    with open(RAW, "a", encoding="utf-8") as f:
        for pid in sorted(key):
            if pid in done:
                continue
            choice, meta = gw.chat([dict(role="user", content=ITEM.format(text=view(pid)))], model=QWEN,
                                   max_tokens=MAX_TOKENS, temperature=0.0, tag=TAG, tag_cap_usd=CAP_USD, full=True)
            m = (meta.get("resp") or {}).get("model")
            if not m or "qwen-sea-lion" not in m.lower():
                raise RuntimeError(f"{pid}: served {m!r}, expected {QWEN}")
            served[m] += 1
            calls += 1
            reply = (choice.get("message") or {}).get("content") or ""
            f.write(json.dumps(dict(id=pid, label=qwen9.parse(reply), model=m, raw=reply[:4000]), ensure_ascii=False)
                    + "\n")
            f.flush()
            usd += 0.0 if meta.get("cached") else meta.get("usd", 0.0)
    rows = {r["id"]: r for r in C._jsonl(RAW)}
    LABELS.parent.mkdir(parents=True, exist_ok=True)
    with open(LABELS, "w", encoding="utf-8") as f:
        for pid in sorted(rows):
            f.write(json.dumps(clean(pid, rows[pid].get("label")), ensure_ascii=False) + "\n")
    models = collections.Counter(r.get("model") for r in rows.values())
    prev = json.loads(RUN.read_text()) if RUN.exists() else {}
    res = dict(label=LABEL, model=QWEN, tag=TAG, cap_usd=CAP_USD, max_tokens=MAX_TOKENS, temperature=0.0,
               usd=round(prev.get("usd", 0.0) + usd, 4), calls_this_run=calls, packets=len(rows),
               served=dict(models), command="PYTHONPATH=src:. .venv/bin/python -m eval.p10.qwen10 run",
               note="spend summed from the gateway's per-call report (cached replays cost 0); served model checked on "
                    "every call")
    C.R10.mkdir(parents=True, exist_ok=True)
    RUN.write_text(json.dumps(res, indent=1) + "\n")
    return res


# ------------------------------------------------------------------------------------------------ score (no model)
def _pairs(lab: dict) -> list[tuple[str, str]]:
    return [(p["name"], p["role"]) for p in lab.get("people") or []]


def name_pairs(a: list[tuple[str, str]], b: list[tuple[str, str]]) -> list[tuple[int, int]]:
    """(index in a, index in b) of the names matched one-to-one: eval/p10/score.py `match` without the role, with both
    indices kept (greedy in a's printed order; `convert.roles.same_person`)."""
    from gegenprobe.convert import roles as R

    used: list[int] = []
    out = []
    for i, (an, _) in enumerate(a):
        for j, (bn, _) in enumerate(b):
            if j not in used and R.same_person(an, bn):
                used.append(j)
                out.append((i, j))
                break
    return out


def compare(x: dict[str, dict], y: dict[str, dict], ids: list[str]) -> dict:
    """Agreement of two label sets on `ids`: pair F1, name F1, packets agreeing, role kappa on co-printed names."""
    from eval.p10.annotate import agree
    from eval.p10.score import match

    n = m = nn = mn = same = 0
    rx, ry = [], []
    for pid in ids:
        a, b = _pairs(x.get(pid) or {}), _pairs(y.get(pid) or {})
        n += len(a) + len(b)
        m += 2 * match(a, b)[0]
        nn += len(a) + len(b)
        mn += 2 * match(a, b, with_role=False)[0]
        same += agree(dict(people=[dict(name=s, role=r) for s, r in a]), dict(people=[dict(name=s, role=r) for s, r in b]))
        for i, j in name_pairs(a, b):  # roles of the names matched one-to-one (names only, match's greedy rule)
            rx.append(a[i][1])
            ry.append(b[j][1])
    return dict(packets=len(ids), packets_agreeing=same, pair_f1=round(m / n, 4) if n else None,
                name_f1=round(mn / nn, 4) if nn else None, names_both=len(rx),
                role_agree_on_names_both=sum(p == q for p, q in zip(rx, ry)),
                role_kappa_on_names_both=round(cohen_kappa(rx, ry), 3) if rx else None)


def _committed(name: str) -> dict[str, dict]:
    return {r["id"]: r for r in C._jsonl(C.ANN_COMMITTED / name)}


def rows_with_gold(gold_people: dict[str, list[tuple[str, str]]]) -> list[dict]:
    """The committed arm rows (results/p10/p10_arms.jsonl) re-scored against another gold, as eval/p10/arms.py `join`."""
    from eval.p10 import score as S

    cands = {r["affair_id"]: r for r in C._jsonl(C.CANDS10)}
    out = []
    for r in C._jsonl(C.ARMS):
        if r["id"] not in gold_people:
            continue
        gp = gold_people[r["id"]]
        pred = {k: [tuple(p) for p in v] for k, v in r["pred"].items()}
        out.append(dict(r, gold=gp, arms={k: S.affair_row(v, gp) for k, v in pred.items()},
                        cand=S.cand_row(cands[r["affair_id"]]["candidates"], gp)))
    return out


def decisions(gold_people: dict[str, list[tuple[str, str]]]) -> dict:
    from eval.p10 import score as S

    prim = [r for r in rows_with_gold(gold_people) if r["cell"] == "primary"]
    h = S.hypotheses(prim, C.SEED_BOOT, C.N_BOOT)
    tests = h.get("tests") or {}
    return dict(n_affairs=len(prim), gold_pairs=sum(len(r["gold"]) for r in prim),
                pointer=S.pooled(prim, "pointer"), rules=S.pooled(prim, "rules"),
                verdicts={k: tests[k].get("verdict") for k in S.FAMILY if k in tests},
                p_holm={k: tests[k].get("p_holm") for k in S.FAMILY if k in tests},
                observed={k: tests[k].get("observed") for k in S.FAMILY if k in tests})


def score() -> dict:
    from eval.p10.annotate import agree

    gold = {g["id"]: g for g in C._jsonl(C.GOLD)}
    a1, a2, a3 = _committed("A1.jsonl"), _committed("A2.jsonl"), _committed("A3.jsonl")
    qw = _committed("QWEN.jsonl")
    ids = sorted(gold)
    invalid = [pid for pid in ids if not (qw.get(pid) or {}).get("valid")]
    agreement = dict(qwen_vs_gold=compare(qw, gold, ids), qwen_vs_A1=compare(qw, a1, ids),
                     qwen_vs_A2=compare(qw, a2, ids), A1_vs_A2=compare(a1, a2, ids), A1_vs_gold=compare(a1, gold, ids),
                     A2_vs_gold=compare(a2, gold, ids))
    by_stratum = {s: compare(qw, gold, [i for i in ids if gold[i]["stratum"] == s])
                  for s in sorted({g["stratum"] for g in gold.values()})}

    def lab(d, pid):
        return dict(people=[dict(name=n, role=r) for n, r in _pairs(d.get(pid) or {})])

    registered = {pid: _pairs(gold[pid]) for pid in ids}
    rep_a1, rep_q, sources = {}, {}, collections.Counter()
    for pid in ids:
        if agree(lab(a1, pid), lab(qw, pid)):
            rep_a1[pid] = rep_q[pid] = _pairs(a1[pid])
            sources["A1=Qwen"] += 1
        elif pid in a3:
            rep_a1[pid] = rep_q[pid] = _pairs(a3[pid])
            sources["A3 (tie-break exists)"] += 1
        else:
            rep_a1[pid], rep_q[pid] = _pairs(a1[pid]), _pairs(qw.get(pid) or {})
            sources["no tie-break: A1 or Qwen"] += 1
    consensus = {pid: registered[pid] for pid in ids if agree(lab(gold, pid), lab(qw, pid))}
    scen = dict(registered_gold=decisions(registered),
                qwen_replaces_A2_unresolved_to_A1=decisions(rep_a1),
                qwen_replaces_A2_unresolved_to_qwen=decisions(rep_q),
                qwen_as_gold=decisions({pid: _pairs(qw.get(pid) or {}) for pid in ids}),
                consensus=decisions(consensus))
    base = scen["registered_gold"]["verdicts"]
    # a scenario too small for the registered stop rule (>= 30 affairs and >= 60 gold pairs) reports every hypothesis
    # inconclusive: that is the stop rule, not a reversed verdict, so it is listed apart
    underpowered = sorted(k for k, s in scen.items() if any(str(v).startswith("inconclusive") for v in s["verdicts"].values()))
    changes = {k: sorted(h for h, v in s["verdicts"].items() if v != base.get(h)) for k, s in scen.items()
               if k != "registered_gold" and k not in underpowered}
    out = dict(label=LABEL, model=QWEN, tag=TAG, n_packets=len(ids), invalid_or_missing=invalid,
               agreement=agreement, qwen_vs_gold_by_stratum=by_stratum,
               merge_with_qwen_in_place_of_A2=dict(sources),
               decisions=scen, verdict_changes=changes,
               any_registered_verdict_changes={k: bool(v) for k, v in changes.items()},
               underpowered_by_the_registered_stop_rule={
                   k: dict(n_affairs=scen[k]["n_affairs"], gold_pairs=scen[k]["gold_pairs"],
                           verdicts_if_the_stop_rule_were_ignored={
                               h: ("confirmed" if p is not None and p <= 0.05 else "not confirmed")
                               for h, p in scen[k]["p_holm"].items()}) for k in underpowered},
               note="Qwen's labels change no gold label and no decision; the registered P10 result stays the one in "
                    "results/p10/p10_scores.json")
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "run":
        print(json.dumps(run(), indent=1))
    elif cmd == "score":
        r = score()
        print(json.dumps(dict(agreement=r["agreement"]["qwen_vs_gold"], A1_vs_A2=r["agreement"]["A1_vs_A2"],
                              verdict_changes=r["verdict_changes"]), indent=1))
    else:
        print(__doc__)
        sys.exit(0 if cmd in ("", "-h", "--help") else 2)
