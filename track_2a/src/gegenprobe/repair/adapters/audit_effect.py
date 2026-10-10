"""Filter effect on the design sample: the first blind audit's rows re-judged by the current checks and filters.

    python -m gegenprobe.repair.adapters.audit_effect      -> results/repair/adapters/audit_effect.json

The document-type filters (filters.py) were written from this audit's 'no' and 'unclear' rows, so what this measures is
how far the filters catch the cases they were designed on and whether they remove rows the auditors judged answers. It
is NOT an unbiased precision estimate; the fresh sample (WORK/adapters/audit2, `run --fresh-audit 300`) is.

Inputs (WORK, never committed): the audit rows (WORK/adapters/audit/<BODY>.jsonl), the auditors' verdicts
(WORK/adapters/audit_verdicts/<BODY>.jsonl: is_answer yes/no/unclear), and, frozen when the filters were added, the
audited document of every row (WORK/adapters/audit/frozen: best.jsonl with the candidate the first run judged, and its
extracted text). The affair's final outcome is read from the current checkpoint (after `run --refilter`, which may
have found another document on the affair).
"""
from __future__ import annotations

import collections
import json
import sys

from . import base, registry, run, targets

AUDIT = run.AUDIT
FROZEN = AUDIT / "frozen"
VERDICTS = base.ADIR / "audit_verdicts"
OUT = run.OUT / "audit_effect.json"


def _jsonl(p) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _key(*parts) -> str:
    return "|".join(str(p) for p in parts)


def measure() -> dict:
    verdict = {(v["body"], v["affair_id"]): v["is_answer"] for p in sorted(VERDICTS.glob("*.jsonl")) for v in _jsonl(p)}
    frozen = {(r["body"], r["affair_id"]): r for r in _jsonl(FROZEN / "best.jsonl")}
    doc, final, by_filter = collections.Counter(), collections.Counter(), collections.Counter()
    removed_yes = []
    for p in sorted(AUDIT.glob("*.jsonl")):
        body = p.stem
        rows = _jsonl(p)
        if not rows:
            continue
        ad = registry.get(body)
        xs = {x["id"]: x for x in targets.load(body)}
        state = run.load_state(body)
        for a in rows:
            k = (body, a["affair_id"])
            v = verdict[k]
            fb = frozen[k]["best"]
            text = (FROZEN / "excerpts" / body / f"{a['affair_id']}.txt").read_text(encoding="utf-8").split("\n\n", 1)[1]
            c = base.Candidate(url=fb.get("url"), title=fb.get("title") or "", origin=fb.get("origin") or "source",
                               opd_doc_id=fb.get("opd_doc_id"), uid=fb.get("uid"),
                               source_typed_answer=bool(fb.get("source_typed_answer")), meta=fb.get("cmeta") or {})
            chk = ad.check(xs[a["affair_id"]], c, text)
            doc[_key(a["outcome"], chk["outcome"], v)] += 1
            if chk.get("filter"):
                by_filter[_key(chk["filter"], a["outcome"], chk["outcome"], v)] += 1
            now = state[a["affair_id"]]["outcome"]
            final[_key(a["outcome"], now, v)] += 1
            if v == "yes" and ord_(now) > ord_(a["outcome"]):
                removed_yes.append(dict(body=body, affair_id=a["affair_id"], was=a["outcome"], now=now,
                                        filter=chk.get("filter")))

    def cell(c, was, now, v):
        return c.get(_key(was, now, v), 0)

    ver_no = sum(cell(doc, "verified", o, "no") for o in run.ORDER)
    ver_unclear = sum(cell(doc, "verified", o, "unclear") for o in run.ORDER)
    ver_yes = sum(cell(doc, "verified", o, "yes") for o in run.ORDER)
    rev_no = sum(cell(doc, "review", o, "no") for o in run.ORDER)
    out = dict(
        note="design sample: the filters were written from these rows; not an unbiased precision estimate",
        rows=sum(doc.values()),
        audited_document=dict(sorted(doc.items())),
        by_filter=dict(sorted(by_filter.items())),
        affair_final_outcome=dict(sorted(final.items())),
        headline=dict(
            verified_rows=ver_no + ver_unclear + ver_yes,
            verified_no=ver_no, verified_no_caught=ver_no - cell(doc, "verified", "verified", "no"),
            verified_unclear=ver_unclear,
            verified_unclear_to_review=cell(doc, "verified", "review", "unclear"),
            verified_unclear_to_failed=cell(doc, "verified", "failed", "unclear"),
            verified_yes=ver_yes, verified_yes_removed=ver_yes - cell(doc, "verified", "verified", "yes"),
            review_no=rev_no, review_no_to_failed=cell(doc, "review", "failed", "no"),
            yes_rows=sum(n for k, n in doc.items() if k.endswith("|yes")),
            yes_rows_moved_down=len(removed_yes),
            verified_still_verified_not_yes=cell(doc, "verified", "verified", "no")
            + cell(doc, "verified", "verified", "unclear")),
        yes_rows_moved_down=removed_yes,
    )
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))
    return out


def ord_(outcome: str) -> int:
    return run.ORDER[outcome]


def main(argv: list[str]) -> int:
    print(json.dumps(measure()["headline"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
