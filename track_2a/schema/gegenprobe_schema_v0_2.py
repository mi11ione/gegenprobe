"""Gegenprobe affair schema v0.2.0: schema v0.1 plus the roles the pre-registered meaning test P8 found.

Needs only pydantic>=2 and the sibling file gegenprobe_schema.py (schema v0.1, unchanged): copy both files next to your code
and
    from gegenprobe_schema_v0_2 import Affair, upgrade_v0_1, json_schema, validate_affair
The module reads and writes nothing.

What v0.2 adds to v0.1 (every v0.1 field is kept, so a v0.1 record upgrades losslessly: `upgrade_v0_1`, `downgrade_to_v0_1`)
  * Actor roles: sole_author, joint_author, supporter, spokesperson and group next to v0.1's first_signatory,
    co_signatory and committee; groups and committees are actors (`kind` parliamentary_group / committee), and a
    spokesperson names the body it speaks for (`on_behalf_of`).
  * `type.instrument_function`: what the member's text asks for (mandate, direct_decision, examine_report, questions,
    other) next to the harmonised type, and `type.instrument_named`: what the documents call the instrument.
  * `Document.language_of_text` (determined from the text) apart from `Document.language_tag` (what the source tags);
    v0.1's `language` stays and equals the tag.
  * Submission-date roles in `DateRole`: signed, lodged, received, announced, later_step (v0.1's `submitted` stays and
    names a source's own "submitted" event, e.g. OPD's).
  * `government_recommendation.stage`: on_adoption (whether to take the motion or postulate up) or on_fulfilment (the
    executive's report on one already adopted).
  * Provenance: a span may be pinned by `quote_sha256` instead of a verbatim `quote` (the value stays checkable against the
    document without redistributing its text); route `annotator` for values labelled by an annotator (gold labels), located
    to a document and page; null reason `not_extracted` for a field the producer did not attempt.
  * Typed reasons for empty lists (`Affair.empty_reasons`): every list field of the record that is empty (EMPTY_FIELDS:
    languages, actors, dates, qa, related_affairs, documents, title, body.languages and, per document, language_of_text
    and parts, per Q/A pair, items) carries a reason keyed by its path ("documents.1.language_of_text"), so an empty list
    is never silent; a reason for a list that is not empty is an error. `Document.language_of_text_method` names how the
    language of the text was determined (a detector, or `annotator`), apart from the source's `language_tag`.
    `extraction.builds` is not covered: it lists model builds consulted, and [] means no model was consulted.
"""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Generic, Literal, TypeVar, Union, get_args

from pydantic import BaseModel, Discriminator, Field, model_validator

try:  # package-relative (both files inside a package) or next to each other on sys.path
    from . import gegenprobe_schema as _v01
except ImportError:
    import gegenprobe_schema as _v01

SCHEMA_VERSION = "0.2.0"
V01_VERSION = _v01.SCHEMA_VERSION

# ----------------------------------------------------------------------------------------------- vocabularies (v0.1 + P8)
Route = Literal[get_args(_v01.Route) + ("annotator",)]
MODEL_ROUTES = _v01.MODEL_ROUTES
SPAN_ROUTES = _v01.SPAN_ROUTES
NullReason = Literal[get_args(_v01.NullReason) + ("not_extracted",)]
NULL_ROUTES: dict[str, tuple[str, ...]] = {
    **{k: v + ("annotator",) for k, v in _v01.NULL_ROUTES.items()},
    # the producer did not attempt this field (v0.1 had no honest reason for it: docs/ech-onepager.md §4)
    "not_extracted": get_args(Route),
}
ActorRole = Literal[get_args(_v01.ActorRole) + ("sole_author", "joint_author", "supporter", "spokesperson", "group")]
DateRole = Literal[get_args(_v01.DateRole) + ("signed", "lodged", "received", "announced", "later_step")]
InstrumentFunction = Literal["mandate", "direct_decision", "examine_report", "questions", "other"]
InstrumentNamed = Literal["motion", "postulate", "interpellation", "question", "resolution", "initiative", "other"]
RecommendationStage = Literal["on_adoption", "on_fulfilment"]
# why a list is empty: the null reasons, plus `carried_from_v0_1` (a v0.1 record upgraded by upgrade_v0_1: v0.1 records no
# reason for an empty list) and `none_printed` (the producer read the source and it lists nothing: no co-signatory, no
# related affair)
EmptyReasonCode = Literal[get_args(NullReason) + ("carried_from_v0_1", "none_printed")]
Lang = _v01.Lang

T = TypeVar("T")
_strict = _v01._strict


