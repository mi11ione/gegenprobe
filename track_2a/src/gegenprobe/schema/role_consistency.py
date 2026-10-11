"""Author-role consistency in a schema v0.2 record: one rule set (the check) and one guide-backed repair (the harmonise step).

    python -m gegenprobe.schema.role_consistency FILE [FILE ...]   check v0.2 records (a record, a product row with
                                                                   `record`, or JSONL of either); exit 1 on a violation

Round 16 (J1): the converter printed a group as `sole_author` and the five persons who signed under the group's name as
`joint_author` on the same affair (results/schema/v0_2/samples/p5_5192_28156.json; the post-hoc branch "a group's name
over signatures, no 'for the group'" in gegenprobe.convert.roles, frozen under the LOCK files, so the repair is applied
here, after the rules, in the v0.2 carrier (gegenprobe.schema.v0_2_parts) and in `python -m gegenprobe affair`).

The check (`violations`), from P8's role definitions (eval/p8/GUIDE_P8.md section 2) and held by all 66 of P8's blind
gold records:
  R1  at most one `sole_author` per affair ("the only author printed");
  R2  `sole_author` and `joint_author` exclude each other (one only author, or several with equal standing);
  R3  a person who is `sole_author` excludes a `first_signatory` (a group or committee that is the author may have a
      person set apart as its first signatory: P8 gold, GR and Lugano, 6 of 66 records);
  R4  `joint_author` excludes `first_signatory` ("none designated first"), and a `joint_author` has at least one other
      joint author.
Not adopted: "a first_signatory needs a co_signatory or a group". GUIDE_P8 names "X et consorts" as a first-signatory
form, and 9 of P8's 66 blind gold records carry a first signatory alone (the consorts are not listed).

The repair (`harmonise`): where `sole_author` and `joint_author` meet (R2), every `sole_author` becomes `joint_author`.
GUIDE_P8's `joint_author` is "one of several authors printed with equal standing, none designated first (... a list of
signatures under the text with no designated first)"; a group's name over the signatures, without "per il gruppo / for
the group" (which would make the persons spokespersons), is one more author of equal standing. The persons keep
`joint_author`; nobody is promoted to `first_signatory`, which the document does not print. The value, page, span and
rule of every name are unchanged; the record's `extraction.notes` gets one sentence naming the change.
"""
from __future__ import annotations

import collections
import copy
import json
import sys

STEP = "gegenprobe.schema.role_consistency"
GUIDE = "eval/p8/GUIDE_P8.md section 2"


def _role_counts(actors: list[dict]) -> collections.Counter:
    return collections.Counter(a.get("role") for a in actors)


def violations(actors: list[dict]) -> list[str]:
    """The R1-R4 violations of one affair's actors (empty when consistent)."""
    c = _role_counts(actors)
    out = []
    if c["sole_author"] > 1:
        out.append(f"R1: {c['sole_author']} sole_author entries on one affair")
    if c["sole_author"] and c["joint_author"]:
        out.append("R2: sole_author together with joint_author")
    if c["first_signatory"] and any(a.get("role") == "sole_author" and a.get("kind") == "person" for a in actors):
        out.append("R3: a person sole_author together with a first_signatory")
    if c["joint_author"] and c["first_signatory"]:
        out.append("R4: joint_author together with first_signatory")
    if c["joint_author"] == 1:
        out.append("R4: a single joint_author (a joint author has at least one other)")
    return out


def harmonise_actors(actors: list[dict]) -> tuple[list[dict], list[dict]]:
    """(actors, changes): R2 repaired by making every sole_author a joint_author; nothing else is touched."""
    c = _role_counts(actors)
    if not (c["sole_author"] and c["joint_author"]):
        return actors, []
    out, changes = [], []
    for a in actors:
        if a.get("role") == "sole_author":
            name = a.get("name")
            changes.append(dict(name=name.get("value") if isinstance(name, dict) else name, kind=a.get("kind"),
                                was="sole_author", now="joint_author"))
            a = dict(a, role="joint_author")
        out.append(a)
    return out, changes


def note(changes: list[dict]) -> str:
    who = ", ".join(f"{x['kind']} '{x['name']}'" for x in changes)
    return (f"author roles harmonised by {STEP} ({GUIDE}: authors printed with equal standing, none designated first, "
            f"are joint authors): {who} sole_author -> joint_author")


def harmonise(rec: dict) -> tuple[dict, list[dict]]:
    """(record, changes): the v0.2 record with R2 repaired and a sentence added to `extraction.notes` when changed."""
    actors, changes = harmonise_actors(rec.get("actors") or [])
    if not changes:
        return rec, []
    rec = copy.deepcopy(rec)
    rec["actors"] = copy.deepcopy(actors)
    ex = rec.setdefault("extraction", {})
    n = note(changes)
    ex["notes"] = f"{ex['notes']}; {n}" if ex.get("notes") else n
    return rec, changes


def check_records(recs: list[dict]) -> dict:
    """{n_records, n_violating, violations: [{affair, violations}]} over v0.2 records."""
    bad = []
    for r in recs:
        v = violations(r.get("actors") or [])
        if v:
            ref = r.get("ref") or {}
            bad.append(dict(affair=f"{ref.get('body_key')}:{ref.get('opd_id')}", violations=v))
    return dict(n_records=len(recs), n_violating=len(bad), violations=bad)


def _objects(path: str):
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
    n = bad = 0
    for p in argv:
        for where, obj in _objects(p):
            rec = obj.get("record") if isinstance(obj.get("record"), dict) else obj
            n += 1
            for v in violations(rec.get("actors") or []):
                bad += 1
                print(f"{where}: {v}")
    print(f"{n} records, {bad} role-consistency violations (R1-R4, {STEP})", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
