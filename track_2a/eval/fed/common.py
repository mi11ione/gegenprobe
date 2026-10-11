"""Federal cell (eval/fed/PROTOCOL.md): an EXPLORATORY check of the converter and of four schema fields on the federal
parliament (OPD body CHE). Model-free. This module fixes what the protocol fixes: the frame, the strata, the seeds, the
paths, the text conversion and the exclusions.

    PYTHONPATH=src:. .venv/bin/python -m eval.fed.common scan    network (once, before the lock): one streamed request
                                                                  for OPD's texts_CHE export -> WORK/fed/texts_che_meta.jsonl.gz
                                                                  (per text row and language slot: length, sha256 of the
                                                                  stored HTML, the converter's language guess, the number of
                                                                  dates the converter's date lattice finds; never text)
    PYTHONPATH=src:. .venv/bin/python -m eval.fed.common probe   no network: -> results/fed/pool_probe.json (counts only)

Where federal answers live in OPD. OPD's docs_CHE export holds Federal Gazette / Official Compilation publications
(messages, decrees; most stored as Fedlex's "JavaScript required" page, resolved by gegenprobe.repair.che). The Federal
Council's answers to members' interventions are not documents: they are rows of the separate `texts` export (Curia
Vista's "Antwort BR / Büro", "Réponse CF / Bureau", "Risposta del CF / Ufficio"), one row per text, each row carrying
one HTML version per language slot (`text_de`, `text_fr`, `text_it`, `text_rm`). The member's intervention is the
"Eingereichter Text" row (+ "Begründung" where the instrument has one). The texts carry no date (`text_date` is null
for every row of these types); OPD's events carry the Federal Council's dates.

Frame (an affair qualifies when all hold; computed from the scan file and OPD's committed-snapshot exports in
GP_OPD_RAW, never from text):
  * OPD body CHE, harmonised type Interpellation, Motion, Postulate or Question (P8's scope; question time excluded);
  * a recorded Federal Council answer: an answer text row in the texts export ("Antwort BR / Büro" and its FR/IT
    labels), and the affair is not answered by another body (an affair whose only written-answer events name the
    Bureau, a supervisory authority or a federal court is out; census `classify_event` == "written"). OPD's events
    carry a Federal Council answer event for only part of these affairs (most interpellations and questions have the
    answer text and no answer event); both kinds qualify and the probe counts each;
  * one submitted-text row (the lowest row id; the answer likewise), plus the reasoning row if present;
  * at least one language slot L in {de, fr, it} that is a GENUINE version: the answer in slot L has 200-40,000
    characters (census MIN_DOC_CHARS; P8's upper bound) and the converter's language guess on it is L, and the member's
    text in slot L (submitted text + reasoning) has >= 200 characters and the guess on it is L;
  * not in any existing gold, dev, test or audit set (P8's frozen exclusions plus the P8 sample).
Stratum (the language of the answer). Most federal answers are published in three genuine language versions (the
Federal Council's text in German, French and Italian), so an answer has no single language in OPD; what an affair can be
tested in is a language version. Each eligible affair is assigned ONE stratum, the language version its packet shows:
a seeded uniform choice among its genuine slots (`stratum`: random.Random(f"{SEED}:slot:{affair}")), fixed before the
draw and independent of any outcome. A choice by priority (e.g. Italian whenever genuine) would leave German and French
only the older affairs whose Italian version is missing.
"""

from __future__ import annotations

import collections
import gzip
import hashlib
import html as H
import json
import re
import sys

from gegenprobe.paths import DATA, OPD_RAW, RESULTS, WORK

# ------------------------------------------------------------------------------------------------ paths
DF = DATA / "fed"
WF = WORK / "fed"
RF = RESULTS / "fed"
TEXTS_URL = "https://files.openparldata.ch/exports/texts/texts_CHE.ndjson.gz"
INDEX_URL = "https://files.openparldata.ch/exports/index.json"
SCAN = WF / "texts_che_meta.jsonl.gz"  # per row and slot: n, sha256 of the stored HTML, language guess, n dates (no text)
SCAN_INFO = WF / "texts_che_scan.json"  # the export's index entry (created, size, row count) and the bytes streamed
PROBE = RF / "pool_probe.json"
AFFAIRS = DF / "fed_affairs.jsonl"  # drawn affairs: ids, number, type, stratum, row ids, sha256s, lengths; never text
FETCH_LOG = DF / "fed_fetch_log.jsonl"
META = DF / "opd_meta_fed.jsonl"  # OPD affair row, events, contributors (frozen gegenprobe.affair.meta.vendor)
NAMES = DF / "body_names_fed.json"
DATELISTS = DF / "fed_datelists.jsonl"  # per packet: the parser's distinct dates with doc/page positions (no text)
GOLD = DF / "fed_gold.jsonl"
ANN_COMMITTED = DF / "annotations"
KEY = WF / "key.jsonl"  # packet id -> affair id, stratum, type (kept in WORK until the gold is merged)
TEXTS = WF / "texts"  # the drawn affairs' text rows as fetched (WORK only, never committed)
PACK = WF / "packets"
ANN = WF / "ann"
TABLES = RF / "fed_tables.json"