# ----------------------------------------------------------------------------------------------- provenance-bearing values
class Valued(BaseModel, Generic[T]):
    """v0.1's Valued, plus `quote_sha256` (a span pinned by the hash of its text) and route `annotator`."""
    model_config = _strict
    kind: Literal["value"] = "value"
    value: T
    role: str | None = Field(None, description="semantic role of the value (e.g. a DateRole for dates)")
    basis: _v01.Basis
    route: Route
    doc: str | None = Field(None, description="Document.doc_id the span points into")
    page: int | None = Field(None, ge=1)
    char_start: int | None = Field(None, ge=0)
    char_end: int | None = Field(None, ge=0)
    quote: str | None = Field(None, max_length=400, description="verbatim source text at the span (short)")
    quote_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$",
                                     description="sha256 of the verbatim text at the span, in place of or next to `quote`")
    context: str | None = Field(None, max_length=400, description="the source line around the span, for review (not checked)")
    source: str | None = Field(None, description="structured record for basis=metadata, e.g. 'opd:events/618276'")
    model_build: str | None = None
    theta: float | None = None
    margin: float | None = Field(None, description="null margin of the forced choice (nats); value kept iff margin <= theta")
    candidates: int | None = Field(None, ge=0, description="size of the closed candidate set the model chose from")
    rule: str | None = Field(None, description="id of the deterministic rule that produced the value (route rule / ocr+rule; "
                             "user_anchor:<id> for route user_anchor)")

    @model_validator(mode="after")
    def _consistent(self):
        has_span = self.page is not None and self.char_start is not None and self.char_end is not None
        pinned = bool(self.quote or self.quote_sha256)
        doc_level = self.basis == "inferred" and self.route in MODEL_ROUTES and not has_span
        if self.route == "annotator":
            # an annotator's label names its document and page; a span, when given, is pinned by quote or hash
            if not (self.doc and self.page is not None):
                raise ValueError("route=annotator needs doc and page")
            if (self.char_start is not None or self.char_end is not None) and not (has_span and pinned):
                raise ValueError("an annotator span needs page, char_start, char_end and quote or quote_sha256")
        elif doc_level:
            if not (self.doc and self.candidates):
                raise ValueError("a document-level model classification needs doc and candidates")
        elif self.basis in ("extracted", "normalised", "inferred") or self.route in SPAN_ROUTES:
            if not (has_span and self.doc and pinned):
                raise ValueError(f"route={self.route} basis={self.basis} needs doc, page, char_start, char_end and "
                                 "quote or quote_sha256")
        if has_span and self.char_end <= self.char_start:
            raise ValueError("char_end must be > char_start")
        if self.basis == "metadata" and not self.source:
            raise ValueError("basis=metadata needs `source` (the OPD/canton record)")
        if self.route == "metadata" and self.basis != "metadata":
            raise ValueError("route=metadata implies basis=metadata")
        if self.basis == "metadata" and self.route != "metadata":
            raise ValueError("basis=metadata implies route=metadata")
        _v01._model_fields(self.route, self.model_build, self.theta, self.margin)
        return self


class TypedNull(_v01.TypedNull):
    """v0.1's TypedNull with route `annotator` and null reason `not_extracted`."""
    null_reason: NullReason
    route: Route

    @model_validator(mode="after")
    def _consistent(self):
        allowed = NULL_ROUTES[self.null_reason]
        if self.route not in allowed:
            raise ValueError(f"null_reason={self.null_reason} cannot come from route={self.route} (allowed: {allowed})")
        if self.null_reason == "unlinked" and not self.related_doc:
            raise ValueError("null_reason=unlinked needs related_doc (the unattached document)")
        _v01._model_fields(self.route, self.model_build, self.theta, self.margin)
        if self.route in MODEL_ROUTES and self.margin is not None and self.theta is not None and self.margin <= self.theta:
            raise ValueError("a model abstention needs margin > theta")
        return self


class EmptyReason(BaseModel):
    """Why a list field of the record is empty."""
    model_config = _strict
    reason: EmptyReasonCode
    route: Route | None = Field(None, description="the route that established it (None for carried_from_v0_1)")
    evidence: str = Field(..., min_length=1, description="the record, rule or source that establishes why it is empty")
    doc: str | None = Field(None, description="Document.doc_id that was read, for not_in_document / none_printed")

    @model_validator(mode="after")
    def _consistent(self):
        if self.reason == "carried_from_v0_1":
            return self
        if self.route is None:
            raise ValueError(f"empty reason {self.reason} needs the route that established it")
        if self.reason in NULL_ROUTES and self.route not in NULL_ROUTES[self.reason]:
            raise ValueError(f"empty reason {self.reason} cannot come from route={self.route}")
        return self


