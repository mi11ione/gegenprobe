"""Validate a JSON file against schema v0.1 with the normative Pydantic models (the exported JSON Schema cannot express
the cross-field rules, e.g. "a rule-produced value carries page + span", "an Apertus abstention has margin > θ",
"a null reason is legal for its route"; the Pydantic validators can).

    python -m gegenprobe.schema.validate FILE [FILE ...]
FILE may hold an Affair, a DocExtraction, a converter output row (its `record` is validated), or JSONL of any of these.
Exit 0 if every object is valid, 1 otherwise (each error printed with its JSON path).
"""
from __future__ import annotations

import json
import sys

from pydantic import ValidationError

from .schema_v0_1 import Affair, DocExtraction


def kind_of(obj: dict):
    if "record" in obj and "status" in obj:
        return "row", DocExtraction
    if "ref" in obj and "body" in obj:
        return "affair", Affair
    if "doc" in obj and "extraction" in obj:
        return "doc_extraction", DocExtraction
    return None, None


def validate_obj(obj: dict) -> list[str]:
    kind, model = kind_of(obj)
    if model is None:
        return ["not a schema v0.1 object (expected an Affair, a DocExtraction or a converter output row)"]
    if kind == "row":
        if obj.get("status") != "ok":
            return []  # a typed failure row carries no record
        obj = obj["record"]
    try:
        model.model_validate(obj)
        return []
    except ValidationError as e:
        return [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]


def iter_objects(path: str):
    text = open(path, encoding="utf-8").read().strip()
    if not text:
        return
    if text.startswith("{") and "\n{" in text:
        for i, line in enumerate(text.splitlines(), 1):
            if line.strip():
                yield f"{path}:{i}", json.loads(line)
    else:
        yield path, json.loads(text)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    bad = n = 0
    for path in argv:
        for where, obj in iter_objects(path):
            n += 1
            errs = validate_obj(obj)
            if errs:
                bad += 1
                print(f"INVALID {where}")
                for e in errs[:20]:
                    print(f"  {e}")
    print(f"{n} objects, {n - bad} valid, {bad} invalid")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
