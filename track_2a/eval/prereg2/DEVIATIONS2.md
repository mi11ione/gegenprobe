# Deviations from PREREG2 (unseen parliaments)

PREREG2.md and LOCK2 are frozen (commit 3dde418, before the P2 labels in 2e4a9d6). Later changes and post-hoc analyses:

## D2-1 Unit of the primary test (found by the round-2 jury)
P2-H2 is registered as an exact McNemar test on documents (22 pointer-only vs 0 rules-only, p = 4.8 × 10⁻⁷). The 29
gold-value documents are nested in 7 parliaments (VD alone contributes 8), so documents are not independent. POST-HOC, at
the parliament level: 6 parliaments favour the pointer, 0 favour the rules, 1 has no discordant pair; two-sided sign test
p = 0.031, and an exact cluster permutation test (all 64 joint flips of a parliament's documents) p = 0.031, the smallest
value 6 clusters allow (`results/eval2/body_level.json`, `eval/body_level.py`). The registered result stands; the honest
headline p-value is the parliament-level one.

## D2-2 Trivial baselines (POST-HOC, asked for by the round-2 jury)
On P2, "latest printed date" finds 22/29 answer dates but also puts a date on 31/33 answerless documents (exact 24/62);
gated by OPD's document type (null for member texts) it is exact on 44/62. The pointer is exact on 53/62 (24/29 dates,
4/33 answerless) (`results/eval/baselines_dates.json`). The registered comparison was pointer vs rules; these baselines
show the margin over the strongest one-line alternative (53 vs 44).

## D2-3 Naive arms
PREREG2 lists `naive_null`; the frozen runner (`eval.arms.run`, arm `naive`) also produced `naive_plain` on the same
documents. Both are reported; no decision is attached to either.
