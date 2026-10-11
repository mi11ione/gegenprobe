"""Blind audit v3 of the counted adapter rows (round 6; answers J5's critique of the fresh audit v2).

v2 handed auditors the pipeline's outcome, reason and proposed action, kept its inputs out of the repository, estimated a
stratified sample with a simple-random-sample interval and had no negative controls. v3:

  * a NEW stratified sample (seed 20261212) of 200 counted rows (tiers exact_doc_date, exact_any_printed_date,
    date_window) from the frame of counted rows outside the design audit (first audit, whose rows the filters were tuned
    on); strata = tier x action, at least FLOOR per stratum, the rest in proportion to the stratum's size (largest
    remainder); estimate = sum over strata of N_h/N * k_h/n_h, 95% interval from per-stratum Jeffreys posteriors
    (Monte Carlo, seeded), per-stratum Wilson intervals alongside;
  * 60 decoys from rows the pipeline did NOT count (30 review, 30 failed with extracted text), shuffled in with the 200;
  * packets carry ONLY an opaque id, the affair number, title, type, OPD's answer event dates and the path of the text
    the auditor reads; no parliament, outcome, reason, action, tier or verified field. The text file is the extracted text
    (no header), cut to the first HEAD and last TAIL characters when longer;
  * the key (packet id -> parliament, affair, stratum or decoy group) stays in WORK until the verdicts are in; its sha256
    is committed with the sample (results/repair/adapters/audit3/sample.json) so the key cannot change afterwards;
  * two independent auditors on the same packets and prompt (PROMPT.md): a Claude agent (launched by the lead) and
    Qwen-SEA-LION-v4-32B-IT through the budget gateway (never an Apertus model).
  * blindness: a packet carries no outcome, but its `text_sha256` (the full text's sha256) equals the `text_sha256`
    column of the committed adapters_<BODY>.tsv lists, so anyone with the repository can join a packet to its tier and
    counted flag. The Qwen auditor received only the filled item prompt (metadata and text, no hash, no repository); the
    Claude auditor ran as an agent in a checkout and was blind by instruction only (PROMPT.md: "Read nothing else in the
    repository for this task").

    python -m gegenprobe.repair.adapters.audit3 draw     sample + packets + PROMPT.md (results), texts + key (WORK)
    python -m gegenprobe.repair.adapters.audit3 qwen     the second auditor -> WORK/adapters/audit3/verdicts_qwen.jsonl
                                                         development: Qwen through the developer's budget gateway
                                                         (GP_GATEWAY_DIR, gegenprobe/devpaths.py);
                                                         `qwen --backend openai`: any OpenAI-compatible server
                                                         (LLM_BASE_URL, LLM_API_KEY, LLM_NAME; never an Apertus model),
                                                         the route for an operator
    python -m gegenprobe.repair.adapters.audit3 score [--final]   join verdicts with the key; per auditor: stratified
                                                         precision, decoy rates, date_ok, quote check, agreement.
                                                         WORK/adapters/audit3/score.json; --final also writes
                                                         results/repair/adapters/audit3/summary.json and key.jsonl
"""
from __future__ import annotations

import collections
import csv
import hashlib
import json
import math
import random
import re
import sys

from ... import devpaths
from ...paths import RESULTS, ROOT
from . import base, lists, run

SEED = 20261212
N_COUNTED = 200
N_DECOY = dict(review=30, failed=30)
FLOOR = 12
HEAD, TAIL = 12000, 3000
OUT = RESULTS / "repair" / "adapters" / "audit3"
WORKDIR = base.ADIR / "audit3"
TEXTS = WORKDIR / "texts"
KEY = WORKDIR / "key.jsonl"
QWEN = "aisingapore/Qwen-SEA-LION-v4-32B-IT"
QWEN_TAG = "2a-adapter-audit-qwen"
LABELS = ("yes", "no", "unclear")

