# Whole-affair extraction (P3)

`src/gegenprobe/affair/` turns an affair's documents (the member's text and the executive's answer) plus OPD metadata into a
validated schema v0.1 `Affair`, field by field, with the same rule as the answer-date converter: metadata first, then
deterministic rules on the documents, then Apertus only as a closed-set pointer with null, and only as a review suggestion.

| field | metadata (route metadata, `source`) | rules on the documents (route rule, page + span) | Apertus pointer (closed set + null) |
|---|---|---|---|
| number | OPD affair number | the own number printed in either document | — |
| affair type | OPD harmonised type + the body's label | first type word in the question head (DE/FR/IT lexicon) | interpellation / motion / postulate / question / resolution |
| submitter | first OPD contributor with role author | a known office holder of the body printed after an author cue | office holders of the body (OPD contributors) whose surname is printed in the question |
| co-signatories | further OPD authors | — | — |
| addressed body | — | addressee phrase ("an den Regierungsrat", "au Conseil d'État", …) | executive / parliament / committee / administration |
| submission date | OPD "Eingereicht" event (BE begin_date 2024-10-28 is a load timestamp and is skipped) | a date within 80 characters after a submission cue | dates printed in the question |
| answer date + decision no. | OPD answer event (used only where the answer prints it) | the frozen P1 cascade on the answer | the frozen P1 pointer (θ +10.40) |
| recommendation | OPD "Antrag:" events | the frozen P1 rules | the frozen P1 pointer |
| procedural state, decision | latest harmonised OPD event | — | — |
| related affairs | — | other OPD-known affair numbers printed | — |
| answer-link status | census (`gegenprobe.census.funnel`) | — | — |

Commands: `python -m eval.gold3.run_p3 --backend none|gateway:…|gguf|fake` writes `results/eval3/p3__<build>.json` with each
arm's values, the pointer suggestions (with model build, θ, margin, candidate count, prompt id) and the validated `Affair`
instances. The evaluation design is `eval/prereg3/PREREG3_draft.md`; the annotation guide `eval/gold3/GUIDE.md`.
θ for the new pointer fields is 0 (declared; no dev labels exist for them).
