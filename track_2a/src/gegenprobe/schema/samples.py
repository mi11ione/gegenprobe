"""Hand-built schema v0.1 samples from the worked examples in spikes/recovery/results.md §7, plus the JSON Schema export.

    python -m gegenprobe.schema.samples      # writes results/schema/{affair.schema.json, samples/*.json, samples_check.json}

Values and OPD record ids are the real ones (OPD export snapshot 2026-10-06). Spans are computed by exact search in the cached
pdftotext output of the source PDFs (WORK/text), so the samples pass the span re-check; when the PDFs are not cached (e.g. in
Docker) the committed sample files are validated without the span step.

  be_2024_RRGR_91   answer present in OPD but unlinked: the canton RRB (OPD doc 404590, parentless) carries
                    "RRB-Nr.: 879/2024 vom 28. August 2024"; OPD's own 'Beantwortet' event says 2024-08-28.
  be_2024_RRGR_97   the same situation seen only through OPD: the answer exists as parentless docs 89814 (DE) / 253383 (FR),
                    so the answer date from documents is TypedNull(unlinked), not not_in_corpus.
  che_14_089        government affair whose Federal Gazette doc 38879 stores Fedlex's "JavaScript required" page as text;
                    the decree is recovered via Fedlex (eli/fga/2014/2095/de) and read with spans.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from ..paths import PDF_CACHE, RESULTS, TEXT_CACHE
from .schema_v0_1 import SCHEMA_VERSION, Affair

OUT = RESULTS / "schema"
BE91_SHA = "aee311edbe3633cbc60d581aa17b6a4f368d8ec31eeae3dbe16c44e6e05bce32"   # canton OGD 0778ef86…-332.pdf (201,704 B)
CHE_SHA = "ef0da1854be3de6aed18a811ed7bc0c031b404160afe27390e19a47162c69b8b"    # fedlex eli/fga/2014/2095/de pdf-a
RUN = dict(converter_version="samples-hand-0.1", schema_version=SCHEMA_VERSION, created="2026-10-09T20:00:00Z", builds=[],
           notes="hand-built sample from spikes/recovery/results.md §7; not converter output")


def _pages(sha: str) -> list[str] | None:
    hits = sorted(TEXT_CACHE.glob(f"{sha}.pdftotext-*.json")) if TEXT_CACHE.exists() else []
    if hits:
        return json.loads(hits[-1].read_text())["pages"]
    if (PDF_CACHE / f"{sha}.pdf").exists():
        from .. import pdftext
        return pdftext.extract(sha, ocr=False)["pages"]
    return None


def _span(pages, pattern: str, group: int = 0, page: int | None = None) -> dict:
    for i, t in enumerate(pages):
        if page and i + 1 != page:
            continue
        m = re.search(pattern, t)
        if m:
            return dict(page=i + 1, char_start=m.start(group), char_end=m.end(group), quote=m.group(group))
    raise LookupError(pattern)


def _meta(value, role, source):
    return dict(kind="value", value=value, role=role, basis="metadata", route="metadata", source=source)


def be_91(pages) -> dict:
    doc = "be-ogd:0778ef860e7d4e5c8ab89d1fe2922a42"
    rrb_date = _span(pages, r"RRB-Nr\.:[\s\S]*?\n\d+/2024\nvom (28\. August 2024)", group=1)
    rrb_nr = _span(pages, r"\n(879/2024)\nvom 28\. August 2024", group=1)
    sub = _span(pages, r"Eingereicht am:\n\n(13\.03\.2024)", group=1)
    head = _span(pages, r"Antwort des Regierungsrates")
    return dict(
        schema_version=SCHEMA_VERSION,
        ref=dict(body_key="BE", number="2024.RRGR.91", opd_id=130828),
        body=dict(key="BE", name="Grosser Rat des Kantons Bern", level="cantonal", languages=["de", "fr"]),
        type=dict(harmonised="interpellation", opd_harmonised_id=8, source_label="Interpellation"),
        title=dict(de="Wie wirkt sich die BVG-Reform auf die Versicherten der Bernischen Pensionskasse (BPK) und der "
                      "Bernischen Lehrerversicherungskasse (BLVK) aus?"),
        languages=["de", "fr"],
        actors=[dict(role="addressed_body", kind="executive", name=dict(kind="value", value="Regierungsrat", basis="inferred",
                     route="rule", doc=doc, **head))],
        dates=[
            dict(role="submitted", label="Eingereicht", date=_meta("2024-03-13", "submitted", "opd:events/271159")),
            dict(role="submitted", label="Eingereicht am", date=dict(kind="value", value="2024-03-13", role="submitted",
                 basis="normalised", route="rule", doc=doc, **sub)),
            dict(role="answered", label="Beantwortet", date=_meta("2024-08-28", "answered", "opd:events/84384")),
            dict(role="scheduled", label="Traktandiert", date=_meta("2024-11-25", "scheduled", "opd:events/675383")),
        ],
        procedural_state=_meta("scheduled", None, "opd:events/675383"),
        decision=dict(kind="null", null_reason="not_in_corpus", route="metadata",
                      evidence="no decision event in OPD (last event 'Traktandiert' 2024-11-25); an interpellation is "
                               "debated, not decided, unless a declaration of satisfaction is recorded"),
        government_recommendation=dict(kind="value", value="not_applicable", basis="metadata", route="metadata",
                                       source="opd:affairs/130828#type_harmonized_id=8"),
        qa=[dict(question_doc="opd:83619", answer_doc=doc, link_status="parentless",
                 answering_body=dict(kind="value", value="Regierungsrat", basis="inferred", route="rule", doc=doc, **head),
                 answer_date=dict(kind="value", value="2024-08-28", role="answer_decided", basis="normalised", route="rule",
                                  doc=doc, **rrb_date),
                 answer_identifier=dict(kind="value", value="879/2024", role="RRB-Nr.", basis="extracted", route="rule",
                                        doc=doc, **rrb_nr))],
        answer_link_status="parentless",
        documents=[
            dict(doc_id="opd:83619", source="opd", url="https://ogd.parl.apps.be.ch/pdf-upload/9997a07610a24df2bf39f04920b6b276-332.pdf",
                 role="question", language="de", opd_text_status="ok"),
            dict(doc_id="opd:404590", source="opd",
                 url="https://www.rrgr-service.apps.be.ch/api/rr/documents/document/0778ef860e7d4e5c8ab89d1fe2922a42-332/27/"
                     "RRB-28.08.2024-de.pdf", role="answer", language="de", opd_text_status="ok"),
            dict(doc_id=doc, source="canton", url="https://ogd.parl.apps.be.ch/pdf-upload/0778ef860e7d4e5c8ab89d1fe2922a42-332.pdf",
                 sha256=BE91_SHA, role="answer", language="de", n_pages=len(pages), extractor="pdftotext-26.02.0",
                 image_only=False),
        ],
        extraction=RUN,
    )


def be_97() -> dict:
    return dict(
        schema_version=SCHEMA_VERSION,
        ref=dict(body_key="BE", number="2024.RRGR.97", opd_id=130832),
        body=dict(key="BE", name="Grosser Rat des Kantons Bern", level="cantonal", languages=["de", "fr"]),
        type=dict(harmonised="interpellation", opd_harmonised_id=8, source_label="Interpellation"),
        title=dict(de="Besorgniserregender Anstieg von antisemitischen, islamfeindlichen und rassistischen Vorfällen auch "
                      "an Berner Schulen"),
        languages=["de", "fr"],
        dates=[dict(role="submitted", label="Eingereicht", date=_meta("2024-03-13", "submitted", "opd:events/20753")),
               dict(role="answered", label="Beantwortet", date=_meta("2024-09-04", "answered", "opd:events/393932"))],
        procedural_state=_meta("scheduled", None, "opd:events/675389"),
        decision=dict(kind="null", null_reason="not_in_corpus", route="metadata", evidence="no decision event in OPD"),
        government_recommendation=dict(kind="value", value="not_applicable", basis="metadata", route="metadata",
                                       source="opd:affairs/130832#type_harmonized_id=8"),
        qa=[dict(question_doc="opd:300609", answer_doc=None, link_status="parentless",
                 answering_body=_meta("Regierungsrat", None, "opd:events/393932#actor_de=Regierung"),
                 answer_date=dict(kind="null", null_reason="unlinked", route="metadata", related_doc="opd:89814",
                                  evidence="RRB-04.09.2024 (910/2024) is in OPD as parentless docs 89814 (DE) and 253383 (FR) "
                                           "with no affair_id; the affair has only its Vorstoss attached"),
                 answer_identifier=dict(kind="null", null_reason="unlinked", route="metadata", related_doc="opd:89814",
                                        evidence="see answer_date"))],
        answer_link_status="parentless",
        documents=[
            dict(doc_id="opd:300609", source="opd", url="https://ogd.parl.apps.be.ch/pdf-upload/1b36381927d448dcaeb2de41ecc13fa9-332.pdf",
                 role="question", language="de", opd_text_status="ok"),
            dict(doc_id="opd:89814", source="opd",
                 url="https://www.rrgr-service.apps.be.ch/api/rr/documents/document/57f55bdf5e4b41f9a78fc4278461cf37-332/27/"
                     "RRB-04.09.2024-de.pdf", role="answer", language="de", opd_text_status="ok"),
            dict(doc_id="opd:253383", source="opd",
                 url="https://www.rrgr-service.apps.be.ch/api/rr/documents/document/a83b8687ca494f9c947f37699e630741-332/26/"
                     "RRB-04.09.2024-fr.pdf", role="answer", language="fr", opd_text_status="ok"),
        ],
        extraction=RUN,
    )


def che_14089(pages) -> dict:
    doc = "fedlex:eli/fga/2014/2095/de"
    msg = _span(pages, r"Botschaft des Bundesrates vom (19\. November 2014)", group=1)
    init = _span(pages, r"am (10\. März 2014)\d? eingereichten Volksinitiative", group=1)
    rec = _span(pages, r"empfiehlt Volk und Ständen, die Initiative abzulehnen")
    return dict(
        schema_version=SCHEMA_VERSION,
        ref=dict(body_key="CHE", number="14.089", opd_id=58009),
        body=dict(key="CHE", name="Bundesversammlung", level="federal", languages=["de", "fr", "it"]),
        type=dict(harmonised="government_affair", opd_harmonised_id=9, source_label="Geschäft des Bundesrates"),
        title=dict(de="Für eine faire Verkehrsfinanzierung. Volksinitiative",
                   fr="Pour un financement équitable des transports. Initiative populaire"),
        languages=["de", "fr", "it"],
        dates=[
            dict(role="published", label="Botschaft des Bundesrates", date=dict(kind="value", value="2014-11-19",
                 role="published", basis="normalised", route="rule", doc=doc, **msg)),
            dict(role="other", label="Volksinitiative eingereicht", date=dict(kind="value", value="2014-03-10", role="other",
                 basis="normalised", route="rule", doc=doc, **init)),
            dict(role="closed", label="Erledigt", date=_meta("2015-06-19", "closed", "opd:events/107097")),
        ],
        procedural_state=_meta("closed", None, "opd:events/107097"),
        decision=_meta("adopted", "final vote on the federal decree",
                       "opd:events/363707#title_de='Annahme in der Schlussabstimmung' (unharmonised in OPD)"),
        government_recommendation=dict(kind="value", value="reject", basis="inferred", route="rule", doc=doc, **rec),
        answer_link_status="not_applicable",
        documents=[
            dict(doc_id="opd:38879", source="opd", url="http://www.admin.ch/opc/de/federal-gazette/2014/9657.pdf",
                 role="placeholder", language="de", opd_text_status="placeholder"),
            dict(doc_id=doc, source="fedlex", url="https://www.fedlex.admin.ch/filestore/fedlex.data.admin.ch/eli/fga/2014/2095/de/"
                 "pdf-a/fedlex-data-admin-ch-eli-fga-2014-2095-de-pdf-a.pdf", sha256=CHE_SHA, role="publication", language="de",
                 n_pages=len(pages), extractor="pdftotext-26.02.0", image_only=False),
        ],
        extraction=RUN,
    )


def build() -> dict:
    (OUT / "samples").mkdir(parents=True, exist_ok=True)
    from .public import write_json_schemas  # identified schemas: $schema, $id, version (schema/public.py)

    write_json_schemas(OUT)
    p91, pche = _pages(BE91_SHA), _pages(CHE_SHA)
    built = {}
    if p91 is not None:
        built["be_2024_RRGR_91"] = be_91(p91)
    built["be_2024_RRGR_97"] = be_97()
    if pche is not None:
        built["che_14_089"] = che_14089(pche)
    for name, obj in built.items():
        a = Affair.model_validate(obj)
        (OUT / "samples" / f"{name}.json").write_text(a.model_dump_json(indent=1, exclude_none=True) + "\n")
    return dict(written=sorted(built), at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))


if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
