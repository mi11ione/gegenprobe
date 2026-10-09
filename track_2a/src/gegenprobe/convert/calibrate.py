"""Per-build abstention threshold θ for the closed-set pointer (port of spikes/inversions/f2_abstain.py).

Rule: abstain (null) iff margin > θ, margin = lp(null) − logsumexp(lp(date candidates)). Positive class = no value in the doc.
θ is fitted to maximise accuracy and taken as the midpoint of the widest contiguous accuracy-optimal interval of candidate
thresholds. It is per build × per prompt: it transferred only across near-identical checkpoints in F2.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from ..stats import auroc, wilson


def _cands(m: list[float]) -> list[float]:
    v = sorted(set(m))
    return [v[0] - 1] + [(a + b) / 2 for a, b in zip(v, v[1:])] + [v[-1] + 1]


def fit_theta(m: list[float], y: list[bool]) -> tuple[float, float]:
    """Return (θ, in-sample accuracy). y[i] True = should abstain."""
    assert len(m) == len(y) and m
    cands = _cands(m)
    acc = [sum((mi > t) == yi for mi, yi in zip(m, y)) / len(m) for t in cands]
    best_acc = max(acc)
    best = [i for i, a in enumerate(acc) if a == best_acc]
    runs, cur = [], [best[0]]
    for b in best[1:]:
        if b == cur[-1] + 1:
            cur.append(b)
        else:
            runs.append(cur)
            cur = [b]
    runs.append(cur)
    r = max(runs, key=len)  # first longest run, as in the spike (numpy max over list keeps the first)
    lo, hi = cands[r[0]], cands[r[-1]]
    return ((lo + hi) / 2 if len(r) > 1 else cands[r[0]]), best_acc


def loo(m: list[float], y: list[bool]) -> dict:
    pred = []
    for i in range(len(m)):
        t, _ = fit_theta(m[:i] + m[i + 1 :], y[:i] + y[i + 1 :])
        pred.append(m[i] > t)
    k = sum(p == yi for p, yi in zip(pred, y))
    return dict(
        acc=k / len(m),
        correct=k,
        n=len(m),
        abstain_correct=sum(p and yi for p, yi in zip(pred, y)),
        n_pos=sum(y),
        answer_correct=sum((not p) and (not yi) for p, yi in zip(pred, y)),
        n_neg=len(y) - sum(y),
        wilson95=list(wilson(k, len(m))),
    )


@dataclass
class Calibration:
    build: str
    prompt_id: str
    theta: float
    acc_in_sample: float
    auroc: float
    gap: float  # min(positive margins) − max(negative margins); > 0 means perfectly separable
    loo: dict
    n_pos: int
    n_neg: int
    fitted_on: list  # doc ids (dev only)

    def save(self, path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1, ensure_ascii=False))


def calibrate(build: str, prompt_id: str, ids: list, m: list[float], y: list[bool]) -> Calibration:
    th, acc = fit_theta(m, y)
    pos = [a for a, b in zip(m, y) if b]
    neg = [a for a, b in zip(m, y) if not b]
    return Calibration(
        build=build,
        prompt_id=prompt_id,
        theta=th,
        acc_in_sample=acc,
        auroc=auroc(pos, neg),
        gap=(min(pos) - max(neg)) if pos and neg else float("nan"),
        loo=loo(m, y),
        n_pos=len(pos),
        n_neg=len(neg),
        fitted_on=list(ids),
    )


def transfer(theta: float, m: list[float], y: list[bool]) -> dict:
    pred = [mi > theta for mi in m]
    return dict(
        theta=theta,
        acc=sum(p == yi for p, yi in zip(pred, y)) / len(m),
        abstain=f"{sum(p and yi for p, yi in zip(pred, y))}/{sum(y)}",
        answer=f"{sum((not p) and (not yi) for p, yi in zip(pred, y))}/{len(y) - sum(y)}",
    )
