# P10 deviations from PREREG10.md (logged as they happen)

**D1 (annotation, 11 Oct 2026).** The annotator instructions allowed only the selfcheck command. Annotator A1 (Claude
Opus) reported that, before labelling, it also ran three read-only commands on files it was allowed to read: it printed
sections 1–2 of `eval/p8/GUIDE_P8.md` (named by `GUIDE_P10.md`), listed the packet file sizes and printed
`P10-001.txt`. It opened no key, text, data, result or source file and no other annotator's folder. Blindness is
unaffected; the labels stand. A2 (Claude Sonnet) reported no command besides the selfcheck.

**D2 (exploratory 8B arm, 11 Oct 2026, written before any 8B answer exists).** PREREG10 §4 (d) runs the frozen pointer
on the local Apertus 8B GGUF with the gateway's thresholds, not refitted. `eval/p10/run_8b.py` (CI:
`.github/workflows/arms-8b-p10.yml`) runs exactly that (variant `frozen`) and, in addition, a variant `refit_dev` whose
tau and tau_first are refitted on the 8B's answers on P10's development set (P8's 6 development parliaments, 36 affairs)
by the §7 selection rule; prompts and the lone-first cue rule stay frozen, and no test label is read. The refit is
reported only if all 36 development affairs are rebuilt byte-identically and fully scored. The runner extracts text
with Ubuntu's poppler, not the macOS build the gold and the registered arm read; per-affair text identity is reported.
Both variants are exploratory and outside the family; no registered result changes.
