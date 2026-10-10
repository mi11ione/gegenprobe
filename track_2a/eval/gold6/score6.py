"""P5 scoring (definitions registered in eval/prereg6/PREREG6.md, "Metrics").

Spans are compared as character intervals of one document (global offsets: pages joined with "\\n"); IoU = |A∩B| / |A∪B|.
A predicted span "matches" a gold span when both lie in the same document and IoU >= 0.5.

  questions      per gold question n: matched by the predicted question n (IoU >= 0.5).  recall = matched / gold
                 questions; precision = matched / predicted questions; count_exact = affairs whose predicted question
                 count equals the gold count.
  qa_pairs       (headline) per gold question n whose gold answer span is non-null: correct when the predicted answer n
                 is non-null and matches.  recall = correct / gold non-null answers; precision = correct / predicted
                 non-null answers (every predicted non-null answer counts, including answers to questions gold does not
                 have); false_span = predicted non-null answers where gold has the question with a null answer.
  submitter      per affair: correct when both are null, or both name a person and the gold surname (last token, folded)
                 is a token of the predicted name or the predicted last token is a token of the gold name.
  co_signatories micro precision / recall over names with the same name rule.
  recommendation per affair: exact label (accept, reject, partial, convert, none, not_applicable; an abstention is wrong).
  reasoning      per affair: correct when both are null, or both are spans that match; mean IoU reported.
"""

from __future__ import annotations

import unicodedata

from gegenprobe.stats import wilson


def fold(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(ch)).lower()


def iou(a: dict | None, b: dict | None) -> float:
    if not a or not b or a["doc"] != b["doc"]:
        return 0.0
    inter = max(0, min(a["g_end"], b["g_end"]) - max(a["g_start"], b["g_start"]))
    union = max(a["g_end"], b["g_end"]) - min(a["g_start"], b["g_start"])
    return inter / union if union > 0 else 0.0


def toks(n: str) -> list[str]:
    return [t.strip(".,;:()") for t in fold(n).split() if t.strip(".,;:()")]


def name_match(g: str | None, p: str | None) -> bool:
    if not g or not p:
        return False
    gt, pt = toks(g), toks(p)
    if not gt or not pt:
        return False
    return gt[-1] in pt or pt[-1] in gt


def gold_view(lab: dict) -> dict:
    sub = next((x for x in lab["people"] if x["role"] == "submitter"), None)
    return dict(
        questions=[dict(n=q["n"], span=q["span"]) for q in lab["questions"]],
        answers=[dict(n=x["n"], span=x["span"]) for x in lab["answers"]],
        submitter=sub["name"] if sub else None,
        co_signatories=[x["name"] for x in lab["people"] if x["role"] == "co_signatory"],
        recommendation=lab["recommendation"],
        reasoning=lab["reasoning"],
        question_style=lab["question_style"],
        answer_style=lab["answer_style"],
    )


def _ci(k: int, n: int) -> dict:
    lo, hi = wilson(k, n) if n else (None, None)
    return dict(k=k, n=n, rate=(k / n if n else None), ci95=[lo, hi])


def score(preds: dict, gold: dict) -> dict:
    """preds, gold: affair_id -> view. Returns per-field counts with Wilson 95% CIs."""
    ids = sorted(gold)
    qm = qg = qp = cnt = 0
    pc = pg = pp = fs = 0
    sub_ok = co_tp = co_g = co_p = rec_ok = rs_ok = 0
    ious = []
    per = {}
    for i in ids:
        g, p = gold[i], preds.get(i) or {}
        pq = {x["n"]: x["span"] for x in p.get("questions") or []}
        pa = {x["n"]: x["span"] for x in p.get("answers") or []}
        qg += len(g["questions"])
        qp += len(pq)
        cnt += len(pq) == len(g["questions"])
        m_q = sum(iou(x["span"], pq.get(x["n"])) >= 0.5 for x in g["questions"])
        qm += m_q
        gnn = {x["n"]: x["span"] for x in g["answers"] if x["span"] is not None}
        gnull = {x["n"] for x in g["answers"] if x["span"] is None}
        pnn = {n: s for n, s in pa.items() if s is not None}
        c = sum(iou(s, pnn.get(n)) >= 0.5 for n, s in gnn.items())
        pc += c
        pg += len(gnn)
        pp += len(pnn)
        fs += sum(n in gnull for n in pnn)
        ps = p.get("submitter")
        psn = ps["name"] if isinstance(ps, dict) else ps
        s_ok = (g["submitter"] is None and not psn) or name_match(g["submitter"], psn)
        sub_ok += s_ok
        pcs = [x["name"] if isinstance(x, dict) else x for x in p.get("co_signatories") or []]
        tp = sum(any(name_match(gn, pn) for pn in pcs) for gn in g["co_signatories"])
        co_tp += tp
        co_g += len(g["co_signatories"])
        co_p += len(pcs)
        r_ok = p.get("recommendation") == g["recommendation"]
        rec_ok += r_ok
        rv = iou(g["reasoning"], p.get("reasoning"))
        rs = (g["reasoning"] is None and not p.get("reasoning")) or rv >= 0.5
        rs_ok += rs
        if g["reasoning"]:
            ious.append(rv)
        per[i] = dict(questions=f"{m_q}/{len(g['questions'])} (pred {len(pq)})", qa=f"{c}/{len(gnn)} (pred {len(pnn)})",
                      submitter=s_ok, recommendation=[g["recommendation"], p.get("recommendation")], reasoning=round(rv, 3))
    n = len(ids)
    return dict(
        n_affairs=n,
        questions=dict(recall=_ci(qm, qg), precision=_ci(qm, qp), count_exact=_ci(cnt, n)),
        qa_pairs=dict(recall=_ci(pc, pg), precision=_ci(pc, pp), false_span_on_gold_null=fs,
                      gold_null_answers=sum(sum(x["span"] is None for x in gold[i]["answers"]) for i in ids)),
        submitter=_ci(sub_ok, n),
        co_signatories=dict(recall=_ci(co_tp, co_g), precision=_ci(sum(
            any(name_match(gn, pn) for gn in gold[i]["co_signatories"])
            for i in ids
            for pn in [x["name"] if isinstance(x, dict) else x for x in (preds.get(i) or {}).get("co_signatories") or []]
        ), co_p)),
        recommendation=_ci(rec_ok, n),
        reasoning=dict(match=_ci(rs_ok, n), mean_iou=(sum(ious) / len(ious) if ious else None)),
        per_affair=per,
    )
