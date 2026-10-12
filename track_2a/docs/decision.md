# Gegenprobe at a glance: what to decide

For OPD's management and a cantonal chancellery. Details: [operator sheet](runbook.md#operator-sheet),
[licences](licences.md). Every number on this page is checked by `make claims`.

**What runs.** A nightly job on a Linux server, or inside OPD next to its export job: it recounts the answers that lack
text in OPD and re-checks the Bern repairs against OPD's exports. Rules write the values; no model runs by default.
Apertus (the optional review mode) proposes values, and a reviewer confirms them.

**What leaves the machine.**

- Default: no document text. The job reads public sources (OPD's exports, the parliaments' sites) and sends nothing on.
- Review mode with the local Apertus 8B: no document text.
- Review mode through the Public AI gateway: the text of each document the rules leave open goes to a US nonprofit that
  offers no processing agreement, a disclosure abroad under nDSG Art. 16. A body that may not do this goes without two
  components, the review-queue verifier and the role reader; the rules and the 8B's date suggestions stay.

**What it costs.**

| route | cost |
|---|---|
| rules over the 902,754 documents in OPD's export | about 0.5 CPU-hours |
| review mode, Public AI (70B) | USD 0.59 per 1,000 residue documents, at its list price |
| review mode, local 8B | 49.9 machine-hours per 1,000 residue documents (a 4-vCPU machine) |
| review mode, Swiss-hosted 70B | an estimated 1.64 GPU-hours per 1,000 residue documents (assumed hardware and throughput) |

**OPD's one open decision.** Relinking the 2,421 Bern answers already in OPD changes each document's identifier (its
hash) unless OPD keeps the old one. OPD picks the rule; the plan carries both values. Meanwhile 3,621 repairs need
neither a decision nor a fetch.

**Who reviews what.**

| who | reviews |
|---|---|
| the data engineer who runs the nightly job | its alerts and exit codes; review mode's refits when the model build changes |
| OPD's reviewer of the repair lists | the 38 Bern relinks and 173 begin-date corrections set aside for review; every Apertus suggestion before it is written |

**Maturity.**

| component | maturity |
|---|---|
| census and Bern repair lists | ready to apply (relinks: after the hash decision) |
| nightly job | ready to deploy |
| source-adapter lists | audited |
| rules-only converter | tested prototype |
| review mode (Apertus) | feasibility study |
| schema, both versions | drafts for the eCH group |
