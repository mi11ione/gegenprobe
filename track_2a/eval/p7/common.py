"""P7 shared tooling: the review-queue frame, exclusions (every audit sample, and DEV for the test), the seeded stratified
draw (review reason x parliament), blind packets for annotators, and the annotation guide.

Packets carry an opaque id, the affair number, title, type, OPD's answer event dates and the path of the text the
annotator reads (the extracted text, cut to the first HEAD and last TAIL characters when longer, as in audit v3); no
parliament, review reason, tier, action, model output or any other pipeline field. The key (packet id -> parliament,
affair, stratum) stays in WORK; its sha256 is recorded with the sample.
"""

from __future__ import annotations

import collections
import hashlib
import json
import random
from pathlib import Path

from gegenprobe.paths import ROOT
from gegenprobe.repair.adapters import adjudicate as J
from gegenprobe.repair.adapters import audit3, base, targets

HEAD, TAIL = audit3.HEAD, audit3.TAIL  # 12,000 + 3,000, as in audit v3


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def audit_keys() -> dict[str, set[tuple[str, int]]]:
    """(body, affair_id) of every adapter audit sample: design audit (and its backup copy), audit v2, audit v3."""
    out = {}
    for name, globs in (("design", ["audit/*.jsonl", "audit_orig_backup/*.jsonl"]), ("audit2", ["audit2/*.jsonl"]),
                        ("audit3", ["audit3/key.jsonl"])):
        s = set()
        for g in globs:
            for p in sorted(base.ADIR.glob(g)):
                s |= {(str(r["body"]), int(r["affair_id"])) for r in _jsonl(p)}
        out[name] = s
    return out


def frame(exclude: set[tuple[str, int]] = frozenset()) -> tuple[dict[str, list[dict]], dict]:
    """Eligible review rows outside every audit and `exclude`, grouped by review reason; plus a count report."""
    keys = audit_keys()
    allaud = set().union(*keys.values())
    rows = J.review_rows()
    rep = collections.Counter()
    strata = collections.defaultdict(list)
    for r in rows:
        k = (r["body"], r["affair_id"])
        rep["review_rows"] += 1
        if not r["eligible"]:
            rep[f"ineligible:{r['reason']}"] += 1
            continue
        if k in allaud:
            rep["in_audit"] += 1
            continue
        if k in exclude:
            rep["excluded_other"] += 1
            continue
        strata[r["reason"]].append(r)
    rep["frame"] = sum(len(v) for v in strata.values())
    return {k: sorted(v, key=lambda r: (r["body"], r["affair_id"])) for k, v in sorted(strata.items())}, \
        dict(rep, audits={k: len(v) for k, v in keys.items()})


def draw(strata: dict[str, list[dict]], n: int, seed: int, floor: int) -> tuple[list[dict], dict]:
    """Stratified by review reason (at least `floor` per reason, the rest in proportion, largest remainder: audit3.allocate)
    and, within a reason, by parliament (proportional, largest remainder, at least one row for each parliament while the
    reason's share allows one per parliament with rows). Seeded; returns rows with `stratum`, and the allocation."""
    sizes = {k: len(v) for k, v in strata.items()}
    alloc = audit3.allocate(sizes, n=n, floor=floor)
    rng = random.Random(seed)
    out, by_body = [], {}
    for k in sorted(strata):
        pool = collections.defaultdict(list)
        for r in strata[k]:
            pool[r["body"]].append(r)
        bs = {b: len(v) for b, v in pool.items()}
        fl = 1 if len(bs) <= alloc[k] else 0
        ba = audit3.allocate(bs, n=alloc[k], floor=fl) if alloc[k] else {b: 0 for b in bs}
        by_body[k] = {b: v for b, v in ba.items() if v}
        for b in sorted(pool):
            for r in rng.sample(pool[b], ba[b]):
                out.append(dict(r, stratum=k))
    rng.shuffle(out)
    return out, dict(seed=seed, n=n, floor=floor, frame=sizes, allocation=alloc, by_body=by_body)


