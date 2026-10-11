"""P8 (eval/prereg9/PREREG9.md): a pre-registered test of what seven schema fields MEAN across parliaments. Model-free.

This module holds what the registration fixes: the fields, their closed sets of meaning categories, the shared-meaning set
E of each field (the meaning the schema v0.1 definition gives it), the decision thresholds, the seeds, the parliaments
and their quotas, the exclusions (every affair and document of every existing gold, dev, test and audit set) and the
qualifying pool.

    PYTHONPATH=src:. python -m eval.p8.common probe   -> results/p8/pool_probe.json (counts per parliament; no affair)

Qualifying affair (the pool): an Interpellation, Motion, Postulate or Question (OPD's harmonised type) of one of the
twelve parliaments with one document typed as the member's text and one typed as the executive's answer, both with OPD
text status ok and 1,000-40,000 characters. The document type is a guess from OPD metadata only: P3's frozen
`eval.gold3.sample.pair_type` first, else P6's frozen `eval.p6.common.doctype6`; per role the lowest document id of the
P3-typed documents, else of the P6-typed ones. The annotators label what the documents are.
"""

from __future__ import annotations

import collections
import glob
import gzip
import hashlib
import json
import math
import random
import sys

from eval.gold.sample import affair_types
from eval.gold3 import sample as s3
from eval.p6 import common as C6
from gegenprobe.paths import DATA, DOCS_META, RESULTS, WORK

# ------------------------------------------------------------------------------------------------ paths
D8 = DATA / "p8"
W8 = WORK / "p8"
R8 = RESULTS / "p8"
AFFAIRS = D8 / "p8_affairs.jsonl"  # drawn affairs: ids, urls, sha256, pages, chars, OPD language tags; never text
FETCH_LOG = D8 / "p8_fetch_log.jsonl"
META8 = D8 / "opd_meta_p8.jsonl"  # OPD affair row, events, contributors (frozen gegenprobe.affair.meta.vendor)
NAMES8 = D8 / "body_names_p8.json"
DATELISTS = D8 / "p8_datelists.jsonl"  # per packet: the parser's distinct dates with doc/page positions (no context text)
GOLD = D8 / "p8_gold.jsonl"  # merged gold (categories, spans, quote sha256; no document text)
ANN_COMMITTED = D8 / "annotations"
KEY = W8 / "key.jsonl"  # packet id -> affair id, parliament, cell (kept in WORK until the gold is merged)
PACK = W8 / "packets"
ANN = W8 / "ann"
PROBE = R8 / "pool_probe.json"

# ------------------------------------------------------------------------------------------------ seeds and thresholds
SEED = 20261042  # draw (per parliament x group seeded order) and packet-id shuffle
SEED_A3 = 20261043  # X/Y order of the tie-break packets
SEED_BOOT = 20261044  # parliament-cluster bootstrap
N_BOOT = 10000
X = 0.90  # share of affairs in the shared-meaning set E a parliament must reach
K = 3  # a parliament is evaluable for a field with at least K determinable affairs
MIN_PARLIAMENTS = 6  # evaluable parliaments needed before a field can be called shared
QWEN = "aisingapore/Qwen-SEA-LION-v4-32B-IT"
QWEN_TAG = "2a-p8-qwen"
QWEN_CAP_USD = 0.8


def max_exceptions(n: int) -> int:
    """Affairs outside E that a parliament with n determinable affairs may have and still conform: the 10% the threshold
    X allows, and at least one (one affair is never enough to call a parliament different; it may be a labelling error)."""
    return max(1, math.floor((1 - X) * n + 1e-9))


# ------------------------------------------------------------------------------------------------ parliaments and quotas
# (body, level, language stratum, n Motion/Postulate, n Interpellation/Question). Written from results/p8/pool_probe.json
# (counts only) before any affair was drawn: 4 + 2 per parliament where the pool allows; VD has 2 eligible
# Motion/Postulate affairs, TI none. No language filter anywhere (the language field is under test): VS and GR are drawn
# as they come (VS de / fr, GR de / rm / it documents). VS replaced Luzern, whose documents OPD does not tag, so that
# the language field can reach MIN_PARLIAMENTS parliaments with tags.
QUOTAS = [
    ("TG", "canton", "de", 4, 2),  # Thurgau
    ("VS", "canton", "multi", 4, 2),  # Valais (bilingual)
    ("351", "commune", "de", 4, 2),  # Bern (city): the parliament is the Stadtrat, the executive the Gemeinderat
    ("261", "commune", "de", 4, 2),  # Zürich (city)
    ("VD", "canton", "fr", 2, 4),  # Vaud
    ("FR", "canton", "fr", 4, 2),  # Fribourg (bilingual; OPD's documents mostly French)
    ("5586", "commune", "fr", 4, 2),  # Lausanne
    ("6643", "commune", "fr", 4, 2),  # Vernier
    ("TI", "canton", "it", 0, 6),  # Ticino
    ("5192", "commune", "it", 4, 2),  # Lugano
    ("5002", "commune", "it", 4, 2),  # Bellinzona
    ("GR", "canton", "multi", 4, 2),  # Graubünden (de / rm / it)
]
BODIES = [q[0] for q in QUOTAS]
GROUPS = {"MP": ("Motion", "Postulate"), "IQ": ("Interpellation", "Question")}
SCOPE = {t for v in GROUPS.values() for t in v}
LEN_BAND = (1000, 40000)

