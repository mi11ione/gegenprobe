"""Shared U3 tooling for DEV2 (development) and P6 (pre-registered test): exclusions, a metadata-only document-type guess,
the seeded draw with polite fetches, and the annotation wrapper (the frozen P1 helpers pointed at a P6 path).

Exclusions: every document, affair and body of P1 dev + held-out (+ spikes and every dev-id source), P2, P3, P3b, P4
(dev, held-out, transfer meetings), the P5 sets of workstream U2 (data/gold6/*.jsonl, when present) and, for P6, DEV2.

The document-type guess reads only OPD metadata (document name, affair type); it stratifies the draw, the label is the
annotators'. It extends eval/gold/doctype.py with the answer names that the unseen communes use ("Beantwortung",
"Antwort des Stadtrats", "_ant", "Réponse", "Risposta"); `report`-like names are left out of both strata.
"""

from __future__ import annotations

import collections
import glob
import gzip
import json
import random
import re
import urllib.parse
from pathlib import Path

from eval.gold.sample import affair_types, lang_of
from eval.gold2.sample import fetch_one, seen
from gegenprobe.paths import DATA, DOCS_META

ANSWER6 = re.compile(
    r"beantwortung|antwort|_ant\b|_ant\.|r[ée]?ponse|risposta|osservazioni? del municipio|schreiben des rr", re.I
)
NOT_ANSWER6 = re.compile(
    r"vernehmlassung|fragen.?antworten|pr[äa]sentation|beilage|annexe|allegato|rapport (de la )?commission|kommissionsbericht",
    re.I,
)
INTERVENTION6 = re.compile(
    r"interpellation|motion|postulat|anfrage|interpellanza|interrogazione|mozione|question|vorstoss|wortlaut", re.I
)
REPORTISH = re.compile(
    r"bericht|rapport|protokoll|proc[eè]s|verbale|messaggio|botschaft|traktand|ordre du jour|beschluss|mitteilung|"
    r"medienmitteilung|abstimmung|fristerstreckung|fristverl|stellungnahme|entgegennahme|haltung|srb|stapab|prota",
    re.I,
)
INTERVENTION_TYPES = {"Interpellation", "Motion", "Postulate", "Question", "Question time"}


def doctype6(name: str | None, a_type: str | None) -> str | None:
    s = name or ""
    if ANSWER6.search(s) and not NOT_ANSWER6.search(s):
        return "answer"
    if REPORTISH.search(s):
        return None
    if INTERVENTION6.search(s) or (a_type in INTERVENTION_TYPES and not ANSWER6.search(s)):
        return "intervention"
    return None


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in open(p, encoding="utf-8")] if p.exists() else []


def _ids(x, docs: set, affs: set, bodies: set) -> None:
    """Collect doc_id / affair_id / body from any nested set record."""
    if isinstance(x, dict):
        for k, v in x.items():
            if k in ("doc_id", "id") and isinstance(v, int):
                docs.add(v)
            elif k == "affair_id" and isinstance(v, int):
                affs.add(v)
            elif k == "body" and v is not None:
                bodies.add(str(v))
            else:
                _ids(v, docs, affs, bodies)
    elif isinstance(x, list):
        for v in x:
            _ids(v, docs, affs, bodies)


EXISTING_SETS = [
    "gold2/p2_docs.jsonl",
    "gold3/p3_affairs.jsonl",
    "gold5/p3b_affairs.jsonl",
    "gold4/p4_meetings.jsonl",
    "gold4/p4_heldout_meetings.jsonl",
    "gold4/p4_transfer_meetings.jsonl",
]


def exclusions(extra: list[Path] = ()) -> tuple[set, set, set]:
    """(doc ids, affair ids, bodies) of every existing set. P1 via the frozen eval.gold2.sample.seen (bodies derived from
    the documents), the other sets from their committed lists, U2's P5 lists if present, plus `extra` lists."""
    docs, affs, bodies = seen()
    for rel in EXISTING_SETS:
        for x in _jsonl(DATA / rel):
            _ids(x, docs, affs, bodies)
    for p in sorted((DATA / "gold6").glob("*.jsonl")) if (DATA / "gold6").exists() else []:
        if "label" in p.name or "annotation" in p.name:
            continue
        for x in _jsonl(p):
            _ids(x, docs, affs, bodies)
    for p in extra:
        for x in _jsonl(p):
            _ids(x, docs, affs, bodies)
    return docs, affs, bodies


