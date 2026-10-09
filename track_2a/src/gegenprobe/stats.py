"""Small, dependency-free statistics used across the report."""
import math


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k/n, as fractions in [0, 1]."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def wilson_pct(k: int, n: int) -> tuple[float, float]:
    lo, hi = wilson(k, n)
    return (round(100 * lo, 1), round(100 * hi, 1))


def auroc(pos: list[float], neg: list[float]) -> float:
    """P(score_pos > score_neg) with ties counted half (Mann-Whitney)."""
    if not pos or not neg:
        return float("nan")
    s = 0.0
    for p in pos:
        for q in neg:
            s += 1.0 if p > q else 0.5 if p == q else 0.0
    return s / (len(pos) * len(neg))


def logsumexp(xs: list[float]) -> float:
    if not xs:
        return float("-inf")
    m = max(xs)
    return m + math.log(sum(math.exp(x - m) for x in xs))


def cohen_kappa(a: list, b: list) -> float:
    assert len(a) == len(b) and a
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    labels = set(a) | set(b)
    pe = sum((a.count(lab) / n) * (b.count(lab) / n) for lab in labels)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)
