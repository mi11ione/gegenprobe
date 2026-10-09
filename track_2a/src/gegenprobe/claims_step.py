"""`make run` step: every claim in claims.tsv recomputed from its results file and found in the documents that print it."""
from .claims import check, load
from .paths import ROOT


def main(ctx: dict) -> dict:
    rows = load(ROOT / "claims.tsv")
    errs = check(rows)
    return dict(status="FAIL" if errs else "PASS", summary=f"{len(rows)} claims recomputed, {len(errs)} failing", errors=errs[:50])
