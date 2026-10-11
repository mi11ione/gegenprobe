"""P8: derive each field's meaning category for one affair from (i) an annotator's label (what the documents print, labelled
blind to OPD) and (ii) OPD's metadata for that affair. Pure functions, no model, no network (eval/prereg9/PREREG9.md §4).

The value under test is the value schema v0.1 carries for the field ("carried value"): OPD's metadata value where OPD
carries one (the frozen metadata route `gegenprobe.affair.extract.from_metadata`; for the language the OPD tag of the
member's text; for the type OPD's harmonised type), else the value the documents print. Its category says what that value
denotes, judged from the documents:
  layer "opd": OPD's value is located in the annotator's inventory (people by name, dates by value) and takes the role the
               annotator gave the printed item;
  layer "doc": OPD carries no value, the category is the role of the printed value (addressed body and recommendation
               are always this layer: the product takes them from the documents).
Each result: {applicable, layer, category (one of common.CATS[field] or common.UNDET), reason (why undeterminable or
not applicable), doc_category (the document layer alone), opd_category (OPD's value alone, None when OPD carries none),
secondary (OPD vs documents agreement)}.
"""

from __future__ import annotations

import re
import statistics
import unicodedata

from eval.p8 import common as C

LODGED_ROLES = {"signed", "lodged", "session_lodged"}
ROLE_RANK = ("sole_author", "first_signatory", "joint_author", "spokesperson", "co_signatory", "supporter", "other")
ADDRESSED_ROLES = {"leading_department", "departement", "responder", "authority"}  # census.matrix.ADDRESSED_ROLES


# ------------------------------------------------------------------------------------------------ names
def fold(s: str | None) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(ch)).lower()


def toks(s: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(s))


def name_match(first: str | None, last: str | None, printed: str | None) -> bool:
    """OPD's person (first, last) is the printed name: every token of the surname is a token of the printed name, and any
    remaining printed token that could be a first name starts with the first name's initial (printed order is free:
    'Nava Andrea', 'A. Nava' and 'Andrea Nava' all match)."""
    P, L = toks(printed), toks(last)
    if not L or not P or not all(t in P for t in L):
        return False
    rest = [t for t in P if t not in L]
    F = toks(first)
    return not rest or not F or any(r[0] == F[0][0] for r in rest)


def best_role(entries: list[dict]) -> str | None:
    roles = [e.get("role") for e in entries if e.get("role") in ROLE_RANK]
    return min(roles, key=ROLE_RANK.index) if roles else None


def opd_authors(meta: dict | None) -> list[dict]:
    """OPD's `author` persons in OPD order, exactly the rows `from_metadata` reads (first = submitter, rest =
    co-signatories)."""
    if not meta:
        return []
    cons = sorted(meta.get("contributors") or [], key=lambda c: (c.get("position") or 0, c["id"]))
    return [c for c in cons if c.get("role_harmonized") == "author" and c.get("type") == "person" and c.get("fullname")]


def _match(c: dict, people: list[dict]) -> list[dict]:
    return [p for p in people if name_match(c.get("firstname"), c.get("lastname") or c.get("fullname"), p.get("name"))]


def record_kind(people: list[dict]) -> str | None:
    rec = [p for p in people if p.get("role") in ("sole_author", "first_signatory")]
    return rec[0].get("kind") if rec else None


def _res(applicable=True, layer=None, category=C.UNDET, reason=None, doc_category=None, opd_category=None, **sec):
    return dict(applicable=applicable, layer=layer, category=category, reason=reason, doc_category=doc_category,
                opd_category=opd_category, secondary=sec)


# ------------------------------------------------------------------------------------------------ submitter
def submitter_doc(people: list[dict]) -> tuple[str, str | None]:
    k = record_kind(people)
    if k is not None:
        return {"person": "author_person", "group": "group"}.get(k, "committee_or_body"), None
    if any(p.get("role") == "joint_author" and p.get("kind") == "person" for p in people):
        return "joint_person", None
    if any(p.get("role") == "spokesperson" for p in people):
        return "other", None
    return C.UNDET, "no author printed"


def _submitter_of_role(role: str | None, people: list[dict]) -> str:
    if role in ("sole_author", "first_signatory"):
        return "author_person"
    if role == "joint_author":
        return "joint_person"
    if role == "spokesperson":
        k = record_kind(people)
        return "group" if k == "group" else "committee_or_body" if k in ("committee", "other_body") else "other"
    if role in ("co_signatory", "supporter"):
        return "cosigner_person"
    return "other"


