"""OPD's response to the data-quality findings (correspondence, 10 Oct 2026), factual content only.

Single switch: ATTRIBUTION. While OPD's consent to be cited by name is pending it is the neutral string below; set it to a
named attribution in this one place once consent is given (every generated file and the docs read it from here).
"""
from __future__ import annotations

ATTRIBUTION = "OPD confirmed (correspondence, 10 Oct 2026)"
SOURCE_DATE = "2026-10-10"

# finding id -> {status, summary}
# status: confirmed_bug | confirmed | source_discrepancy | explained | by_design | scope_pointer
STATUS: dict[str, dict] = {
    "be_answers_unlinked": dict(
        status="confirmed_bug",
        summary="Root cause: the government's answer reaches OPD from two sources with the same document id; staging keeps the "
        "first parent seen and the government-agenda load runs first, so the answer hangs under that agenda item or has no "
        "parent if the item is not in OPD. Fix pending; the relink list is the interim workaround.",
    ),
    "be_begin_date_import": dict(
        status="confirmed_bug",
        summary="2024-10-28 is a load timestamp, not a date of the affair: older affairs (mostly 2010-2013) plus about 170 BE "
        "affairs from later loads. The true date is the affair's 'Eingereicht' event. Fix pending; correction list in "
        "results/repair/repair_BE_begin_date.tsv.",
    ),
    "grparl_384_date": dict(
        status="source_discrepancy",
        summary="Not an OPD error: the canton's open data (submission date 2025-06-18) disagrees with the canton's own PDF "
        "(19.06.2025); OPD keeps the open-data value.",
    ),
    "hash_not_sha256": dict(
        status="explained",
        summary="`hash` is an identifier, not a content checksum: sha256 hex of body_key + parent_type + url without a "
        "separator, also the file name on files.openparldata.ch. Verified by code: results/census/hash_check.json.",
    ),
    "che_placeholder": dict(
        status="confirmed",
        summary="Federal Gazette / AS links now land on the Fedlex web app, so its 'JavaScript required' page is stored instead "
        "of the PDF (about 55% of CHE documents by OPD's count). Federal answers are in the texts export. Quoted search phrases "
        "are compared with the whole field, so they never match inside a document's text.",
    ),
    "lang_tag_FR": dict(
        status="by_design",
        summary="FR and VS are bilingual; the crawler fetches German first, then French. Schema implication: a body's "
        "language must be multi-valued.",
    ),
    "lang_tag_VS": dict(
        status="by_design",
        summary="FR and VS are bilingual; the crawler fetches German first, then French. Schema implication: a body's "
        "language must be multi-valued.",
    ),
    "doc_language_null": dict(
        status="by_design",
        summary="The document language is set per pipeline; an empty field means 'not specified'. Schema implication: "
        "document language allows 'unspecified', distinct from unknown.",
    ),
    "persons_contact_fields": dict(
        status="by_design",
        summary="Intended: public figures, public sources. We stored field names only.",
    ),
    "docs_without_affairs": dict(
        status="scope_pointer",
        summary="Many communes publish only per-meeting documents (minutes) and no affairs. Deriving 'virtual affairs' from "
        "meeting documents is part of the challenge; OPD numbers them 'V' + start date (e.g. SO consultations).",
    ),
    "numbers_from_dates": dict(
        status="scope_pointer",
        summary="'V' + start date is OPD's virtual affair number (e.g. SO consultations), not a data error.",
    ),
}


def attach(finding: dict) -> dict:
    s = STATUS.get(finding["id"])
    if s:
        finding = dict(finding, opd_response=dict(s, attribution=ATTRIBUTION, date=SOURCE_DATE))
    return finding