ITEM = """You are auditing whether a document is the government's written answer to a parliamentary intervention in a Swiss \
parliament (a canton or a municipality). You see the intervention's metadata from OpenParlData (OPD) and the text \
extracted from one document. Judge only from what is shown.

Intervention
- number: {number}
- title: {title}
- type: {type}
- OPD answer event date(s): {dates}

Document text (extracted; when longer than 15,000 characters, the first 12,000 and the last 3,000 are shown):
<<<
{text}
>>>

Questions
1. is_answer: Is this document the executive's written answer or written response to THIS intervention (the \
government, Regierungsrat, Conseil d'État, Consiglio di Stato, Stadtrat, Gemeinderat, Municipalité, Municipio, ...)? \
yes = it is, or it contains it; no = it is something else (the member's own question or motion text, minutes of the \
parliament that only refer to an answer, a commission report, a request for more time, the answer to a different \
intervention, ...); unclear = the text does not let you decide.
2. date_ok: Does the document's own date, or the answer date it states, agree with one of the OPD answer event dates \
(the same day, or within about 30 days)? yes / no / unclear (no date found in the text, or no OPD date given).
3. quote: copy verbatim, at most 200 characters, the passage of the document text that most supports your is_answer \
judgment.

Reply with one JSON object only, no other text:
{{"is_answer": "yes|no|unclear", "date_ok": "yes|no|unclear", "quote": "...", "note": "one short sentence"}}"""

TEMPLATE = ITEM.replace("{{", "{").replace("}}", "}")  # the item prompt as printed in PROMPT.md (fields in braces)
assert HEAD == 12000 and TAIL == 3000  # printed in ITEM

BATCH = """# Audit v3: auditor instructions (identical for both auditors)

Input: `results/repair/adapters/audit3/packets.jsonl`, one JSON object per line with `id`, `affair_number`, `title`,
`type`, `answer_event_dates` and `excerpt_path` (a text file under `.work/adapters/audit3/texts/`, path relative to
`track_2a/`). Read nothing else in the repository for this task: not the adapter lists, not results/, not the code, not
earlier audits. For every packet, read its excerpt file and answer the item prompt below with these values filled in
(`{{number}}` = affair_number, `{{title}}`, `{{type}}`, `{{dates}}` = answer_event_dates joined by ", " or "none",
`{{text}}` = the excerpt file's content). Judge each packet on its own.

Output: `.work/adapters/audit3/verdicts_<auditor>.jsonl`, one line per packet:
`{{"id": "A3-001", "is_answer": "yes|no|unclear", "date_ok": "yes|no|unclear", "quote": "...", "note": "..."}}`
(`quote`: at most 200 characters, verbatim from the excerpt).

The Qwen auditor (`python -m gegenprobe.repair.adapters.audit3 qwen`) receives exactly the filled item prompt as the
only user message (temperature 0).

## Item prompt

```
{item}
```
"""


# ---------------------------------------------------------------- frame and sample
def _excerpt_text(body: str, aid: int) -> str | None:
    p = base.excerpt_path(body, aid)
    if not p.exists():
        return None
    raw = p.read_text(encoding="utf-8")
    return raw.split("\n\n", 1)[1] if "\n\n" in raw else raw


def _view(text: str) -> str:
    if len(text) <= HEAD + TAIL:
        return text
    return text[:HEAD] + "\n\n[... " + f"{len(text) - HEAD - TAIL:,}" + " characters not shown ...]\n\n" + text[-TAIL:]