# ------------------------------------------------------------------------------------------------ fields and categories
FIELDS = ("submitter", "co_signatories", "date_submission", "addressed_body", "language", "government_recommendation",
          "type")
CATS = {
    "submitter": ("author_person", "joint_person", "cosigner_person", "group", "committee_or_body", "other"),
    "co_signatories": ("cosigners", "supporters", "cosigners_and_supporters", "joint_authors", "includes_author_of_record",
                       "signing_for_group", "other"),
    "date_submission": ("lodged", "cited", "later_step", "answer_or_decision", "other_printed", "unprinted_differs"),
    "addressed_body": ("executive", "executive_member_or_department", "parliament", "committee", "administration",
                       "other"),
    "language": ("text_language", "subset_of_text", "superset_of_text", "other_language", "invalid_tag"),
    "government_recommendation": ("on_referral", "on_fulfilment", "other"),
    "type": ("conforms", "mandate", "examine_report", "questions", "direct_decision", "other"),
}
UNDET = "undeterminable"  # not in any denominator; its reason is recorded and reported
# E: the meaning the v0.1 definition gives the field
E = {
    "submitter": {"author_person"},
    "co_signatories": {"cosigners"},
    "date_submission": {"lodged", "cited"},
    "addressed_body": {"executive"},
    "language": {"text_language"},
    "government_recommendation": {"on_referral"},
    "type": {"conforms"},
}
# categories that name no shared role: a deviation that falls mostly here is body-specific (or unexplained), not a role split
UNNAMED = {
    "submitter": {"other"},
    "co_signatories": {"other"},
    "date_submission": {"other_printed", "unprinted_differs"},
    "addressed_body": {"other"},
    "language": set(),
    "government_recommendation": {"other"},
    "type": {"other"},
}
TYPE_FUNCTION = {"Motion": "mandate", "Postulate": "examine_report", "Interpellation": "questions", "Question": "questions"}
TYPE_WORD = {"Motion": "motion", "Postulate": "postulate", "Interpellation": "interpellation", "Question": "question"}

# label vocabularies (eval/p8/GUIDE_P8.md)
QDOC = ("member_text", "other", "unclear")
ADOC = ("executive_answer", "other", "unclear")
KINDS = ("person", "group", "committee", "other_body")
ROLES = ("sole_author", "first_signatory", "joint_author", "co_signatory", "supporter", "spokesperson", "other")
DATE_ROLES = ("signed", "lodged", "session_lodged", "cited", "later_step", "answer_or_decision", "other_procedural")
ADDR = ("executive", "executive_member_or_department", "parliament", "committee", "administration", "other",
        "none_printed")
FUNCTION = ("mandate", "examine_report", "questions", "direct_decision", "other", "unclear")
INSTRUMENT = ("motion", "postulate", "interpellation", "question", "resolution", "initiative", "other", "none")
LANGS = ("de", "fr", "it", "rm", "en")
REC_ACT = ("on_referral", "on_fulfilment", "other", "none_printed", "not_applicable")
REC_VALUE = ("accept", "reject", "convert", "partial", "accept_and_write_off", "none", "not_applicable")
FITS = ("one", "several", "none", "not_applicable")
# which label parts carry each field (a tie-break replaces exactly these parts)
PARTS = {
    "submitter": ("people",),
    "co_signatories": ("people",),
    "date_submission": ("dates", "extra_dates"),
    "addressed_body": ("addressed_body",),
    "language": ("languages",),
    "government_recommendation": ("answer_doc", "recommendation"),
    "type": ("function", "instrument_named"),
}


# ------------------------------------------------------------------------------------------------ exclusions
def _jsonl(p) -> list[dict]:
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()] if p.exists() else []


WORK_KEYS = [WORK / "p7dev" / "key.jsonl", WORK / "p7test" / "key.jsonl", WORK / "adapters" / "audit3" / "key.jsonl"]
WORK_AUDITS = [WORK / "adapters" / g for g in ("audit", "audit_orig_backup", "audit2")]
EXTRA_SETS = [DATA / "p6" / "dev2_docs.jsonl", DATA / "p6" / "p6_docs.jsonl"]


