"""Gegenprobe affair schema v0.2.1 (DRAFT, POST HOC, proposed in review): schema v0.2.0 plus the submission-date role
`cited`. v0.2.0 (gegenprobe_schema_v0_2.py) is frozen in the P11 and federal locks and stays unchanged; this file extends
it and is not used by any registered test.

Needs only pydantic>=2 and the sibling files gegenprobe_schema_v0_2.py and gegenprobe_schema.py (both unchanged): copy the
three files next to your code and
    from gegenprobe_schema_v0_2_1 import Affair, upgrade_v0_2, json_schema, validate_affair
The module reads and writes nothing.

What v0.2.1 adds to v0.2.0 (every v0.2.0 record upgrades losslessly: `upgrade_v0_2`, `downgrade_to_v0_2`)
  * `cited` in `DateRole`: the date by which a heading or another text names the affair without saying what happened on
    that day (P8's annotation guide, eval/p8/GUIDE_P8.md; P11 NI's guide uses the same definition). The registered meaning
    test P8 counts `cited` submission dates inside the shared meaning of the submission date (eval/prereg9/PREREG9.md,
    the submission-date row), but v0.2.0's `DateRole` had no `cited` and mapped it to `other`; a review (round 20)
    pointed out the inconsistency. With `cited`, the five P11 NI submission dates its annotators labelled `cited` get a
    named role (results/schema/v0_2_1/oos_role_fit.json, post hoc).
Nothing else changes: v0.2.0's validators (typed empty-list reasons, document references) apply unchanged.
"""
from __future__ import annotations

from typing import Literal, get_args

from pydantic import Field

try:  # package-relative (the files inside a package) or next to each other on sys.path
    from . import gegenprobe_schema_v0_2 as _v02
except ImportError:
    import gegenprobe_schema_v0_2 as _v02

SCHEMA_VERSION = "0.2.1"
V02_VERSION = _v02.SCHEMA_VERSION
NEW_DATE_ROLES = ("cited",)

# ----------------------------------------------------------------------------------------------- vocabularies (v0.2 + cited)
DateRole = Literal[get_args(_v02.DateRole) + NEW_DATE_ROLES]
ActorRole = _v02.ActorRole
InstrumentFunction = _v02.InstrumentFunction
InstrumentNamed = _v02.InstrumentNamed
RecommendationStage = _v02.RecommendationStage
Lang = _v02.Lang
_v01 = _v02._v01


class DatedEvent(_v02.DatedEvent):
    role: DateRole


class ExtractionRun(_v02.ExtractionRun):
    schema_version: Literal["0.2.1"] = SCHEMA_VERSION


class Affair(_v02.Affair):
    """A parliamentary affair in schema v0.2.1 (v0.2.0 plus the date role `cited`)."""
    schema_version: Literal["0.2.1"] = SCHEMA_VERSION
    dates: list[DatedEvent] = Field([], description="dated events; `role` from DateRole (v0.2.0's roles plus `cited`)")
    extraction: ExtractionRun


def upgrade_v0_2(obj: dict) -> Affair:
    """A v0.2.0 affair (dict, as JSON) as a v0.2.1 Affair; only the version strings change."""
    d = _v02.Affair.model_validate(obj).model_dump(mode="json")
    d["schema_version"] = SCHEMA_VERSION
    d["extraction"]["schema_version"] = SCHEMA_VERSION
    return Affair.model_validate(d)


def downgrade_to_v0_2(affair: Affair) -> dict:
    """The v0.2.0 view of a v0.2.1 affair. Raises if a dated event uses a role v0.2.0 cannot carry (`cited`)."""
    d = affair.model_dump(mode="json")
    d["schema_version"] = V02_VERSION
    d["extraction"]["schema_version"] = V02_VERSION
    return _v02.Affair.model_validate(d).model_dump(mode="json")


# ----------------------------------------------------------------------------------------------- JSON Schema
ID_BASE = "https://raw.githubusercontent.com/mi11ione/gegenprobe/main/track_2a/results/schema/v0_2_1/"
SCHEMA_IDS = {"affair": ID_BASE + "affair.schema.json"}


def json_schema(name: str = "affair") -> dict:
    """JSON Schema of the v0.2.1 `affair`, identified: $schema, $id, version first, then Pydantic's schema."""
    body = {"affair": Affair}[name].model_json_schema()
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": SCHEMA_IDS[name], "version": SCHEMA_VERSION,
            **body}


def validate_affair(obj: dict) -> Affair:
    return Affair.model_validate(obj)