class DateValue(Valued[dt.date]):
    decision_number: str | None = Field(
        None, description="the executive's decision number printed with the date (RRB-Nr., ACE, RG n.), if the rule captured it")


class TextValue(Valued[str]):
    pass


class ProceduralStateValue(Valued[_v01.ProceduralState]):
    pass


class DecisionValue(Valued[_v01.DecisionOutcome]):
    pass


class GovRecommendationValue(Valued[_v01.GovRecommendation]):
    stage: RecommendationStage | None = Field(
        None, description="on_adoption: whether parliament should take the motion/postulate up; on_fulfilment: the "
        "executive's report on one already adopted (approve, write off)")


class InstrumentFunctionValue(Valued[InstrumentFunction]):
    pass


class InstrumentNamedValue(Valued[InstrumentNamed]):
    pass


def _f(cls):
    return Annotated[Union[cls, TypedNull], Discriminator("kind")]


DateF = _f(DateValue)
StrF = _f(TextValue)
ProceduralStateF = _f(ProceduralStateValue)
DecisionF = _f(DecisionValue)
GovRecommendationF = _f(GovRecommendationValue)
InstrumentFunctionF = _f(InstrumentFunctionValue)
InstrumentNamedF = _f(InstrumentNamedValue)


# ----------------------------------------------------------------------------------------------- documents and components
class Document(_v01.Document):
    language_tag: Lang | Literal["unspecified"] | None = Field(
        None, description="the language the source tags the document with ('unspecified' = the source's field is empty); "
        "v0.1's `language` carries the same value")
    language_of_text: list[Lang] = Field(
        [], description="the language(s) the text is written in, determined from the text (several only for substantial parts)")
    language_of_text_method: str | None = Field(
        None, description="how language_of_text was determined: a detector id (e.g. 'stopword-profile-v1 ...') or 'annotator'")


class AffairTypeV(_v01.AffairTypeV):
    instrument_function: InstrumentFunctionF | None = Field(
        None, description="the operative request of the member's text, next to the harmonised type")
    instrument_named: InstrumentNamedF | None = Field(None, description="the name the documents give the instrument")


class Actor(_v01.Actor):
    role: ActorRole
    name: StrF
    on_behalf_of: str | None = Field(None, description="for a spokesperson: the name of the group or committee it speaks for")


class DatedEvent(_v01.DatedEvent):
    role: DateRole
    date: DateF


class QAItem(_v01.QAItem):
    question: StrF
    answer: StrF


class QAPair(_v01.QAPair):
    answering_body: StrF
    answer_date: DateF
    answer_identifier: StrF = Field(..., description="decision number of the answer, e.g. RRB-Nr. 879/2024")
    items: list[QAItem] = Field([], description="per-question pairing (question n <-> answer n), optional")


class RelatedAffair(_v01.RelatedAffair):
    evidence: StrF


class ExtractionRun(_v01.ExtractionRun):
    schema_version: Literal["0.2.0"] = SCHEMA_VERSION


class Affair(_v01.Affair):
    """A parliamentary affair in schema v0.2."""
    schema_version: Literal["0.2.0"] = SCHEMA_VERSION
    type: AffairTypeV
    actors: list[Actor] = []
    dates: list[DatedEvent] = []
    procedural_state: ProceduralStateF
    decision: DecisionF
    government_recommendation: GovRecommendationF
    qa: list[QAPair] = []
    related_affairs: list[RelatedAffair] = []
    documents: list[Document] = []
    extraction: ExtractionRun
    empty_reasons: dict[str, EmptyReason] = Field(
        {}, description="a typed reason for every empty list field (EMPTY_FIELDS), keyed by its path, e.g. "
        "'body.languages', 'documents.0.language_of_text', 'qa.0.items'")

    @model_validator(mode="after")
    def _empty(self):
        empty = set(empty_fields(self))
        missing = sorted(empty - set(self.empty_reasons))
        if missing:
            raise ValueError(f"empty list fields without a typed reason (empty_reasons): {missing}")
        extra = sorted(set(self.empty_reasons) - empty)
        if extra:
            raise ValueError(f"empty_reasons given for fields that are not empty or not covered: {extra}")
        ids = {d.doc_id for d in self.documents}
        for k, r in self.empty_reasons.items():
            if r.doc is not None and r.doc not in ids:
                raise ValueError(f"empty_reasons.{k}.doc={r.doc!r} is not in documents")
        return self

    @model_validator(mode="after")
    def _refs(self):
        ids = {d.doc_id for d in self.documents}
        if len(ids) != len(self.documents):
            raise ValueError("duplicate doc_id")
        for path, v in iter_fields(self):
            for attr in ("doc", "related_doc"):
                ref = getattr(v, attr, None)
                if ref is not None and ref not in ids:
                    raise ValueError(f"{path}.{attr}={ref!r} is not in documents")
        if self.ref.derived_from is not None and self.ref.derived_from not in ids:
            raise ValueError(f"ref.derived_from={self.ref.derived_from!r} is not in documents")
        for q in self.qa:
            for ref in (q.question_doc, q.answer_doc):
                if ref is not None and ref not in ids:
                    raise ValueError(f"qa doc {ref!r} is not in documents")
        names = {a.name.value for a in self.actors if a.name.kind == "value"}
        for i, a in enumerate(self.actors):
            if a.on_behalf_of is not None and a.on_behalf_of not in names:
                raise ValueError(f"actors.{i}.on_behalf_of={a.on_behalf_of!r} names no actor of this affair")
        return self


