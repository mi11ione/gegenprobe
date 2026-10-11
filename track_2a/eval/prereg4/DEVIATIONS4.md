# Deviations from PREREG4 (virtual affairs)

PREREG4.md and LOCK4 are frozen (commit 922218d). Every later change or defect is listed here with its effect.

## D4-1 Header text of the locked file
The first line of the locked `PREREG4.md` still reads "(DRAFT, not locked)". It was written as a draft and frozen by LOCK4
at commit 922218d without its title line being updated; the hash in LOCK4 covers exactly that text. Status: frozen at 922218d.
The text below the title is the registration.

## D4-2 lock4.py internals
`eval/prereg4/lock4.py` was adapted from `eval/prereg2/lock2.py` and keeps its variable names (`P2_FILES`, `LOCK2`); the
file list and output path are P4's (19 files + the 33 P1 frozen files, `eval/prereg4/LOCK4`). Cosmetic, no effect.

## D4-3 θ = 0 for both pointers
Declared in PREREG4 before any P4 label; its justification cites P1/P2 ("θ = 0 is a reasonable default"), which is a choice
informed by the P1 post-hoc θ curve. Disclosed; θ was not changed after the P4 labels.

## D4-4 Transfer cell (registered as exploratory, "2 meetings of a second French-speaking frontier body with agenda +
minutes, chosen by a seeded draw among frontier bodies with both document kinds")
- The registration gives no seed value. Written here before the draw (2026-10-10T11:20:22+0200): seed **20261015**.
- Eligibility (frontier list `results/census/virtual_affairs.json`, French-speaking, OPD meeting documents with text named
  "Ordre du jour" AND "Procès-verbal" under the same meeting): only **La Chaux-de-Fonds (6421)** qualifies (Sion: 1 agenda;
  Fully, Conthey, Monthey: no document named as an agenda; Yverdon: no meeting documents with text). The body draw is
  therefore trivial; the 2 meetings are drawn with the seed above among La Chaux-de-Fonds meetings that have both kinds.
- The frozen candidate function (`eval/gold4/sample.py`) is hard-wired to Bulle; `eval/gold4/transfer.py` applies the same
  rule (agenda + minutes of the same sitting, text ok) with the body as a parameter.

## D4-5 Hypothesis script and the meeting-date output
`eval/gold4/hypotheses4.py` was written after the run (commit ddf0716). The frozen scorer (`run_p4.py score`) does not output
the derived meeting date that P4-H4 needs, so the script reads it from the virtual affair number each prediction row carries
(`V <meeting date> - <item no>`, written by the frozen `derive.py`) and compares it with the gold meeting date.
Result as reported: 6/6.

## D4-6 (11 Oct 2026, round-9 jury): the PREREG4 header predates the lock
`PREREG4.md` line 1 still reads "DRAFT, not locked". The header was written before the lock and was not updated when P4
was locked; the file is hashed in `LOCK4`, so it is left unchanged to keep the lock verifiable. `LOCK4` is the record:
P4 was locked before any P4 label, and its registered content is the hashed text.
