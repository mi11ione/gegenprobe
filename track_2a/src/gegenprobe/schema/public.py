"""Public API of schema v0.1 for integrators (OPD's extraction workbench, the converter's `record`).

    from gegenprobe.schema.public import Affair, DocExtraction, Document, validate_doc_extraction, json_schema

Every public model and vocabulary type of schema_v0_1 in one import. (gegenprobe/schema/__init__.py is frozen by the
P3b pre-registration lock, eval/prereg5/LOCK5, so the fuller export lives here; __init__ keeps its original names.)
The model code itself is unchanged: this module only re-exports it and adds identified JSON Schema documents.

JSON Schema files (results/schema/*.schema.json, written by `python -m gegenprobe.schema.public` and by
`python -m gegenprobe.schema.samples`) carry `$schema` (draft 2020-12, what Pydantic emits), a stable `$id` and the schema
`version`. JSON Schema alone cannot express the cross-field rules (a rule value needs page + span; see docs/schema.md):
validate with the Pydantic models for the full contract.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .schema_v0_1 import (SCHEMA_VERSION, Actor, ActorKind, ActorRole, Affair, AffairRef, AffairType, AffairTypeV,
                          AnswerLinkStatus, Basis, Body, DatedEvent, DateRole, DateValue, DecisionOutcome, DecisionValue,
                          DocExtraction, DocRole, DocSource, Document, DocumentPart, ExtractionRun, GovRecommendation,
                          GovRecommendationValue, Lang, Level, NullReason, PartKind, ProceduralState, ProceduralStateValue,
                          QAItem, QAPair, RelatedAffair, Relation, Route, TextValue, TypedNull, Valued, from_converter,
                          iter_fields)

__all__ = [
    "SCHEMA_VERSION", "SCHEMA_IDS", "json_schema", "validate_affair", "validate_doc_extraction", "write_json_schemas",
    # models
    "Actor", "Affair", "AffairRef", "AffairTypeV", "Body", "DatedEvent", "DateValue", "DecisionValue", "DocExtraction",
    "Document", "DocumentPart", "ExtractionRun", "GovRecommendationValue", "ProceduralStateValue", "QAItem", "QAPair",
    "RelatedAffair", "TextValue", "TypedNull", "Valued",
    # vocabularies (Literal types)
    "ActorKind", "ActorRole", "AffairType", "AnswerLinkStatus", "Basis", "DateRole", "DecisionOutcome", "DocRole",
    "DocSource", "GovRecommendation", "Lang", "Level", "NullReason", "PartKind", "ProceduralState", "Relation", "Route",
    # helpers
    "from_converter", "iter_fields",
]

ID_BASE = "https://raw.githubusercontent.com/mi11ione/gegenprobe/main/track_2a/results/schema/"
SCHEMA_IDS = {"affair": ID_BASE + "affair.schema.json", "doc_extraction": ID_BASE + "doc_extraction.schema.json"}
_MODELS = {"affair": Affair, "doc_extraction": DocExtraction}


def json_schema(name: str) -> dict:
    """JSON Schema of `affair` or `doc_extraction`, identified: $schema, $id, version first, then Pydantic's schema."""
    body = _MODELS[name].model_json_schema()
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": SCHEMA_IDS[name], "version": SCHEMA_VERSION,
            **body}


def write_json_schemas(out: Path | None = None) -> list[Path]:
    from ..paths import RESULTS

    out = out or RESULTS / "schema"
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in _MODELS:
        p = out / f"{name}.schema.json"
        p.write_text(json.dumps(json_schema(name), ensure_ascii=False, indent=1) + "\n")
        paths.append(p)
    return paths


def validate_affair(obj: dict) -> Affair:
    return Affair.model_validate(obj)


def validate_doc_extraction(obj: dict) -> DocExtraction:
    return DocExtraction.model_validate(obj)


if __name__ == "__main__":
    for p in write_json_schemas(Path(sys.argv[1]) if len(sys.argv) > 1 else None):
        print(p)
