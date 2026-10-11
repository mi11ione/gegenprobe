"""Candidate authors of one affair, located in its documents by code. No model, no network.

    role_candidates.candidates(q_pages, a_pages, roster=[(first, last), ...]) -> list[dict]

P10 (eval/prereg10/PREREG10.md) separates WHO is printed from WHAT ROLE they have. This module answers the first
question and only that: it returns every person or body the documents print that could be an author of the intervention,
each with the span it is printed at. The role is decided elsewhere (the Apertus role pointer, `convert.roles_pointer`, or
a no-model baseline); every arm that needs candidates gets exactly this list.

Sources (a candidate may come from several; `sources` lists them):
  rules      every actor the frozen converter rules print (`convert.roles.authors`), whatever role they give it;
  blocks     the frozen rules' located name blocks, all of them and not only the first that fires: labelled author,
             first-signatory, co-signatory and supporter blocks, the heading forms, the closing signatures (and a group
             printed above them), the Bern / Vaud forms, the Valais "durch" line, the Thurgau address blocks and the
             answer's heading;
  roster     a person of the parliament's OPD contributor list (first and last name, as OPD publishes them; no other
             personal field) printed in the member's text, or in the first ROSTER_ANSWER_CHARS characters of the answer,
             with a cue that it is that person: the first name or its initial next to the surname ("Anna Muster",
             "A. Muster", "Muster Anna", "MUSTER Anna"), or a title right before it ("Frau Muster", "M. Muster",
             "Grossrat Muster", "député Muster"), or "et consorts / und Mitunterzeichnende / e cofirmatari" right
             after it, or a line that holds only the name (at most four words, no digit);
  group      a parliamentary group printed as a phrase ("SP-Fraktion", "Fraktion der SVP", "groupe PLR", "gruppo PS",
             "Per il Gruppo PLR") in the head (GROUP_HEAD_CHARS) or the closing (GROUP_TAIL_CHARS) of the member's text
             or in the answer's head;
  committee  a committee of the parliament printed as a line of its own in the head (COMMITTEE_HEAD_CHARS) or the
             closing (GROUP_TAIL_CHARS) of the member's text ("Kommission für Planung", "PER LA COMMISSIONE DEL PIANO
             REGOLATORE").
Persons are merged when `roles.same_person` says they are one person; the merged candidate keeps the most complete
printed form (most name tokens, then the earliest) as its value and up to MAX_OCCURRENCES located occurrences. Order: the
member's text before the answer, then page and offset of the first occurrence. At most MAX_CANDIDATES are kept (the
rest is counted in `dropped`).

A candidate: {value, doc, page, char_start, char_end, quote_sha256, kind (person | parliamentary_group | committee),
sources, occurrences: [{doc, page, char_start, char_end}], n_occurrences}. `value` is the printed text at the span with
whitespace collapsed.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from . import roles as R

CAND_VERSION = "rolecand-1"
MAX_CANDIDATES = 60
MAX_OCCURRENCES = 3
ROSTER_ANSWER_CHARS = 3000
GROUP_HEAD_CHARS = 2500
GROUP_TAIL_CHARS = 2000
COMMITTEE_HEAD_CHARS = 1200
ANSWER_HEAD_CHARS = 3000

_TITLE_BEFORE = re.compile(
    r"(?:\b(?:Herrn?|Frau|Dr\.|Prof\.|KR|GR|LR|Grossrat|Grossrätin|Grossr[äa]tin|Kantonsrat|Kantonsrätin|Landrat|"
    r"Landrätin|Gemeinderat|Gemeinderätin|Stadtrat|Stadträtin|Einwohnerrat|Einwohnerrätin|Ratsmitglied|Kollege|Kollegin|"
    r"Mme|Mlle|MM\.|député|députée|conseiller|conseillère|Monsieur|Madame|consigliere|consigliera|deputato|deputata|"
    r"signor|signora|on\.|avv\.|dott\.|ing\.|lic\.)|\bM\.)[ \t]+$")
_GROUP = re.compile(
    r"(?:\b[\w\-/]{1,30}-Fraktion\b|\bFraktion[ \t]+(?:der[ \t]+|des[ \t]+)?[A-ZÀ-Þ][\w\-/.]*(?:[ \t]+[A-ZÀ-Þ][\w\-/.]*){0,2}|"
    r"\b(?:[Gg]roupe|[Gg]ruppo|[Ff]razione|[Ff]racziun|[Gg]ruppa)[ \t]+(?:(?:du|des|de la|de l['’]|del|della|dei|dal)"
    r"[ \t]+)?[A-ZÀ-Þ][\w\-/.’']*(?:[ \t]*/[ \t]*[\w\-.]+)?(?:[ \t]+[A-ZÀ-Þ][\w\-/.’']*){0,2})")
_COMMITTEE = re.compile(  # a committee's name as a line of its own (a heading or a signature), not in prose
    r"(?mi)^[ \t]*(?:(?:per[ \t]+la|pour[ \t]+la|für[ \t]+die|namens[ \t]+der|au[ \t]+nom[ \t]+de[ \t]+la|la|le|die|il)[ \t]+)?"
    r"(?P<c>(?:Kommission|Commission|Commissione|Cumissiun|Ausschuss)\b[^\n,;:()]{0,60})[ \t]*$")
_CONSORTS_AFTER = re.compile(r"[ \t\n]+(?:et[ \t\n]+consorts|und[ \t\n]+Mitunterzeichnende|e[ \t\n]+cofirmatari|und[ \t\n]+"
                             r"Konsorten)\b")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _val(doc: str, pno: int, page: str, s: int, e: int, rule: str) -> dict:
    q = page[s:e]
    return dict(value=re.sub(r"\s+", " ", q).strip(), doc=doc, page=pno, char_start=s, char_end=e,
                quote_sha256=hashlib.sha256(q.encode("utf-8")).hexdigest(), rule=rule)


def _from_rule_value(v: dict, source: str) -> dict:
    return dict(value=v["value"], doc=v["doc"], page=v["page"], char_start=v["char_start"], char_end=v["char_end"],
                quote_sha256=v["quote_sha256"], rule=f"{source}:{v.get('rule', '')}")


# ------------------------------------------------------------------------------------------------------------ sources
def from_rules(q: list[str], a: list[str]) -> list[dict]:
    actors, _ = R.authors(q, a)
    return [dict(_from_rule_value(x["name"], "rules"), kind=x["kind"], source="rules") for x in actors]


def from_blocks(q: list[str], a: list[str]) -> list[dict]:
    """Every located name block of the frozen rules, not only the first that fires in their cascade."""
    out: list[dict] = []

    def add(vals, kind=None):
        for v in vals:
            if isinstance(v, dict) and "name" in v and "role" in v:  # an actor
                out.append(dict(_from_rule_value(v["name"], "blocks"), kind=v["kind"], source="blocks"))
            elif isinstance(v, dict) and "value" in v:
                out.append(dict(_from_rule_value(v, "blocks"), kind=kind or R._kind(v["value"]), source="blocks"))

    if q:
        add(R._table_authors(q, "question"))
        add(R._durch(q, "question"))
        add(R._vd_form(q, "question"))
        add(R._address_blocks(q, "question"))
        for _, vals in R._label_blocks(q, "question", R.AUTHOR_LABELS + R.FIRST_LABELS + R.CO_LABELS + R.SUPPORT_LABELS):
            add(vals)
        add(R._heading_authors(q))
        names, _, groups = R._closing_block(q, "question")
        add(names)
        add(groups, kind="parliamentary_group")
    if a:
        ah = R._answer_head(a)
        if ah:
            add([ah[0]])
    return out


def _roster_index(roster) -> tuple[re.Pattern | None, dict[str, list[tuple[str, str]]]]:
    by_last: dict[str, list[tuple[str, str]]] = {}
    for first, last in roster:
        last = (last or "").strip()
        if len(last) < 2:
            continue
        by_last.setdefault(_fold(last), []).append(((first or "").strip(), last))
    if not by_last:
        return None, by_last
    alts = sorted({re.escape(k) for k in by_last}, key=len, reverse=True)
    # matched on the folded page (same length as the page for Latin letters; checked per hit)
    return re.compile(r"(?<![\w\-])(?:" + "|".join(alts).replace(r"\ ", r"[ \t\n]+") + r")(?![\w\-])"), by_last


def _first_cue(first: str, before: str, after: str) -> tuple[int, int] | None:
    """(chars before the surname, chars after it) the first name or its initial takes, or None."""
    toks = [t for t in re.split(r"[\s]+", first) if t]
    if not toks:
        return None
    f0 = _fold(toks[0])
    fb, fa = _fold(before), _fold(after)
    full = r"[ \t]+".join(re.escape(_fold(t)) for t in toks)
    for rx in (rf"(?:{full}|{re.escape(f0)})[ \t\n]+(?:(?:von|van|de|di|da|del|della|le|la|du|des)[ \t]+)?$",
               rf"{re.escape(f0[0])}\.[ \t]*(?:[a-z]\.[ \t]*)?$"):
        m = re.search(rx, fb)
        if m and (m.start() == 0 or not fb[m.start() - 1].isalpha()):
            return len(fb) - m.start(), 0
    m = re.match(rf"[ \t]*,?[ \t]*(?:{full}|{re.escape(f0)})(?![\w])", fa)
    if m:
        return 0, m.end()
    return None


def from_roster(pages: list[str], doc: str, roster, limit: int | None = None) -> list[dict]:
    rx, by_last = _roster_index(roster)
    out: list[dict] = []
    if rx is None:
        return out
    for pno, page in enumerate(pages, 1):
        if limit is not None and pno > 1:
            break
        text = page if limit is None else page[:limit]
        folded = _fold(text)
        if len(folded) != len(text):  # a letter that folds to several characters: fold per character instead
            folded = "".join(_fold(c)[:1] or c for c in text)
        for m in rx.finditer(folded):
            s, e = m.start(), m.end()
            if not text[s:s + 1].isupper():
                continue
            key = re.sub(r"[ \t\n]+", " ", folded[s:e])
            before, after = text[max(0, s - 40):s], text[e:e + 40]
            hit = None
            for first, _last in by_last.get(key, []):
                c = _first_cue(first, before, after)
                if c:
                    hit = (s - c[0], e + c[1], "first_name")
                    break
            if hit is None and _TITLE_BEFORE.search(before):
                hit = (s, e, "title")
            if hit is None and _CONSORTS_AFTER.match(text, e):
                hit = (s, e, "et_consorts")
            if hit is None:  # a line that is only a name ("Ronnie David", an OCR-damaged "brÎvier Thorens")
                ls = text.rfind("\n", 0, s) + 1
                le = text.find("\n", e)
                le = len(text) if le < 0 else le
                line = text[ls:le].strip()
                if 1 <= len(line.split()) <= 4 and not re.search(r"[\d:;?!]", line) and line.endswith(text[s:e]):
                    ls += len(text[ls:le]) - len(text[ls:le].lstrip())
                    hit = (ls, ls + len(line), "name_line")
            if hit is None:
                continue
            a_, b_ = hit[0], hit[1]
            while a_ < b_ and text[a_] in " \t\n,":
                a_ += 1
            while b_ > a_ and text[b_ - 1] in " \t\n,":
                b_ -= 1
            out.append(dict(_val(doc, pno, page, a_, b_, f"roster:{hit[2]}"), kind="person", source="roster"))
    return out


def from_groups(q: list[str], a: list[str]) -> list[dict]:
    out: list[dict] = []
    spots = []
    if q:
        spots.append(("question", 1, q[0], 0, min(len(q[0]), GROUP_HEAD_CHARS)))
        last = q[-1]
        spots.append(("question", len(q), last, max(0, len(last) - GROUP_TAIL_CHARS), len(last)))
    if a:
        spots.append(("answer", 1, a[0], 0, min(len(a[0]), ANSWER_HEAD_CHARS)))
    seen = set()
    for doc, pno, page, s0, e0 in spots:
        for m in _GROUP.finditer(page, s0, e0):
            s, e = R._clean_span(page, m.start(), m.end())
            if e - s < 4 or (doc, pno, s) in seen:
                continue
            seen.add((doc, pno, s))
            out.append(dict(_val(doc, pno, page, s, e, "group:phrase"), kind="parliamentary_group", source="group"))
    if q:
        for pno, page, s0, e0 in ((1, q[0], 0, min(len(q[0]), COMMITTEE_HEAD_CHARS)),
                                  (len(q), q[-1], max(0, len(q[-1]) - GROUP_TAIL_CHARS), len(q[-1]))):
            for m in _COMMITTEE.finditer(page, s0, e0):
                s, e = m.start("c"), m.end("c")
                while e > s and page[e - 1] in " \t.,;:":
                    e -= 1
                if e - s >= 8 and (pno, s) not in seen:
                    seen.add((pno, s))
                    out.append(dict(_val("question", pno, page, s, e, "committee:line"), kind="committee",
                                    source="committee"))
    return out


# ------------------------------------------------------------------------------------------------------------ merge
def _ntoks(v: str) -> int:
    return len(R.norm_name(v))


def _same(x: dict, y: dict) -> bool:
    if x["kind"] == "person" and y["kind"] == "person":
        return R.same_person(x["value"], y["value"])
    if x["kind"] != y["kind"]:
        return False
    return R._norm_group(_fold(x["value"])) == R._norm_group(_fold(y["value"]))


def _order(c: dict) -> tuple:
    return (0 if c["doc"] == "question" else 1, c["page"], c["char_start"])


def candidates(q: list[str] | None, a: list[str] | None, roster=()) -> dict:
    """{version, candidates, dropped, n_raw}: the merged candidates of one affair (module docstring)."""
    q, a = q or [], a or []
    raw = from_rules(q, a) + from_blocks(q, a) + from_roster(q, "question", roster) + \
        from_roster(a, "answer", roster, limit=ROSTER_ANSWER_CHARS) + from_groups(q, a)
    raw = [r for r in raw if r["value"] and (r["kind"] != "person" or _ntoks(r["value"]) >= 1)]
    raw.sort(key=_order)
    merged: list[dict] = []
    for r in raw:
        tgt = next((m for m in merged if _same(m, r)), None)
        occ = dict(doc=r["doc"], page=r["page"], char_start=r["char_start"], char_end=r["char_end"])
        if tgt is None:
            merged.append(dict({k: r[k] for k in ("value", "doc", "page", "char_start", "char_end", "quote_sha256",
                                                  "kind")}, sources=[r["source"]], occurrences=[occ]))
            continue
        if r["source"] not in tgt["sources"]:
            tgt["sources"].append(r["source"])
        if occ not in tgt["occurrences"]:
            tgt["occurrences"].append(occ)
        if _ntoks(r["value"]) > _ntoks(tgt["value"]):  # keep the most complete printed form as the value
            tgt.update({k: r[k] for k in ("value", "doc", "page", "char_start", "char_end", "quote_sha256")})
    for m in merged:
        m["occurrences"].sort(key=lambda o: (0 if o["doc"] == "question" else 1, o["page"], o["char_start"]))
        m["n_occurrences"] = len(m["occurrences"])
        m["occurrences"] = m["occurrences"][:MAX_OCCURRENCES]
        m["sources"] = sorted(m["sources"])
    merged.sort(key=lambda m: _order(m["occurrences"][0]))
    return dict(version=CAND_VERSION, candidates=merged[:MAX_CANDIDATES], dropped=max(0, len(merged) - MAX_CANDIDATES),
                n_raw=len(raw))
