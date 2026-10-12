"""`make run` step: every claim in claims.tsv recomputed from its results file and found in the documents that print it;
the wording pins (claims_pins.json: verdicts, multipliers, safety/sovereignty/declaration sentences) checked;
444_Report.pdf in sync with technical_report.md (every anchor phrase of the report found in the PDF's text, and the
report's whole text word by word: report/pdf_check.py); the app's stated numbers under the claims (gegenprobe.claims_app)."""
from .claims import check, load
from .claims_pins import summary as pins_summary
from .paths import ROOT


def pdf_errors() -> tuple[list[str], str]:
    """(errors, note): the PDF check, or a note when pdftotext is not installed (the image and CI have it)."""
    try:
        from report import pdf_check
    except ImportError as e:  # report/ is not importable: run from track_2a/ with PYTHONPATH=src:.
        return [f"pdf_check unavailable: {e}"], ""
    try:
        raw = pdf_check.pdf_text(pdf_check.PDF)
        if raw is None:
            raise FileNotFoundError("pdftotext not found (poppler-utils)")
        missing = pdf_check.check(text=raw)
        drifted = pdf_check.report_drift(text=raw)
    except FileNotFoundError as e:
        return [], f"PDF not checked ({e})"
    return [f"444_Report.pdf is stale: {ph!r} is in technical_report.md but not in the PDF" for ph in missing] + \
        [f"444_Report.pdf is stale: {d}" for d in drifted], \
        f"PDF checked against {len(pdf_check.phrases())} report phrases and the report's whole text"


def main(ctx: dict) -> dict:
    rows = load(ROOT / "claims.tsv")
    site_notes: list[str] = []
    errs = check(rows, render_site=True, notes=site_notes)
    perrs, note = pdf_errors()
    errs += perrs
    note = "; ".join([n for n in [note] + site_notes if n])
    return dict(status="FAIL" if errs else "PASS",
                summary=f"{len(rows)} claims recomputed, {pins_summary()}, {len(errs)} failing"
                + (f"; {note}" if note else ""),
                errors=errs[:50])