# ------------------------------------------------------------------------------------------------ seeds, strata, sizes
SEED = 20261050  # draw (per stratum x group seeded order) and packet-id shuffle
SEED_A3 = 20261051  # X/Y order of the tie-break packets
STRATA = ("de", "fr", "it")
GROUPS = {"MP": ("Motion", "Postulate"), "IQ": ("Interpellation", "Question")}
SCOPE = {t for v in GROUPS.values() for t in v}
# (stratum, n Motion/Postulate, n Interpellation/Question): 5 per language, 15 affairs (written from pool_probe.json)
QUOTAS = [("de", 2, 3), ("fr", 2, 3), ("it", 2, 3)]
ANSWER_BAND = (200, 40000)
MEMBER_MIN = 200

TYPE_MEMBER = {"Eingereichter Text", "Texte déposé", "Testo depositato"}
TYPE_REASON = {"Begründung", "Développement", "Motivazione"}
TYPE_ANSWER = {"Antwort BR / Büro", "Réponse CF / Bureau", "Risposta del CF / Ufficio"}
TYPE_TITLE = {"Titel des Geschäftes", "Titre de l'objet", "Titolo dell'oggetto"}
NOT_FC = re.compile(r"büro|bureau|ufficio|aufsichtsbeh|bundesgericht|tribunal f[ée]d[ée]ral|tribunale federale", re.I)
SLOTS = ("de", "fr", "it", "rm")


# ------------------------------------------------------------------------------------------------ text conversion
_BLOCK = re.compile(r"(?i)<\s*(?:br|/p|/div|/li|/h[1-6]|/tr|/ul|/ol|p|li|div|tr|h[1-6])\b[^>]*>")