def write_packets(items: list[dict], workdir: Path, prefix: str) -> dict:
    """Packets + texts (WORK only) + key; returns the key hash and packet count. Never overwrites an existing key."""
    pk, texts = workdir / "packets", workdir / "packets" / "texts"
    key = workdir / "key.jsonl"
    if key.exists():
        raise SystemExit(f"{key} exists: a drawn sample is never redrawn")
    texts.mkdir(parents=True, exist_ok=True)
    tg = {}
    for b in sorted({i["body"] for i in items}):
        tg.update({(b, x["id"]): x for x in targets.load(b)})
    packets, keys = [], []
    for n, it in enumerate(items, 1):
        pid = f"{prefix}-{n:03d}"
        x = tg[(it["body"], it["affair_id"])]
        text = J.excerpt_text(it["body"], it["affair_id"])
        view = audit3._view(text)
        tp = texts / f"{pid}.txt"
        tp.write_text(view, encoding="utf-8")
        packets.append(dict(id=pid, affair_number=x["number"], title=x.get("title") or "", type=x.get("type") or "",
                            answer_event_dates=x.get("answer_dates") or [], excerpt_path=str(tp.relative_to(ROOT)),
                            excerpt_sha256=hashlib.sha256(view.encode()).hexdigest()))
        keys.append(dict(id=pid, body=it["body"], affair_id=it["affair_id"], stratum=it["stratum"],
                         text_sha256=it["text_sha256"]))
    with open(pk / "packets.jsonl", "w", encoding="utf-8") as f:
        for p in packets:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    blob = "".join(json.dumps(k, sort_keys=True) + "\n" for k in keys)
    key.write_text(blob, encoding="utf-8")
    (workdir / "GUIDE.md").write_text(GUIDE.format(dir=str(workdir.relative_to(ROOT)), prefix=prefix), encoding="utf-8")
    return dict(packets=len(packets), key_sha256=hashlib.sha256(blob.encode()).hexdigest(),
                guide_sha256=hashlib.sha256((workdir / "GUIDE.md").read_bytes()).hexdigest())


def load_key(workdir: Path) -> dict[str, dict]:
    return {r["id"]: r for r in _jsonl(workdir / "key.jsonl")}


def load_packets(workdir: Path) -> list[dict]:
    return _jsonl(workdir / "packets" / "packets.jsonl")


GUIDE = """# P7 annotation guide (blind)

You judge whether a document is the government's written answer to one parliamentary intervention of a Swiss parliament
(a canton or a municipality), and which printed date is the date of that answer.

Input: `{dir}/packets/packets.jsonl`, one JSON object per line: `id`, `affair_number`, `title`, `type`,
`answer_event_dates` (OpenParlData's dates of the written-answer event, may be empty) and `excerpt_path` (a text file,
path relative to `track_2a/`: the text extracted from one document; when longer than 15,000 characters, the first 12,000
and the last 3,000 are shown). Read only the packet and its text file: nothing else in the repository (no lists, no
results, no code, no other annotator's file). Judge each packet on its own.

## Fields

1. `is_answer`: does this document print the executive's written answer to THIS intervention (the government:
   Regierungsrat, Stadtrat, Gemeinderat, Kleiner Rat, Conseil d'État, Conseil communal, Municipalité, Consiglio di
   Stato, Municipio ...)?
   - `yes`: it is the answer, or it contains the answer in full (e.g. the intervention's text followed by the
     government's answer; a decision extract "Auszug aus dem Protokoll des Regierungsrates" answering it; a letter of the
     Municipio replying to the interrogation; the government's report and proposal on a motion or postulate).
   - `no`: something else: the intervention's own text as submitted (even with an empty space for the answer), minutes
     of the parliament that only mention or summarise the answer, a commission report, a request for more time, the
     answer to a different intervention, a list or agenda.
   - `unclear`: the text does not let you decide (e.g. an unreadable scan, or the answer may be in the part not shown).
2. `decision_date`: the date on which the executive decided the answer, as printed in the text (e.g. «Regierungsrats-
   beschluss vom 12. März 2020», «Sitzung vom …», «séance du …», «seduta del …»), as `DD.MM.YYYY`, or `null` if no such
   date is printed. Only if `is_answer` is `yes` or `unclear`; otherwise `null`.
3. `letter_date`: the date of the answer letter or of its signature (e.g. «Luzern, 12. März 2020» above the
   government's signature, «Locarno, 18 ottobre 2012»), as `DD.MM.YYYY`, or `null`. Only if `is_answer` is `yes` or
   `unclear`; otherwise `null`. The same date may be both decision and letter date.
   Not an answer date: the submission date of the intervention, dates of parliamentary debates, dates cited in the
   content. Do not use `answer_event_dates` to decide which date is printed: report what the text prints.
4. `quote`: verbatim, at most 200 characters, the passage that best supports `is_answer`.
5. `date_quote`: verbatim, at most 200 characters, the passage that prints the date you gave (or "").
6. `note`: one short sentence.

## Output

`{dir}/ann/<annotator>.jsonl`, one line per packet, in packet order:

```
{{"id": "{prefix}-001", "is_answer": "yes|no|unclear", "decision_date": "DD.MM.YYYY|null", "letter_date": "DD.MM.YYYY|null", "quote": "...", "date_quote": "...", "note": "..."}}
```

Use JSON `null` (not the string) for a missing date.
"""  # noqa: E501