def submitter(label: dict, meta: dict | None) -> dict:
    people = label.get("people") or []
    doc_cat, doc_reason = submitter_doc(people)
    auth = opd_authors(meta)
    sec = dict(opd_name=None, opd_is_author_of_record=None)
    if not auth:
        return _res(layer="doc", category=doc_cat, reason=doc_reason, doc_category=doc_cat, **sec)
    first = auth[0]
    m = _match(first, people)
    sec["opd_name"] = f"{first.get('firstname') or ''} {first.get('lastname') or ''}".strip() or first["fullname"]
    if not m:
        sec["opd_is_author_of_record"] = False if record_kind(people) else None
        return _res(layer="opd", category=C.UNDET, reason="OPD's submitter is not printed", doc_category=doc_cat,
                    opd_category=C.UNDET, **sec)
    cat = _submitter_of_role(best_role(m), people)
    sec["opd_is_author_of_record"] = best_role(m) in ("sole_author", "first_signatory")
    return _res(layer="opd", category=cat, doc_category=doc_cat, opd_category=cat, **sec)


# ------------------------------------------------------------------------------------------------ co-signatories
def _cos_category(roles: set[str]) -> str:
    if roles & {"sole_author", "first_signatory"}:
        return "includes_author_of_record"
    if "spokesperson" in roles:
        return "signing_for_group"
    if roles == {"co_signatory"}:
        return "cosigners"
    if roles == {"supporter"}:
        return "supporters"
    if roles == {"co_signatory", "supporter"}:
        return "cosigners_and_supporters"
    if roles == {"joint_author"}:
        return "joint_authors"
    return "other"


def printed_cosignatories(people: list[dict]) -> list[dict]:
    """The co-signatory list the documents print: co-signatories, supporters, and joint authors after the first listed."""
    out, first_joint = [], True
    for p in people:
        if p.get("role") in ("co_signatory", "supporter"):
            out.append(p)
        elif p.get("role") == "joint_author":
            if first_joint and record_kind(people) is None:
                first_joint = False
                continue
            out.append(p)
    return out


def co_signatories(label: dict, meta: dict | None) -> dict:
    people = label.get("people") or []
    printed = printed_cosignatories(people)
    doc_cat = _cos_category({p["role"] for p in printed}) if printed else None
    rest = opd_authors(meta)[1:]
    sec = dict(opd_n=len(rest), printed_n=len(printed), jaccard=None)
    if rest:
        roles, matched = set(), 0
        for c in rest:
            m = _match(c, people)
            if m:
                matched += 1
                roles.add(best_role(m))
        pk = {(toks(p.get("name")) or [""])[-1] for p in printed}
        ok = {(toks(c.get("lastname") or c.get("fullname")) or [""])[-1] for c in rest}
        sec.update(jaccard=round(len(pk & ok) / len(pk | ok), 3) if (pk | ok) else None, opd_matched=matched)
        if not roles:
            return _res(layer="opd", category=C.UNDET, reason="none of OPD's co-signatories is printed",
                        doc_category=doc_cat, opd_category=C.UNDET, **sec)
        cat = _cos_category(roles)
        return _res(layer="opd", category=cat, doc_category=doc_cat, opd_category=cat, **sec)
    if not printed:
        return _res(applicable=False, reason="no co-signatory in OPD or in the documents", **sec)
    return _res(layer="doc", category=doc_cat, doc_category=doc_cat, **sec)


# ------------------------------------------------------------------------------------------------ submission date
def date_roles(label: dict, datelist: dict[str, str]) -> tuple[dict[str, set], set[str]]:
    """(iso date -> roles the annotator gave it, every printed date: the parser's list plus the annotator's extra dates)."""
    roles: dict[str, set] = {}
    for letter, rs in (label.get("dates") or {}).items():
        d = datelist.get(letter)
        if d:
            roles.setdefault(d, set()).update(r for r in rs if r in C.DATE_ROLES)
    printed = set(datelist.values())
    for x in label.get("extra_dates") or []:
        if x.get("date"):
            printed.add(x["date"])
            roles.setdefault(x["date"], set()).update(r for r in x.get("roles") or [] if r in C.DATE_ROLES)
    return roles, printed


def date_category(d: str, roles: dict[str, set], printed: set[str]) -> str:
    R = roles.get(d, set())
    if R & LODGED_ROLES:
        return "lodged"
    if "cited" in R:
        return "cited"
    if "later_step" in R:
        return "later_step"
    if "answer_or_decision" in R:
        return "answer_or_decision"
    if R or d in printed:
        return "other_printed"
    if any(rs & LODGED_ROLES for rs in roles.values()):
        return "unprinted_differs"
    return C.UNDET