def plain(html_s: str | None) -> str:
    """OPD's stored HTML -> plain text, deterministically: block tags become line breaks, other tags are dropped, entities
    are decoded, runs of spaces collapse, blank-line runs collapse to one."""
    if not html_s:
        return ""
    s = _BLOCK.sub("\n", html_s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = H.unescape(s).replace("\xa0", " ").replace("\r", "\n")
    out: list[str] = []
    for ln in s.split("\n"):
        ln = re.sub(r"[ \t\f\v]+", " ", ln).strip()
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def sha(s: str | None) -> str | None:
    return hashlib.sha256(s.encode("utf-8")).hexdigest() if s else None


def guess(text: str) -> str | None:
    """The converter's own language guess (gegenprobe.convert.batch.guess_lang) on texts of >= 200 characters."""
    from gegenprobe.convert.batch import guess_lang

    return guess_lang(text) if len(text) >= 200 else None


def n_dates(text: str) -> int:
    from gegenprobe.convert import lattice

    return len(lattice.distinct_dates(lattice.dates([text]))) if text else 0


def row_type(d: dict) -> str | None:
    return d.get("type_de") or d.get("type_fr") or d.get("type_it")


def slot_meta(d: dict) -> dict:
    """Per language slot: plain-text length and sha256 of the stored HTML; for member, reasoning and answer rows also the
    converter's language guess and the number of distinct dates its lattice finds."""
    full = row_type(d) in TYPE_MEMBER | TYPE_REASON | TYPE_ANSWER
    out = {}
    for L in SLOTS:
        raw = d.get(f"text_{L}")
        t = plain(raw)
        if not t:
            out[L] = dict(n=0)
        elif full:
            out[L] = dict(n=len(t), sha=sha(raw), lang=guess(t), nd=n_dates(t))
        else:
            out[L] = dict(n=len(t), sha=sha(raw))
    return out


# ------------------------------------------------------------------------------------------------ scan (network, once)
def scan() -> dict:
    from gegenprobe.compliance import fetchguard

    fetchguard.ensure()  # fail-closed: no request without the RFC 9309 matcher
    from gegenprobe import net
    from gegenprobe.census.scan import stream_counted

    idx = json.loads(net.get(INDEX_URL))
    ent = next(f for e in idx["files"] if e.get("entity") == "texts" for f in e.get("files", [])
               if f["filename"] == "texts_CHE.ndjson.gz")
    WF.mkdir(parents=True, exist_ok=True)
    tally: dict = {}
    n = 0
    with gzip.open(SCAN, "wt", encoding="utf-8") as out:
        for line in stream_counted(TEXTS_URL, tally):
            d = json.loads(line)
            n += 1
            out.write(json.dumps(dict(id=d["id"], a=d.get("affair_id"), b=d.get("body_key"), type=row_type(d),
                                      date=d.get("text_date"), slots=slot_meta(d)), ensure_ascii=False) + "\n")
    info = dict(index_generated_at=idx.get("generated_at"), entry={k: ent.get(k) for k in ("filename", "url", "size",
                "row_count", "created")}, rows=n, bytes_streamed=tally.get("bytes"), local=tally.get("local"),
                scan_sha256=hashlib.sha256(SCAN.read_bytes()).hexdigest())
    SCAN_INFO.write_text(json.dumps(info, indent=1) + "\n")
    return info


def scan_rows():
    with gzip.open(SCAN, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


# ------------------------------------------------------------------------------------------------ frame
def _rows(name: str):
    with gzip.open(OPD_RAW / f"{name}.ndjson.gz", "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def fc_answer_events(evs: list[dict]) -> list[dict]:
    from gegenprobe.census import defs

    return [e for e in evs if e.get("date") and defs.classify_event(defs.event_title(e), e.get("title_harmonized_id"))
            == "written" and not NOT_FC.search(defs.event_title(e))]


def other_body_events(evs: list[dict]) -> list[dict]:
    """Written-answer events of another answering body (the Bureau, a supervisory authority, a federal court)."""
    from gegenprobe.census import defs

    return [e for e in evs if defs.classify_event(defs.event_title(e), e.get("title_harmonized_id")) == "written"
            and NOT_FC.search(defs.event_title(e))]


def genuine(ans: dict, member: dict, L: str) -> bool:
    a, m = ans["slots"].get(L) or {}, member.get(L) or {}
    return (ANSWER_BAND[0] <= a.get("n", 0) <= ANSWER_BAND[1] and a.get("lang") == L
            and m.get("n", 0) >= MEMBER_MIN and m.get("lang") == L)


def stratum(affair: int, g: dict[str, bool]) -> str | None:
    """The language version an affair is tested in: a seeded uniform choice among its genuine slots (None if none)."""
    import random

    ok = [L for L in STRATA if g.get(L)]
    return random.Random(f"{SEED}:slot:{affair}").choice(ok) if ok else None


def member_slots(rows: list[dict]) -> dict[str, dict]:
    """The member's text per slot: the submitted-text row + the reasoning row (lengths add; the language guess is the
    submitted text's, else the reasoning's)."""
    out = {}
    for L in SLOTS[:3]:
        parts = [r["slots"].get(L) or {} for r in rows]
        n = sum(p.get("n", 0) for p in parts)
        lang = next((p.get("lang") for p in parts if p.get("lang")), None)
        out[L] = dict(n=n, lang=lang)
    return out


def exclusions() -> tuple[set[int], dict]:
    from eval.p8 import common as C8

    _docs, affs, rep = C8.exclusions()
    p8 = {r["affair_id"] for r in C8._jsonl(C8.AFFAIRS)}
    return affs | p8, dict(rep, p8_sample=len(p8))


def frame() -> tuple[list[dict], dict]:
    """The qualifying affairs (sorted by affair id) and the frame's counts."""
    aff = {a["id"]: a for a in _rows("affairs") if a.get("body_key") == "CHE"}
    scope = {i: a for i, a in aff.items() if a.get("type_harmonized_en") in SCOPE}
    evs = collections.defaultdict(list)
    for e in _rows("events"):
        if e.get("affair_id") in scope:
            evs[e["affair_id"]].append(e)
    by = collections.defaultdict(lambda: dict(member=[], reason=[], answer=[], title=[]))
    for r in scan_rows():
        if r.get("a") not in scope:
            continue
        t = r.get("type")
        k = ("member" if t in TYPE_MEMBER else "reason" if t in TYPE_REASON else "answer" if t in TYPE_ANSWER
             else "title" if t in TYPE_TITLE else None)
        if k:
            by[r["a"]][k].append(r)
    x_affs, rep = exclusions()
    c = collections.Counter()
    out = []
    for i in sorted(scope):
        a = scope[i]
        t = a["type_harmonized_en"]
        c[f"scope:{t}"] += 1
        fc = fc_answer_events(evs.get(i, []))
        other = other_body_events(evs.get(i, []))
        rows = by.get(i)
        has_text = bool(rows and rows["answer"])
        c[f"recorded:{'event' if fc else 'no_event'}+{'text' if has_text else 'no_text'}:{t}"] += 1
        if not has_text:
            continue
        if other and not fc:
            c[f"answered_by_another_body:{t}"] += 1
            continue
        if not rows["member"]:
            c[f"no_member_text:{t}"] += 1
            continue
        if i in x_affs:
            c["excluded"] += 1
            continue
        ans = min(rows["answer"], key=lambda r: r["id"])
        mem = min(rows["member"], key=lambda r: r["id"])
        rea = min(rows["reason"], key=lambda r: r["id"]) if rows["reason"] else None
        ms = member_slots([mem] + ([rea] if rea else []))
        g = {L: genuine(ans, ms, L) for L in STRATA}
        s = stratum(i, g)
        if s is None:
            c[f"no_genuine_slot:{t}"] += 1
            continue
        grp = "MP" if t in GROUPS["MP"] else "IQ"
        c[f"eligible:{s}:{grp}"] += 1
        out.append(dict(affair=i, number=a.get("number"), a_type=t, group=grp, stratum=s, genuine=g,
                        answer_row=ans["id"], member_row=mem["id"], reason_row=rea["id"] if rea else None,
                        title_row=min(rows["title"], key=lambda r: r["id"])["id"] if rows["title"] else None,
                        sha={"answer": ans["slots"][s].get("sha"), "member": mem["slots"].get(s, {}).get("sha"),
                             "reason": (rea["slots"].get(s) or {}).get("sha") if rea else None},
                        answer_chars=ans["slots"][s]["n"], answer_dates=ans["slots"][s].get("nd", 0),
                        fc_event_dates=sorted({e["date"][:10] for e in fc}), recorded_by_event=bool(fc),
                        n_answer_rows=len(rows["answer"]),
                        answer_slot_lang={L: (ans["slots"].get(L) or {}).get("lang") for L in STRATA}))
    return out, dict(counts=dict(sorted(c.items())), exclusions=rep)


def candidates(fr: list[dict], s: str, group: str) -> list[dict]:
    """The eligible affairs of one stratum x group in seeded order (sorted by affair id, then shuffled)."""
    import random

    c = sorted((x for x in fr if x["stratum"] == s and x["group"] == group), key=lambda x: x["affair"])
    random.Random(f"{SEED}:{s}:{group}").shuffle(c)
    return c


def probe() -> dict:
    """Counts only (what QUOTAS was written from). No affair is selected, no text is read."""
    fr, rep = frame()
    by = collections.Counter((x["stratum"], x["a_type"]) for x in fr)
    dated = collections.Counter((x["stratum"], x["answer_dates"] > 0) for x in fr)
    multi = collections.Counter(x["stratum"] for x in fr if x["n_answer_rows"] > 1)
    pattern = collections.Counter("+".join(L for L in STRATA if x["genuine"][L]) for x in fr)
    genuine_by_slot = {L: sum(x["genuine"][L] for x in fr) for L in STRATA}
    # OPD's language slot vs the converter's guess on the answer text it holds (texts of >= 200 characters)
    slot_audit = collections.Counter(f"{L}:{'same' if g == L else 'holds_' + g}" for x in fr
                                     for L, g in x["answer_slot_lang"].items() if g)
    con = collections.Counter()
    ids = {x["affair"] for x in fr}
    for r in _rows("contributors"):
        if r.get("affair_id") in ids:
            con[r.get("role_harmonized") or "none"] += 1
    info = json.loads(SCAN_INFO.read_text()) if SCAN_INFO.exists() else None
    out = dict(
        scan=info,
        opd_snapshot={n: hashlib.sha256((OPD_RAW / f"{n}.ndjson.gz").read_bytes()).hexdigest()
                      for n in ("affairs", "events", "contributors")},
        frame=rep,
        eligible_by_stratum_and_type={f"{s}:{t}": n for (s, t), n in sorted(by.items())},
        eligible_by_stratum={s: sum(n for (s2, _), n in by.items() if s2 == s) for s in STRATA},
        eligible_by_stratum_group_and_event={f"{s}:{g}:{'fc_event' if e else 'no_answer_event'}": n for (s, g, e), n in
                                             sorted(collections.Counter((x["stratum"], x["group"], x["recorded_by_event"])
                                                                        for x in fr).items())},
        genuine_slot_patterns=dict(pattern.most_common()),
        eligible_with_genuine_slot=genuine_by_slot,
        answer_slot_vs_language_guess=dict(sorted(slot_audit.items())),
        answers_with_a_lattice_date={f"{s}:{'yes' if k else 'no'}": n for (s, k), n in sorted(dated.items())},
        affairs_with_several_answer_rows=dict(multi),
        contributor_roles_on_eligible_affairs=dict(con.most_common()),
        note="counts of eligible affairs only; no affair was selected or opened before the LOCKFED commit",
    )
    RF.mkdir(parents=True, exist_ok=True)
    PROBE.write_text(json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1:] or [""]
    if cmd == ["scan"]:
        print(json.dumps(scan(), indent=1))
    elif cmd == ["probe"]:
        print(json.dumps(probe(), indent=1, ensure_ascii=False))
    else:
        print(__doc__)
