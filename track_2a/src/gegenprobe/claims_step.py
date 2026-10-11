"""`make run` step: every claim in claims.tsv recomputed from its results file and found in the documents that print it;
444_Report.pdf in sync with technical_report.md (every anchor phrase of the report found in the PDF's text)."""
from .claims import check, load
from .paths import ROOT


def pdf_errors() -> tuple[list[str], str]:
    """(errors, note): the PDF check, or a note when pdftotext is not installed (the image and CI have it)."""
    try:
        from report import pdf_check
    except ImportError as e:  # report/ is not importable: run from track_2a/ with PYTHONPATH=src:.
        return [f"pdf_check unavailable: {e}"], ""
    try:
        missing = pdf_check.check()
    except FileNotFoundError as e:
        return [], f"PDF not checked ({e})"
    return [f"444_Report.pdf is stale: {ph!r} is in technical_report.md but not in the PDF" for ph in missing], \
        f"PDF checked against {len(pdf_check.phrases())} report phrases"


def main(ctx: dict) -> dict:
    rows = load(ROOT / "claims.tsv")
    errs = check(rows)
    perrs, note = pdf_errors()
    errs += perrs
    return dict(status="FAIL" if errs else "PASS",
                summary=f"{len(rows)} claims recomputed, {len(errs)} failing" + (f"; {note}" if note else ""),
                errors=errs[:50])