def work_inputs() -> dict[str, str]:
    """sha256 of the WORK files (never committed) that define part of the exclusions."""
    out = {}
    for p in WORK_KEYS:
        out[str(p.relative_to(WORK))] = hashlib.sha256(p.read_bytes()).hexdigest()
    for g in WORK_AUDITS:
        h = hashlib.sha256()
        for p in sorted(g.glob("*.jsonl")):
            h.update(p.name.encode() + b"\0" + p.read_bytes())
        out[f"{g.relative_to(WORK)}/*.jsonl"] = h.hexdigest()
    return out


def exclusions() -> tuple[set[int], set[int], dict]:
    """(document ids, affair ids, report) of every existing set: P1 dev + held-out (+ spikes and every dev-id source),
    P2, P3, P3b, P4 (dev, held-out, transfer), P5 dev + test, DEV2, P6 (frozen `eval.p6.common.exclusions` plus the P6
    lists), P7 dev + test, and the adapter audits (design + its backup, v2, v3). Missing inputs stop the draw."""
    for p in EXTRA_SETS + WORK_KEYS:
        if not p.exists():
            raise SystemExit(f"exclusion input missing: {p}")
    for g in WORK_AUDITS:
        if not any(g.glob("*.jsonl")):
            raise SystemExit(f"exclusion input missing: {g}/*.jsonl")
    docs, affs, _bodies = C6.exclusions(extra=EXTRA_SETS)
    n_c6 = (len(docs), len(affs))
    for p in WORK_KEYS:
        for r in _jsonl(p):
            affs.add(int(r["affair_id"]))
    for g in WORK_AUDITS:
        for p in sorted(g.glob("*.jsonl")):
            for r in _jsonl(p):
                if r.get("affair_id") is not None:
                    affs.add(int(r["affair_id"]))
    rep = dict(docs=len(docs), affairs=len(affs), from_existing_gold_sets=dict(docs=n_c6[0], affairs=n_c6[1]),
               from_p7_and_audits=len(affs) - n_c6[1])
    return docs, affs, rep


# ------------------------------------------------------------------------------------------------ pool
def pool(bodies) -> dict[str, list[dict]]:
    """body -> qualifying affairs [{affair, a_type, group, question, answer}] (module docstring)."""
    bodies = set(bodies)
    at = affair_types()
    by = collections.defaultdict(lambda: {r: {"p3": [], "p6": []} for r in ("intervention", "answer")})
    ids = set()
    for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz"))):
        for line in gzip.open(f, "rt"):
            d = json.loads(line)
            if d["id"] in ids or d["b"] not in bodies or not d.get("url") or d.get("a") is None:
                continue
            ids.add(d["id"])
            t = at.get(d["a"])
            if t not in SCOPE or d["st"] != "ok" or not (LEN_BAND[0] <= d["n"] <= LEN_BAND[1]):
                continue
            d["a_type"] = t
            t3 = s3.pair_type(d)
            if t3 in ("intervention", "answer"):
                by[(d["b"], d["a"])][t3]["p3"].append(d)
                continue
            t6 = C6.doctype6(d.get("name"), t)
            if t6 in ("intervention", "answer"):
                by[(d["b"], d["a"])][t6]["p6"].append(d)
    out = collections.defaultdict(list)
    for (b, a), v in by.items():
        pick = {}
        for role in ("intervention", "answer"):
            lst = v[role]["p3"] or v[role]["p6"]
            if lst:
                pick[role] = min(lst, key=lambda d: d["id"])
        if len(pick) == 2:
            t = pick["intervention"]["a_type"]
            out[b].append(dict(affair=a, a_type=t, group="MP" if t in GROUPS["MP"] else "IQ",
                               question=pick["intervention"], answer=pick["answer"]))
    return out


def candidates(pl: dict, body: str, group: str, x_docs: set, x_affs: set) -> list[dict]:
    """The eligible affairs of one parliament x group in seeded order (sorted by affair id, then shuffled)."""
    c = [x for x in pl.get(body, []) if x["group"] == group and x["affair"] not in x_affs
         and x["question"]["id"] not in x_docs and x["answer"]["id"] not in x_docs]
    c.sort(key=lambda x: x["affair"])
    random.Random(f"{SEED}:{body}:{group}").shuffle(c)
    return c


def probe() -> dict:
    """Counts per parliament x group after the exclusions (what QUOTAS was written from). No affair is selected."""
    xd, xa, rep = exclusions()
    pl = pool(BODIES)
    counts = {}
    for b in BODIES:
        c = collections.Counter()
        for x in pl.get(b, []):
            if x["affair"] in xa or x["question"]["id"] in xd or x["answer"]["id"] in xd:
                continue
            c[x["group"]] += 1
            c["tagged_member_text"] += bool(x["question"].get("lang"))
        counts[b] = dict(c)
    out = dict(exclusions=rep, work_inputs=work_inputs(), counts=counts,
               note="counts of eligible affairs only; no affair was selected or opened before the LOCK9 commit")
    R8.mkdir(parents=True, exist_ok=True)
    PROBE.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["probe"]:
        print(json.dumps(probe(), indent=1))
    else:
        print(__doc__)