EMPTY_FIELDS = ("title", "languages", "actors", "dates", "qa", "related_affairs", "documents", "body.languages",
                "documents.*.language_of_text", "documents.*.parts", "qa.*.items")


def empty_fields(affair) -> list[str]:
    """Paths of the EMPTY_FIELDS that are empty in `affair` (an Affair or its JSON dict)."""
    get = (lambda o, k: o.get(k)) if isinstance(affair, dict) else getattr
    out = [k for k in ("title", "languages", "actors", "dates", "qa", "related_affairs", "documents")
           if not get(affair, k)]
    if not get(get(affair, "body"), "languages"):
        out.append("body.languages")
    for i, d in enumerate(get(affair, "documents") or []):
        out += [f"documents.{i}.{k}" for k in ("language_of_text", "parts") if not get(d, k)]
    for i, q in enumerate(get(affair, "qa") or []):
        if not get(q, "items"):
            out.append(f"qa.{i}.items")
    return out


def iter_fields(affair: Affair):
    """Yield (path, Valued|TypedNull) for every provenance-bearing field of a v0.2 affair."""
    yield from _v01.iter_fields(affair)
    for name in ("instrument_function", "instrument_named"):
        v = getattr(affair.type, name)
        if v is not None:
            yield f"type.{name}", v


# ----------------------------------------------------------------------------------------------- v0.1 <-> v0.2
V02_ONLY_KEYS = frozenset({"quote_sha256", "stage", "instrument_function", "instrument_named", "language_tag",
                           "language_of_text", "language_of_text_method", "on_behalf_of", "empty_reasons"})
UPGRADE_EVIDENCE = "upgraded from schema v0.1 by upgrade_v0_1: v0.1 records no reason for an empty list"


def upgrade_v0_1(obj: dict) -> Affair:
    """A v0.1 affair (dict, as JSON) as a v0.2 Affair. Nothing is dropped; v0.1's Document.language becomes the tag too."""
    v1 = _v01.Affair.model_validate(obj).model_dump(mode="json")
    v1["schema_version"] = SCHEMA_VERSION
    v1["extraction"]["schema_version"] = SCHEMA_VERSION
    for d in v1["documents"]:
        d["language_tag"] = d.get("language")
    v1["empty_reasons"] = {k: {"reason": "carried_from_v0_1", "evidence": UPGRADE_EVIDENCE} for k in empty_fields(v1)}
    return Affair.model_validate(v1)


def _strip(x):
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in V02_ONLY_KEYS}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def downgrade_to_v0_1(affair: Affair) -> dict:
    """The v0.1 view of a v0.2 affair: the v0.2-only fields removed. Raises if the record uses a v0.2 vocabulary value
    (a P8 role, a submission-date role, route annotator, quote_sha256 without quote) that v0.1 cannot carry."""
    d = _strip(affair.model_dump(mode="json"))
    d["schema_version"] = V01_VERSION
    d["extraction"]["schema_version"] = V01_VERSION
    return _v01.Affair.model_validate(d).model_dump(mode="json")


# ----------------------------------------------------------------------------------------------- JSON Schema
ID_BASE = "https://raw.githubusercontent.com/mi11ione/gegenprobe/main/track_2a/results/schema/v0_2/"
SCHEMA_IDS = {"affair": ID_BASE + "affair.schema.json"}


def json_schema(name: str = "affair") -> dict:
    """JSON Schema of the v0.2 `affair`, identified: $schema, $id, version first, then Pydantic's schema."""
    body = {"affair": Affair}[name].model_json_schema()
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": SCHEMA_IDS[name], "version": SCHEMA_VERSION,
            **body}


def validate_affair(obj: dict) -> Affair:
    return Affair.model_validate(obj)
