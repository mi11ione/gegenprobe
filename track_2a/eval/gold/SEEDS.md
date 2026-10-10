# Gold-set sampling seeds (written before any draw)

Written 2026-10-09T18:07:58Z by the converter workstream (Claude Code agent), before eval/gold/sample.py drew anything.

| split | seed | purpose |
|---|---|---|
| dev | 20261009 | rule development and θ fitting; may be read freely |
| heldout | 20261010 | frozen evaluation; drawn after dev, disjoint from dev documents and dev affairs; not read before the LOCK |

Draw order: dev first, then heldout excluding every dev doc id, dev affair id, and every affair/doc used in the spikes
(round7/null_items, round8/ptr_items + opd_ctrl, recovery/audit_docs, bilanz docs).

## Deviation log
- 2026-10-09 ~18:40Z: the dev split was drawn twice. Draw v1 (Zürich city PDFs rejected by a too-strict "%PDF" check at byte 0;
  URLs with raw spaces failed) was partly read for rule development; draw v2 added St. Gallen city (3203) to `de_commune`
  and fixed both fetch issues. Both draws are dev: `data/gold/dev_docs.jsonl` holds the union (field `draw`), and every
  doc in it is excluded from the held-out split. After v2 the sampler's RNG became one independent stream per stratum
  (seed string "<seed>:<cell>:<dtype>") so that changing one cell cannot reshuffle another. The held-out split was drawn
  only after this change.
- 2026-10-09 ~19:20Z: the first held-out draw put two documents of one affair into different strata (the one-document-per-affair
  rule was enforced per stratum only). Fixed to be split-wide and the held-out split was redrawn (same seed) before any label
  existed and before any held-out text was read; only metadata (cell, type, token estimate) of the first draw was looked at.

## Correction (appended 10 Oct 2026, POST-HOC; `eval/prereg/DEVIATIONS.md` D13)
The two times above are wrong; the lines are kept as written. Local logs (`.work/sample_*.log` mtimes) give: dev draw v1
18:11:44Z, dev draw v2 18:18:49Z, held-out draw 1 18:35:06Z, held-out redraw 18:41:14Z. The held-out sample was committed
at 18:42:21Z (`da26116`, 20:42:21 CEST) in the same commit as the rules, so P1 is held out by protocol, not by commit
order (D12). The order of events described above is correct.