def _design_audit() -> set[tuple[str, int]]:
    seen = set()
    for p in sorted(run.AUDIT.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                seen.add((r["body"], int(r["affair_id"])))
    return seen


def frame() -> tuple[dict[str, list[tuple[str, int]]], dict[str, list[tuple[str, int]]], int]:
    """(counted strata, decoy pools, design-audit affairs excluded). Counted rows from the committed lists; decoys: review
    rows of the lists and failed affairs with extracted text (<BODY>.json)."""
    seen = _design_audit()
    strata: dict[str, list] = collections.defaultdict(list)
    decoys: dict[str, list] = collections.defaultdict(list)
    excluded = 0
    for p in sorted(run.OUT.glob(f"{lists.PREFIX}*.tsv")):
        body = p.stem[len(lists.PREFIX):]
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                key = (body, int(r["affair_id"]))
                if key in seen:
                    excluded += r["counted"] == "true"
                    continue
                if r["counted"] == "true":
                    strata[f"{r['tier']}/{r['action']}"].append(key)
                elif r["tier"] == "review" and base.excerpt_path(*key).exists():
                    decoys["review"].append(key)
    for p in sorted(run.OUT.glob("*.json")):
        if p.name in run.NOT_BODIES:
            continue
        for a in json.loads(p.read_text())["affairs"]:
            key = (p.stem, int(a["affair_id"]))
            if a["tier"] == "failed" and key not in seen and base.excerpt_path(*key).exists():
                decoys["failed"].append(key)
    return ({k: sorted(v) for k, v in sorted(strata.items())}, {k: sorted(v) for k, v in sorted(decoys.items())},
            excluded)


def allocate(sizes: dict[str, int], n: int = N_COUNTED, floor: int = FLOOR) -> dict[str, int]:
    want = {k: min(floor, v) for k, v in sizes.items()}
    rest = n - sum(want.values())
    room = {k: sizes[k] - want[k] for k in sizes}
    tot = sum(room.values())
    share = {k: rest * room[k] / tot for k in sizes}
    extra = {k: min(int(share[k]), room[k]) for k in sizes}
    left = rest - sum(extra.values())
    for k in sorted(sizes, key=lambda k: (-(share[k] - int(share[k])), k)):
        if left <= 0:
            break
        if want[k] + extra[k] < sizes[k]:
            extra[k] += 1
            left -= 1
    return {k: want[k] + extra[k] for k in sizes}


def draw() -> dict:
    strata, decoys, excluded = frame()
    sizes = {k: len(v) for k, v in strata.items()}
    alloc = allocate(sizes)
    rng = random.Random(SEED)
    items = []
    for k in sorted(strata):
        for key in sorted(rng.sample(strata[k], alloc[k])):
            items.append(dict(group="counted", stratum=k, body=key[0], affair_id=key[1]))
    for g in sorted(N_DECOY):
        for key in sorted(rng.sample(decoys[g], N_DECOY[g])):
            items.append(dict(group="decoy", stratum=f"decoy/{g}", body=key[0], affair_id=key[1]))
    rng.shuffle(items)
    tg = {}
    from . import targets
    for b in sorted({i["body"] for i in items}):
        tg.update({(b, x["id"]): x for x in targets.load(b)})
    TEXTS.mkdir(parents=True, exist_ok=True)
    for f in TEXTS.glob("*.txt"):
        f.unlink()
    OUT.mkdir(parents=True, exist_ok=True)
    packets, keys = [], []
    for n, it in enumerate(items, 1):
        pid = f"A3-{n:03d}"
        x = tg[(it["body"], it["affair_id"])]
        text = _excerpt_text(it["body"], it["affair_id"])
        view = _view(text)
        tp = TEXTS / f"{pid}.txt"
        tp.write_text(view, encoding="utf-8")
        packets.append(dict(id=pid, affair_number=x["number"], title=x.get("title") or "", type=x.get("type") or "",
                            answer_event_dates=x.get("answer_dates") or [],
                            excerpt_path=str(tp.relative_to(ROOT)),
                            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                            excerpt_sha256=hashlib.sha256(view.encode("utf-8")).hexdigest()))
        keys.append(dict(id=pid, **it))
    with open(OUT / "packets.jsonl", "w", encoding="utf-8") as f:
        for p in packets:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    blob = "".join(json.dumps(k, sort_keys=True) + "\n" for k in keys)
    KEY.write_text(blob, encoding="utf-8")
    (OUT / "PROMPT.md").write_text(BATCH.format(item=TEMPLATE), encoding="utf-8")
    res = dict(seed=SEED, n_counted=N_COUNTED, n_decoys=sum(N_DECOY.values()), decoys=N_DECOY, floor=FLOOR,
               frame=dict(counted=sum(sizes.values()), strata=sizes, design_audit_excluded=excluded,
                          decoy_pools={k: len(v) for k, v in decoys.items()}),
               allocation=alloc, packets=len(packets), view=dict(head=HEAD, tail=TAIL),
               key_sha256=hashlib.sha256(blob.encode()).hexdigest(),
               key_note="WORK/adapters/audit3/key.jsonl (packet id -> parliament, affair, stratum); committed only "
                        "after both auditors' verdicts are in (`score --final`); its sha256 is fixed here",
               prompt_sha256=hashlib.sha256(TEMPLATE.encode()).hexdigest(),
               blind="packets carry id, affair number, title, type, OPD answer event dates and the text path only")
    (OUT / "sample.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return res


# ---------------------------------------------------------------- auditors
def item_prompt(p: dict) -> str:
    text = (ROOT / p["excerpt_path"]).read_text(encoding="utf-8")
    assert hashlib.sha256(text.encode()).hexdigest() == p["excerpt_sha256"], p["id"]
    return ITEM.format(number=p["affair_number"], title=p["title"], type=p["type"],
                       dates=", ".join(p["answer_event_dates"]) or "none", text=text)


def parse(reply: str) -> dict:
    """The auditor's JSON object (tolerates a code fence or text around it); labels normalised, else 'invalid'."""
    m = re.search(r"\{.*\}", reply or "", re.S)
    d = {}
    if m:
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            d = {}
    out = {}
    for k in ("is_answer", "date_ok"):
        v = str(d.get(k, "")).strip().lower()
        if not d:  # the object did not parse (an unescaped quote inside "quote"): read the label fields alone
            m2 = re.search(rf'"{k}"\s*:\s*"(\w+)"', reply or "")
            v = m2.group(1).lower() if m2 else ""
        out[k] = v if v in LABELS else "invalid"
    out["quote"] = str(d.get("quote") or "")[:400]
    out["note"] = str(d.get("note") or "")[:400]
    return out


def packets() -> list[dict]:
    return [json.loads(line) for line in (OUT / "packets.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def _gateway_backend(cap_usd: float, max_tokens: int):
    """Development: Qwen through the developer's budget gateway (priced before sending, ledger, cache)."""
    gw = devpaths.import_gw("audit3 qwen (development route; operators use `qwen --backend openai`)")

    def call(prompt: str) -> tuple[str | None, str, float, bool]:
        choice, meta = gw.chat([dict(role="user", content=prompt)], model=QWEN, max_tokens=max_tokens,
                               temperature=0.0, tag=QWEN_TAG, tag_cap_usd=cap_usd, full=True)
        cached = bool(meta.get("cached"))
        return ((meta.get("resp") or {}).get("model"), (choice.get("message") or {}).get("content") or "",
                0.0 if cached else meta.get("usd", 0.0), cached)

    def ok(served: str | None) -> bool:
        return served is not None and "qwen-sea-lion" in served.lower()

    return call, ok, QWEN


def _openai_backend(max_tokens: int):
    """Operator route: any OpenAI-compatible chat endpoint (LLM_BASE_URL, LLM_API_KEY, LLM_NAME). Not cached into the
    repository's model cache; the raw replies go to WORK like the gateway route's."""
    from ... import llm

    be = llm.OpenAICompat()
    if not be.base or not be.model:
        raise SystemExit("audit3 qwen --backend openai: set LLM_BASE_URL, LLM_API_KEY and LLM_NAME (an auditor model "
                         "from another vendor than the first auditor; never an Apertus model)")
    if "apertus" in be.model.lower():
        raise SystemExit(f"audit3: the auditor must not be an Apertus model (LLM_NAME={be.model})")

    def call(prompt: str) -> tuple[str | None, str, float, bool]:
        r = be._post(dict(model=be.model, messages=[dict(role="user", content=prompt)], max_tokens=max_tokens,
                          temperature=0.0))
        return (r.get("resp") or {}).get("model"), r.get("text") or "", 0.0, False

    def ok(served: str | None) -> bool:
        return served is not None and "apertus" not in served.lower()

    return call, ok, be.model


def qwen(cap_usd: float = 0.8, max_tokens: int = 400, backend: str = "gateway") -> dict:
    call, ok, expected = _openai_backend(max_tokens) if backend == "openai" else _gateway_backend(cap_usd, max_tokens)
    out = WORKDIR / "verdicts_qwen.jsonl"  # with the raw replies; `score --final` commits the parsed fields
    done = {}
    if out.exists():
        done = {json.loads(line)["id"]: json.loads(line) for line in out.read_text().splitlines() if line.strip()}
    models, usd, n_new = collections.Counter(), 0.0, 0
    with open(out, "a", encoding="utf-8") as f:
        for p in packets():
            if p["id"] in done:
                continue
            served, reply, cost, cached = call(item_prompt(p))
            models[served] += 1
            if not ok(served):
                raise RuntimeError(f"{p['id']}: served model {served!r}, expected {expected}")
            v = dict(id=p["id"], **parse(reply), model=served, raw=reply[:2000], cached=cached)
            f.write(json.dumps(v, ensure_ascii=False) + "\n")
            f.flush()
            usd += cost
            n_new += 1
    return dict(new=n_new, usd=round(usd, 4), served_models=dict(models))


# ---------------------------------------------------------------- scoring
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"-\s*\n\s*", "", s or "")).strip().lower()


def quote_found(quote: str, text: str) -> bool | None:
    q = _norm(quote).strip(" .…\"'«»")
    if len(q) < 12:
        return None
    t = _norm(text)
    if q in t:
        return True
    parts = [x for x in re.split(r"\s*(?:\.\.\.|…)\s*", q) if len(x) >= 12]  # elisions
    return bool(parts) and all(x in t for x in parts)


def wilson(k: int, n: int, z: float = 1.959964) -> list[float] | None:
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def stratified(per: dict[str, tuple[int, int]], sizes: dict[str, int], draws: int = 20000, seed: int = SEED) -> dict:
    """Stratified estimate sum_h W_h k_h/n_h and a 95% interval from independent Jeffreys Beta(k+1/2, n-k+1/2) posteriors
    per stratum (Monte Carlo)."""
    N = sum(sizes[h] for h in per)
    est = sum(sizes[h] / N * k / n for h, (k, n) in per.items() if n)
    rng = random.Random(seed)
    sims = sorted(sum(sizes[h] / N * rng.betavariate(k + 0.5, n - k + 0.5) for h, (k, n) in per.items() if n)
                  for _ in range(draws))
    return dict(estimate=round(est, 4), ci95=[round(sims[int(0.025 * draws)], 4), round(sims[int(0.975 * draws) - 1], 4)],
                method="stratified (N_h/N weights); 95% interval: Jeffreys posteriors per stratum, Monte Carlo "
                       f"{draws:,} draws, seed {seed}")


def load_verdicts(name: str) -> dict[str, dict]:
    for p in (WORKDIR / f"verdicts_{name}.jsonl", OUT / f"verdicts_{name}.jsonl"):
        if p.exists():
            out = {}
            for x in p.read_text(encoding="utf-8").splitlines():
                if x.strip():
                    v = json.loads(x)
                    if v.get("raw"):  # re-parse the stored reply with the current parser
                        v.update({k: w for k, w in parse(v["raw"]).items() if k in ("is_answer", "date_ok")})
                    out[v["id"]] = v
            return out
    return {}


def score_one(v: dict[str, dict], keys: dict[str, dict], pk: dict[str, dict], sizes: dict[str, int]) -> dict:
    per = collections.defaultdict(collections.Counter)
    for pid, k in keys.items():
        x = v.get(pid)
        lab = x["is_answer"] if x else "missing"
        per[k["stratum"]][lab] += 1
        if x:
            per[k["stratum"]][f"date_{x['date_ok']}"] += 1
            q = quote_found(x.get("quote", ""), (ROOT / pk[pid]["excerpt_path"]).read_text(encoding="utf-8"))
            per[k["stratum"]][{True: "quote_found", False: "quote_not_found", None: "quote_short"}[q]] += 1
    counted = {h: c for h, c in per.items() if not h.startswith("decoy/")}
    yes = {h: (c["yes"], sum(c[x] for x in (*LABELS, "invalid", "missing"))) for h, c in counted.items()}
    yes_decided = {h: (c["yes"], c["yes"] + c["no"]) for h, c in counted.items()}
    date_yes = {h: (c["date_yes"], sum(c[f"date_{x}"] for x in (*LABELS, "invalid"))) for h, c in counted.items()}
    tot = sum((c for c in counted.values()), collections.Counter())
    dec = {h: dict(c) for h, c in per.items() if h.startswith("decoy/")}
    return dict(
        verdicts=len(v),
        counted=dict(n=sum(n for _, n in yes.values()), yes=tot["yes"], no=tot["no"], unclear=tot["unclear"],
                     invalid=tot["invalid"], missing=tot["missing"], date_ok_yes=tot["date_yes"],
                     date_ok_no=tot["date_no"], date_ok_unclear=tot["date_unclear"],
                     quote_found=tot["quote_found"], quote_not_found=tot["quote_not_found"],
                     quote_short=tot["quote_short"],
                     unweighted_wilson=wilson(tot["yes"], sum(n for _, n in yes.values()))),
        precision=stratified(yes, sizes),
        precision_decided_only=stratified(yes_decided, sizes),
        date_ok=stratified(date_yes, sizes),
        by_stratum={h: dict(dict(per[h]), wilson=wilson(*yes[h]), frame=sizes[h]) for h in sorted(counted)},
        decoys=dec,
        decoys_yes_share={h: round(c.get("yes", 0) / max(1, sum(c.get(x, 0) for x in (*LABELS, "invalid"))), 3)
                          for h, c in dec.items()},
    )


def score(final: bool = False) -> dict:
    keys = {json.loads(x)["id"]: json.loads(x) for x in KEY.read_text(encoding="utf-8").splitlines() if x.strip()}
    smp = json.loads((OUT / "sample.json").read_text())
    assert hashlib.sha256(KEY.read_bytes()).hexdigest() == smp["key_sha256"], "key changed after the draw"
    pk = {p["id"]: p for p in packets()}
    sizes = smp["frame"]["strata"]
    auditors = {a: load_verdicts(a) for a in ("claude", "qwen")}
    res = dict(seed=SEED, packets=len(pk), auditors={a: score_one(v, keys, pk, sizes) for a, v in auditors.items() if v})
    if all(auditors.values()):
        a, b = auditors["claude"], auditors["qwen"]
        both = [i for i in keys if i in a and i in b]
        agree = sum(a[i]["is_answer"] == b[i]["is_answer"] for i in both)
        pairs = collections.Counter(f"{a[i]['is_answer']}/{b[i]['is_answer']}" for i in both)
        res["agreement"] = dict(n=len(both), is_answer_equal=agree, pairs_claude_qwen=dict(sorted(pairs.items())),
                                counted_both_yes=sum(1 for i in both if keys[i]["group"] == "counted"
                                                     and a[i]["is_answer"] == b[i]["is_answer"] == "yes"),
                                counted_either_no=sum(1 for i in both if keys[i]["group"] == "counted"
                                                      and "no" in (a[i]["is_answer"], b[i]["is_answer"])))
    WORKDIR.mkdir(parents=True, exist_ok=True)
    (WORKDIR / "score.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True))
    if final:
        (OUT / "summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        (OUT / "key.jsonl").write_bytes(KEY.read_bytes())
        for a, v in auditors.items():
            with open(OUT / f"verdicts_{a}.jsonl", "w", encoding="utf-8") as f:
                for pid in sorted(v):
                    x = v[pid]
                    f.write(json.dumps({k: x.get(k) for k in ("id", "is_answer", "date_ok", "quote", "note", "model")
                                        if k in x}, ensure_ascii=False) + "\n")
    return res


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "draw":
        print(json.dumps(draw(), indent=1))
        return 0
    if cmd == "qwen":
        backend = argv[argv.index("--backend") + 1] if "--backend" in argv[:-1] else "gateway"
        print(json.dumps(qwen(backend=backend), indent=1))
        return 0
    if cmd == "score":
        print(json.dumps(score("--final" in argv), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