def _days(a: str, b: str) -> int:
    import datetime as dt

    return (dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days


def date_submission(label: dict, meta: dict | None, datelist: dict[str, str]) -> dict:
    roles, printed = date_roles(label, datelist)
    lodged = sorted(d for d, rs in roles.items() if rs & LODGED_ROLES)
    doc_cat = "lodged" if lodged else C.UNDET
    opd = None
    if meta:
        from gegenprobe.affair.extract import from_metadata

        v = from_metadata(meta, None)["submitted"]
        opd = v.get("value")
    sec = dict(opd_date=opd, earliest_printed_lodged=lodged[0] if lodged else None, offset_days=None)
    if opd is None:
        return _res(layer="doc", category=doc_cat, reason=None if lodged else "no lodging date printed",
                    doc_category=doc_cat, **sec)
    if lodged:
        sec["offset_days"] = _days(opd, lodged[0])
    cat = date_category(opd, roles, printed)
    reason = "OPD's date is not printed and no lodging date is printed" if cat == C.UNDET else None
    return _res(layer="opd", category=cat, reason=reason, doc_category=doc_cat, opd_category=cat, **sec)


# ------------------------------------------------------------------------------------------------ addressed body
def addressed_body(label: dict, meta: dict | None) -> dict:
    v = (label.get("addressed_body") or {}).get("value")
    dept = [c.get("fullname") for c in (meta or {}).get("contributors") or [] if c.get("role_harmonized") in ADDRESSED_ROLES]
    sec = dict(opd_department=bool(dept))
    if v in (None, "none_printed"):
        return _res(layer="doc", reason="no addressee printed", doc_category=C.UNDET, **sec)
    return _res(layer="doc", category=v, doc_category=v, **sec)


# ------------------------------------------------------------------------------------------------ language
def language_category(tag: str | None, text_langs: list[str]) -> tuple[str, str | None]:
    if not tag:
        return C.UNDET, "OPD tags no language"
    T = {t.strip().lower() for t in tag.split(";") if t.strip()}
    P = {x for x in text_langs or [] if x in C.LANGS}
    if not P:
        return C.UNDET, "text language not labelled"
    if not T <= set(C.LANGS):
        return "invalid_tag", None
    if T == P:
        return "text_language", None
    if T < P:
        return "subset_of_text", None
    if T > P:
        return "superset_of_text", None
    return "other_language", None


def language(label: dict, entry: dict) -> dict:
    docs = {d["role"]: d for d in entry["docs"]}
    langs = label.get("languages") or {}
    cat, why = language_category(docs["question"].get("opd_lang"), langs.get("question") or [])
    acat, _ = language_category(docs["answer"].get("opd_lang"), langs.get("answer") or [])
    return _res(layer="opd", category=cat, reason=why, doc_category=None, opd_category=cat,
                answer_doc_category=acat, question_tag=docs["question"].get("opd_lang"),
                answer_tag=docs["answer"].get("opd_lang"))


# ------------------------------------------------------------------------------------------------ recommendation
def government_recommendation(label: dict, meta: dict | None, entry: dict) -> dict:
    rec = label.get("recommendation") or {}
    opd = None
    if meta:
        from gegenprobe.affair.extract import from_metadata

        opd = from_metadata(meta, None)["recommendation"].get("value")
    sec = dict(opd_value=opd, printed_value=rec.get("value"), fits=rec.get("fits"))
    if entry["affair_type"] not in C.GROUPS["MP"]:
        return _res(applicable=False, reason="not a Motion or Postulate in OPD", **sec)
    if label.get("answer_doc") != "executive_answer":
        return _res(layer="doc", reason="the answer document is not the executive's answer", doc_category=C.UNDET, **sec)
    act = rec.get("act")
    if act in ("none_printed", "not_applicable", None):
        return _res(layer="doc", reason=f"recommendation {act or 'missing'}", doc_category=C.UNDET, **sec)
    return _res(layer="doc", category=act, doc_category=act, **sec)


# ------------------------------------------------------------------------------------------------ type
def type_(label: dict, entry: dict) -> dict:
    t = entry["affair_type"]
    f = (label.get("function") or {}).get("value")
    named = (label.get("instrument_named") or {}).get("value")
    sec = dict(opd_type=t, function=f, instrument_named=named,
               name_agrees=None if named in (None, "none") else named == C.TYPE_WORD[t])
    if f in (None, "unclear"):
        return _res(layer="opd", reason="function unclear", opd_category=C.UNDET, **sec)
    cat = "conforms" if f == C.TYPE_FUNCTION[t] else f
    return _res(layer="opd", category=cat, opd_category=cat, doc_category=f, **sec)


# ------------------------------------------------------------------------------------------------ all fields
def derive(label: dict, entry: dict, meta: dict | None, datelist: dict[str, str]) -> dict[str, dict]:
    return {
        "submitter": submitter(label, meta),
        "co_signatories": co_signatories(label, meta),
        "date_submission": date_submission(label, meta, datelist),
        "addressed_body": addressed_body(label, meta),
        "language": language(label, entry),
        "government_recommendation": government_recommendation(label, meta, entry),
        "type": type_(label, entry),
    }


def key(res: dict) -> str:
    """The disagreement key of one field: its category (or not applicable)."""
    return res["category"] if res["applicable"] else "n/a"


def median_iqr(xs: list[int]) -> dict | None:
    if not xs:
        return None
    q = statistics.quantiles(xs, n=4) if len(xs) > 1 else [xs[0]] * 3
    return dict(n=len(xs), median=statistics.median(xs), q1=q[0], q3=q[2])