def pool(bodies: set[str], band: tuple[int, int]) -> dict:
    at = affair_types()
    out, ids = collections.defaultdict(list), set()
    for f in sorted(glob.glob(str(DOCS_META / "part*" / "docs_meta.jsonl.gz"))):
        for line in gzip.open(f, "rt"):
            d = json.loads(line)
            if d["id"] in ids or d["b"] not in bodies or not d.get("url"):
                continue
            ids.add(d["id"])
            if d["st"] != "ok" or not (band[0] <= d["n"] <= band[1]):
                continue
            d["a_type"] = at.get(d.get("a"))
            d["dtype"] = doctype6(d.get("name"), d["a_type"])
            d["lg"] = lang_of(d)
            if d["dtype"]:
                out[(d["b"], d["dtype"])].append(d)
    return out


def draw(quotas: list[tuple], seed: int, salt: str, band: tuple[int, int], x_docs: set, x_affs: set, fetch: bool = True):
    """quotas: (cell, body, dtype, n). Seeded order per (body, dtype); a fetch failure or a too-short text is replaced by
    the next candidate of the same body and type; one document per affair. Returns (chosen rows, log rows)."""
    pl = pool({q[1] for q in quotas}, band)
    chosen, log, used = [], [], set(x_affs)
    for cell, body, dt, n in quotas:
        cands = sorted((d for d in pl[(body, dt)] if d["id"] not in x_docs), key=lambda d: d["id"])
        random.Random(f"{seed}:{salt}:{body}:{dt}").shuffle(cands)
        got = []
        for d in cands:
            if len(got) >= n:
                break
            if d.get("a") is not None and d["a"] in used:
                continue
            r = fetch_one(d) if fetch else {}
            ok = "error" not in r
            log.append(dict(doc_id=d["id"], body=body, dtype=dt, host=urllib.parse.urlparse(d["url"]).netloc, accepted=ok, **r))
            if ok:
                if d.get("a") is not None:
                    used.add(d["a"])
                got.append(dict(d, **r))
        if len(got) < n:
            log.append(dict(body=body, dtype=dt, shortfall=n - len(got), pool=len(cands)))
        for d in got:
            chosen.append(
                dict(
                    split=salt,
                    cell=cell,
                    level=cell.split("_")[1],
                    dtype=dt,
                    doc_id=d["id"],
                    body=body,
                    affair_id=d.get("a"),
                    affair_type=d.get("a_type"),
                    lang=d["lg"] or cell[:2],
                    name=d.get("name"),
                    url=d["url"],
                    opd_text_status=d["st"],
                    opd_chars=d["n"],
                    **{k: d.get(k) for k in ("sha256", "pages", "chars", "tokens_est", "extractor", "image_only")},
                )
            )
    return chosen, log


def write_jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------------------------------------- annotation wrapper
def bind_annotation(docs_path: Path, work: Path):
    """Point the frozen P1 annotation helpers (eval/gold/annotate.py) at a U3 set. Returns the module."""
    from eval.gold import annotate as A

    A.G, A.PACK, A.ANN = work, work / "packets", work / "ann"
    A.heldout_docs = lambda: _jsonl(docs_path)
    return A


def a3packets(A, seed: int, key) -> list[int]:
    """Tie-break packets for documents whose A1/A2 labels differ under `key`, the two labels as X/Y in seeded order."""
    a1, a2 = A.load("A1"), A.load("A2")
    diff = [d for d in sorted(a1) if d in a2 and key(a1[d]) != key(a2[d])]
    rnd = random.Random(seed)
    order = {}
    (A.G / "a3").mkdir(parents=True, exist_ok=True)
    for i in diff:
        flip = rnd.random() < 0.5
        x, y = (a2[i], a1[i]) if flip else (a1[i], a2[i])
        order[i] = "X=A2,Y=A1" if flip else "X=A1,Y=A2"
        (A.G / "a3" / f"{i}.json").write_text(json.dumps(dict(doc_id=i, label_X=x, label_Y=y), ensure_ascii=False, indent=1))
    (A.G / "a3_order.json").write_text(json.dumps(order, indent=1))
    (A.G / "disagreements.json").write_text(json.dumps(diff))
    return diff
