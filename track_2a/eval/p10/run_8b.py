"""EXPLORATORY (after LOCK10; PREREG10 §4 (d), outside the hypothesis family): the real Apertus v1.5 8B (GGUF Q4_K_M,
llama.cpp on a 4-vCPU CI runner, the fast scorer `gegenprobe.gguf_fast` that cleared the D2 gate) as P10's author-role
reader. Question: which of the registered P10 gains of the Apertus role pointer (70B weights via Public AI) hold on the
sovereign local route (open 8B weights, one machine, no gateway)?

Same frozen system as the registered arm (eval/p10/arms.py `pointer`): the candidates of `convert.role_candidates`
(rolecand-1) on the same documents, the questions, prompts, view and composition of `convert.roles_pointer`
(rolepointer-2), the frozen configuration data/p10/p10_config.json. Only the backend differs: the exact forced choice
P(" true") vs P(" false") after the same JSON prefix (`roles_pointer.p_true`, the GGUF branch). Scored against the
committed P10 gold (data/p10/p10_gold.jsonl) with the registered scoring code, eval/p10/score.py unchanged (affair_row,
pooled, table, candidate_recall, hypotheses: paired parliament-cluster bootstrap, seed 20261102, B = 10,000, Holm); the
other arms are the committed registered outputs (results/p10/p10_offline.jsonl). Nothing here changes a LOCK10 file or a
registered result; every output carries LABEL.

Two threshold variants:
  frozen  tau = 0.98, tau_first = 0.30 as registered (fitted on the gateway build; PREREG10 §4 (d): not refitted)
  refit   tau, tau_first refitted on the 8B's answers on P10's DEVELOPMENT set (the 36 affairs of P8's 6 development
          parliaments, eval/p10/dev.py `dev_affairs`) by the rule PREREG10 §7 used (eval/p10/dev.py: the grid TAUS x TAUS;
          the highest macro pair F1 over the 6 parliaments, ties -> pooled F1 -> precision -> larger tau -> larger
          tau_first). The model-facing variant (staged_v3 prompts) and the structural rule lone_first_needs_cue stay
          frozen: only the two thresholds are refitted. The refit reads no P10 test label. Rule fixed before any 8B
          answer exists: the refit is reported only when all 36 development affairs were rebuilt (PDF byte-identical)
          and fully scored; otherwise it is reported as not available, with the partial development table.

Documents: no text is committed. The committed recipe data/p10/gguf8b/rows.jsonl (written once from the real WORK by
`export`; ids, URLs, sha256 and counts only) lists the 40 P10 test and the 36 development affairs, each document's URL,
the sha256 of its PDF bytes and of its extracted pages (json.dumps(pages, ensure_ascii=False)), and the number and kind of
its candidates. On the runner each PDF is fetched through the project's fetch path (`pdftext.fetch_pdf` -> gegenprobe.net:
RFC 9309 robots.txt, fail-closed; >= 1.2 s between requests to a host; User-Agent hackapertus-research/0.1; the
compliance/mirror routing) and must be byte-identical to the committed sha256; if the original is unreachable or
changed, OPD's own copy (files.openparldata.ch/doc/<body>/<hash>, located through OPD's docs export of that parliament)
is tried under the same byte check. A changed or vanished document is reported, never replaced. The text is extracted by
`pdftext.extract` (Ubuntu's poppler, not the macOS build the gold and the registered arm read: as in D3 of
eval/prereg/DEVIATIONS.md), and its sha256 is compared with the committed one (`text_identical`, reported per affair; a
pooled table on the text-identical affairs is reported too). The candidates are recomputed on the runner's text and
compared with the committed ones (`candidates_identical`).

Work unit: one candidate of one affair (1 model request for a group or committee, 3 for a person: author, first,
first_v2). Shards are contiguous blocks of the units in recipe order with equal request counts, so a large affair (60
candidates) can be split over runners. Each shard writes, per unit, the two log-probabilities and P(true) of each
question (no text); `merge` composes the roles in code exactly as `roles_pointer.read` does (`roles_pointer.decide` on
the same decision fields; checked against `read` itself in tests/test_p10_8b.py, and against the registered gateway
decisions in `export`). An affair with a candidate left unscored (fetch failure, deadline, prompt too long) is a pointer
abstention (no pairs), never an exclusion (PREREG10 stop rule 2).

    export                          DEV ONLY (real WORK, no network): data/p10/gguf8b/rows.jsonl + pins.json
    lockcheck                       LOCK10's committed files + the committed inputs pinned in pins.json, hash by hash
    plan [--split S --shards n]     print the shard plan (units, requests per shard)
    fetch --split S --shard i/n     rebuild the PDFs and texts of the shard's affairs (WORK only)
    features --split S --shard i/n  8B answers per unit -> results/p10/gguf8b/shards/
    merge                           compose (frozen; refit when available), score -> results/p10/gguf8b/

CI: .github/workflows/arms-8b-p10.yml (dev and test shards in parallel -> merge).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher (compliance/fetchguard.py)

from eval.p10 import arms as A  # noqa: E402
from eval.p10 import common as C  # noqa: E402
from eval.p10 import score as S  # noqa: E402
from gegenprobe.convert import role_candidates as RC  # noqa: E402
from gegenprobe.convert import roles_pointer as RP  # noqa: E402
from gegenprobe.paths import DATA, RESULTS, ROOT, WORK  # noqa: E402

LABEL = ("EXPLORATORY (after LOCK10; PREREG10 §4 (d), outside the hypothesis family, not pre-registered as a test): the "
         "real Apertus v1.5 8B (GGUF Q4_K_M, llama.cpp CPU) as P10's author-role reader; frozen candidates, prompts, view "
         "and composition; scored against the committed P10 gold with eval/p10/score.py unchanged")
BUILD = "gguf:apertus-v1.5-8b-text-q4_k_m"
N_CTX = 8192  # the P10 view is at most ~5,000 characters of excerpts plus the candidate list and two printed lines; a
#               longer prompt is refused (the unit is reported `too_long`), never truncated
DIR = DATA / "p10" / "gguf8b"
ROWS = DIR / "rows.jsonl"
PINS = DIR / "pins.json"
OUT = Path(os.environ.get("GP_P10_8B_OUT") or RESULTS / "p10" / "gguf8b")  # overridable for the offline tests
SHARDS = OUT / "shards"
D8 = DATA / "p8"
W8B = WORK / "p10_8b"
# inputs the analysis reads (committed): pinned by sha256 in pins.json at export, checked by `lockcheck` on runners
PINNED = ["data/p10/p10_gold.jsonl", "data/p10/p10_affairs.jsonl", "data/p10/p10_candidates.jsonl",
          "data/p10/body_names_p10.json", "data/p10/p10_key.jsonl", "results/p10/p10_offline.jsonl",
          "results/p10/p10_pointer.jsonl", "results/p10/p10_arms.jsonl", "results/p10/p10_scores.json",
          "data/p8/p8_gold.jsonl", "data/p8/p8_affairs.jsonl", "data/p8/body_names_p8.json",
          "data/p10/gguf8b/rows.jsonl", "src/gegenprobe/gguf_fast.py"]


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _write_jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def pages_sha(pages: list[str]) -> str:
    return _sha(json.dumps(pages, ensure_ascii=False))


def cands_sha(cands: list[dict]) -> str:
    return _sha(json.dumps(cands, ensure_ascii=False, sort_keys=True))


def config() -> dict:
    cfg = json.loads(C.CONFIG.read_text())["pointer"]
    assert cfg["mode"] == "staged" and not cfg.get("prompt_neg"), "the 8B arm replicates the frozen staged_v3 pointer"
    return cfg


def questions(cfg: dict, kind: str) -> list[str]:
    """The prompts `roles_pointer.read` asks about one candidate, in its order."""
    return [cfg["prompt"]] + (RP._as_list(cfg["prompt_first"]) if kind == "person" else [])


def rosters(split: str):
    from gegenprobe.affair import meta
    return meta.body_names(C.NAMES10 if split == "test" else D8 / "body_names_p8.json")


def load_rows(split: str | None = None) -> list[dict]:
    rows = _jsonl(ROWS)
    if not rows:
        raise SystemExit(f"{ROWS.relative_to(ROOT)} missing: run `export` on the machine that holds the P10 WORK")
    return [r for r in rows if split is None or r["split"] == split]


# ------------------------------------------------------------------------------------------------ export (dev only)
def _dev_gold() -> list[dict]:
    """The 36 development affairs (eval/p10/dev.py `dev_affairs`, without reading text): id, affair, body, stratum, gold."""
    from eval import converter_roles as CR

    sp = CR.split()
    gold = {g["affair_id"]: g for g in _jsonl(D8 / "p8_gold.jsonl")}
    affs = {a["affair_id"]: a for a in _jsonl(D8 / "p8_affairs.jsonl")}
    out = []
    for aid in sorted(gold, key=lambda k: gold[k]["id"]):
        g = gold[aid]
        if sp[g["body"]] != "dev":
            continue
        out.append(dict(id=g["id"], affair_id=aid, body=g["body"], stratum=affs[aid]["stratum"], affair=affs[aid],
                        gold=[(p["name"], p["role"]) for p in CR.gold_people(g)]))
    return out


def export() -> dict:
    """DEV ONLY: the recipe of every test and development affair from the local caches (no network). Each recipe is
    checked locally: the PDFs and pages are the ones the gold and the registered arm read, and the recomputed candidates
    of every test affair equal data/p10/p10_candidates.jsonl. Also checks that composing the committed gateway decisions
    with `roles_pointer.decide` (the merge path) reproduces the registered pointer pairs."""
    from eval import converter_roles as CR
    from eval.p10 import packets as PK

    cfg = config()
    test = sorted(_jsonl(C.AFFAIRS), key=lambda e: e["affair_id"])
    gid = {g["affair_id"]: g["id"] for g in _jsonl(C.GOLD)}
    committed = {r["affair_id"]: r["candidates"] for r in _jsonl(C.CANDS10)}
    reg = {r["affair_id"]: r for r in _jsonl(C.R10 / "p10_pointer.jsonl")}
    out, bad, recomposed = [], [], 0
    for split, items in (("test", [(gid[e["affair_id"]], e) for e in test]),
                         ("dev", [(d["id"], d["affair"]) for d in _dev_gold()])):
        N = rosters(split)
        for pid, e in sorted(items, key=lambda t: t[0]):
            docs, pages = [], {}
            for d in e["docs"]:
                ps = PK.doc_pages(d) if split == "test" else CR.pages_of(d["sha256"], d["image_only"])
                if ps is None:
                    raise SystemExit(f"{pid}: text not cached")
                pages[d["role"]] = ps
                docs.append(dict(role=d["role"], doc_id=d["doc_id"], url=d["url"], sha256=d["sha256"],
                                 image_only=bool(d.get("image_only")), extractor=d.get("extractor"), pages=len(ps),
                                 text_sha256=pages_sha(ps)))
            q, a = pages["question"], pages["answer"]
            cd = RC.candidates(q, a, N.get(e["body"], []))["candidates"]
            r = dict(split=split, id=pid, affair_id=e["affair_id"], body=e["body"], stratum=e["stratum"],
                     cell=e.get("cell") if split == "test" else "dev", docs=docs, n_cands=len(cd),
                     kinds="".join("p" if c["kind"] == "person" else "g" for c in cd), candidates_sha256=cands_sha(cd),
                     lang=A.lang_of(e["stratum"], q))
            if split == "test":
                r["recipe_verified_local"] = cd == committed[e["affair_id"]]
                if not r["recipe_verified_local"]:
                    bad.append(pid)
                ds = [dict(d) for d in reg[e["affair_id"]]["result"]["decisions"]]
                for d in ds:
                    d.pop("role", None)
                RP.decide(ds, cfg, RP.has_cosign_cue(q, a))
                recomposed += [(d["value"], d["role"]) for d in ds if d["role"] != "not_an_author"] == \
                    [tuple(x) for x in reg[e["affair_id"]]["pointer"]]
            else:
                r["recipe_verified_local"] = True
            out.append(r)
    _write_jsonl(ROWS, out)
    pins = dict(label=LABEL, files={f: _file_sha(ROOT / f) for f in PINNED},
                registered_pointer_recomposed=f"{recomposed}/{len(test)}",
                note="sha256 of the committed inputs the exploratory 8B arm reads; checked by `run_8b lockcheck`")
    PINS.write_text(json.dumps(pins, indent=1, sort_keys=True) + "\n")
    res = dict(rows=len(out), test=sum(r["split"] == "test" for r in out), dev=sum(r["split"] == "dev" for r in out),
               requests={s: sum(_cost(r) for r in out if r["split"] == s) for s in ("test", "dev")},
               recipe_not_reproduced=bad, registered_pointer_recomposed=pins["registered_pointer_recomposed"])
    print(json.dumps(res, indent=1))
    if bad or recomposed != len(test):
        raise SystemExit("recipe check failed")
    return res


# ------------------------------------------------------------------------------------------------ units and shards
def _cost(r: dict) -> int:
    return sum(3 if k == "p" else 1 for k in r["kinds"])


def units(split: str) -> list[dict]:
    """Every candidate of every affair of the split, in recipe order (id, then reading order)."""
    out = []
    for r in sorted(load_rows(split), key=lambda r: r["id"]):
        for i, k in enumerate(r["kinds"]):
            out.append(dict(affair_id=r["affair_id"], idx=i, cost=3 if k == "p" else 1, last=i == r["n_cands"] - 1))
    return out


def shard_units(split: str, shard: str) -> list[dict]:
    """Contiguous blocks with (nearly) equal request counts: unit j goes to shard floor(n * requests before j / total)."""
    i, n = map(int, shard.split("/"))
    us = units(split)
    total = sum(u["cost"] for u in us) or 1
    out, acc = [], 0
    for u in us:
        if acc * n // total == i:
            out.append(u)
        acc += u["cost"]
    return out


def _tag(split: str, shard: str) -> str:
    return f"{split}__{shard.replace('/', '_of_')}"


def plan(split: str, n: int) -> dict:
    rows = {r["affair_id"]: r for r in load_rows(split)}
    out = []
    for i in range(n):
        us = shard_units(split, f"{i}/{n}")
        out.append(dict(shard=f"{i}/{n}", units=len(us), requests=sum(u["cost"] for u in us),
                        affairs=len({u["affair_id"] for u in us}),
                        max_affair_requests=max((_cost(rows[a]) for a in {u["affair_id"] for u in us}), default=0)))
    return dict(split=split, affairs=len(rows), units=len(units(split)),
                requests=sum(u["cost"] for u in units(split)), shards=out)


# ------------------------------------------------------------------------------------------------ fetch (network)
def _offline_guard() -> None:
    """GP_P10_8B_OFFLINE=1 (tests): any network request raises before a byte leaves."""
    from gegenprobe import net

    def refuse(*a, **kw):
        raise RuntimeError("network disabled (GP_P10_8B_OFFLINE=1)")
    net.open_url = refuse


_OPD_COPY: dict[str, dict[int, str]] = {}


def opd_copy(body: str, doc_id: int) -> str | None:
    """OPD's own copy of a document (files.openparldata.ch/doc/<body>/<hash>, or the row's url_oparl), from OPD's docs
    export of the parliament (streamed once per parliament, only when an original fails; cached in WORK)."""
    from gegenprobe import net

    if body not in _OPD_COPY:
        p = W8B / f"opd_copies_{body}.json"
        if p.exists():
            _OPD_COPY[body] = {int(k): v for k, v in json.loads(p.read_text()).items()}
        else:
            want = {int(d["doc_id"]) for r in load_rows() if r["body"] == body for d in r["docs"]}
            m = {}
            for line in net.stream_ndjson_gz(f"https://files.openparldata.ch/exports/docs/docs_{body}.ndjson.gz"):
                d = json.loads(line)
                if d.get("id") in want:
                    u = d.get("url_oparl") or (f"https://files.openparldata.ch/doc/{d.get('body_key') or body}/{d['hash']}"
                                               if d.get("hash") else None)
                    if u:
                        m[int(d["id"])] = u
            W8B.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({str(k): v for k, v in m.items()}, sort_keys=True))
            _OPD_COPY[body] = m
    return _OPD_COPY[body].get(int(doc_id))


def get_doc(body: str, d: dict) -> dict:
    """The document's PDF, byte-identical to the committed sha256: the original URL, else OPD's copy. Then its pages."""
    from gegenprobe import pdftext

    st, path, errs = {}, None, []
    for via in ("original", "opd_copy"):
        try:
            u = d["url"] if via == "original" else opd_copy(body, d["doc_id"])
            if not u:
                raise LookupError("no OPD copy in the docs export")
            _sha_got, path = pdftext.fetch_pdf(C.quoted(u), expect_sha256=d["sha256"])  # FetchError sha_mismatch if changed
            st["via"] = via
            break
        except Exception as e:
            errs.append(f"{via}: {type(e).__name__}: {str(e)[:160]}")
    if path is None:
        return dict(ok=False, error="; ".join(errs))
    pages = pdftext.extract(d["sha256"], path, ocr=d["image_only"])["pages"]
    return dict(st, ok=True, pdf_identical=True, text_identical=pages_sha(pages) == d["text_sha256"],
                pages=len(pages), chars=sum(map(len, pages)), errors_before=errs or None)


def fetch(split: str, shard: str) -> dict:
    if os.environ.get("GP_P10_8B_OFFLINE") == "1":
        _offline_guard()
    rows = {r["affair_id"]: r for r in load_rows(split)}
    aids = list(dict.fromkeys(u["affair_id"] for u in shard_units(split, shard)))
    status = {}
    for aid in aids:
        r = rows[aid]
        docs = {d["role"]: get_doc(r["body"], d) for d in r["docs"]}
        ok = all(x["ok"] for x in docs.values())
        status[str(aid)] = dict(ok=ok, docs=docs, text_identical=ok and all(x["text_identical"] for x in docs.values()))
        if not ok:
            print("FETCH-FAIL", r["id"], {k: v.get("error", "")[:160] for k, v in docs.items() if not v["ok"]}, flush=True)
    SHARDS.mkdir(parents=True, exist_ok=True)
    rep = dict(label=LABEL, split=split, shard=shard, affairs=len(aids), fetched=sum(s["ok"] for s in status.values()),
               text_identical=sum(s["text_identical"] for s in status.values()),
               failed=sorted(rows[int(k)]["id"] for k, s in status.items() if not s["ok"]), status=status)
    (SHARDS / f"fetch__{_tag(split, shard)}.json").write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n")
    print(f"fetch {split} {shard}: {rep['fetched']}/{len(aids)} affairs, {rep['text_identical']} with text byte-identical "
          f"to the committed sha256; failed: {rep['failed']}", flush=True)
    return rep


# ------------------------------------------------------------------------------------------------ model
class TooLong(Exception):
    pass


def backend():
    """The fast GGUF scorer (same model file, rendering, tokens and cache keys as the frozen GGUF scorer); a prompt that
    would not fit N_CTX is refused before any evaluation."""
    from gegenprobe.gguf_fast import GGUFFast
    from gegenprobe.llm import ModelCache

    class P10GGUF(GGUFFast):
        def score(self, user_text, prefix, conts):
            k = ModelCache.key(self.build, "score", dict(user=user_text, prefix=prefix, conts=conts, n_ctx=4096))
            if self.cache.get(k) is None and not self.offline:
                self._load()
                n = len(self._tok(self.render(user_text) + prefix)) + max(len(self._tok(c)) for c in conts) + 8
                if n > self.n_ctx:
                    raise TooLong(f"{n} tokens > n_ctx {self.n_ctx}")
            return super().score(user_text, prefix, conts)

        def n_prompt(self, user_text, prefix, conts):
            hit = self.cache.get(ModelCache.key(self.build, "score",
                                                dict(user=user_text, prefix=prefix, conts=conts, n_ctx=4096)))
            return (hit or {}).get("n_prompt")

    return P10GGUF(n_ctx=N_CTX)


def affair_inputs(r: dict) -> tuple[list[str], list[str]]:
    """The runner's pages of the affair's two documents (fetched by `fetch`; read from WORK's text cache)."""
    from gegenprobe import pdftext

    pages = {d["role"]: pdftext.extract(d["sha256"], ocr=d["image_only"])["pages"] for d in r["docs"]}
    return pages["question"], pages["answer"]


def features(split: str, shard: str, be=None, deadline_s: float | None = None) -> dict:
    """8B answers for the shard's units (resumable: units already in the shard file are kept)."""
    t0 = time.time()
    deadline_s = deadline_s if deadline_s is not None else float(os.environ.get("GP_P10_8B_DEADLINE_S", "inf"))
    cfg = config()
    rows = {r["affair_id"]: r for r in load_rows(split)}
    N = rosters(split)
    mine = collections.defaultdict(list)
    for u in shard_units(split, shard):
        mine[u["affair_id"]].append(u)
    fst = json.loads((SHARDS / f"fetch__{_tag(split, shard)}.json").read_text())["status"]
    dst, dst_aff = SHARDS / f"{_tag(split, shard)}.jsonl", SHARDS / f"affairs__{_tag(split, shard)}.jsonl"
    done = {(f["affair_id"], f["idx"]) for f in _jsonl(dst)}
    have_aff = {f["affair_id"] for f in _jsonl(dst_aff)}
    be = be or backend()
    not_scored, n_new, n_req = {}, 0, 0
    with open(dst, "a", encoding="utf-8") as fh, open(dst_aff, "a", encoding="utf-8") as fa:
        for aid, us in mine.items():
            r = rows[aid]
            st = fst.get(str(aid)) or dict(ok=False)
            if not st["ok"]:
                for u in us:
                    not_scored[f"{r['id']}#{u['idx']}"] = "fetch failed"
                continue
            q, a = affair_inputs(r)
            cands = RC.candidates(q, a, N.get(r["body"], []))["candidates"]
            lg = A.lang_of(r["stratum"], q)
            if aid not in have_aff:
                fa.write(json.dumps(dict(
                    split=split, id=r["id"], affair_id=aid, lang=lg, cue=RP.has_cosign_cue(q, a),
                    text_identical=st["text_identical"], candidates_identical=cands_sha(cands) == r["candidates_sha256"],
                    candidates=[{k: c[k] for k in ("value", "kind", "sources", "doc", "page", "char_start", "char_end",
                                                   "quote_sha256")} for c in cands]), ensure_ascii=False, sort_keys=True)
                    + "\n")
                fa.flush()
            idxs = [u["idx"] for u in us]
            if any(u["last"] for u in us):  # the runner's text yields more candidates than the recipe: this shard
                idxs += list(range(r["n_cands"], len(cands)))  # (holding the recipe's last one) takes the extra ones
            v = RP.view(q, a, cfg)
            for i in idxs:
                key = f"{r['id']}#{i}"
                if (aid, i) in done:
                    continue
                if i >= len(cands):
                    not_scored[key] = "no such candidate on the runner's text"
                    continue
                if time.time() - t0 > deadline_s:
                    not_scored[key] = "deadline"
                    continue
                c, t1, ans, pids, nps = cands[i], time.time(), {}, [], []
                try:
                    for name in questions(cfg, c["kind"]):
                        user, pid = RP.prompt(c, cands, v, q, a, lg, cfg, name)
                        res = RP.p_true(be, user, RP.BOOL_PREFIX[name][lg])  # roles_pointer's GGUF branch: exact choice
                        ans[name] = dict(lps=res["lps"], p=res["p"], method=res["method"])
                        pids.append(pid)
                        nps.append(be.n_prompt(user, RP.BOOL_PREFIX[name][lg], [" true", " false"])
                                   if hasattr(be, "n_prompt") else None)
                        n_req += 1
                except TooLong as e:
                    not_scored[key] = f"too_long: {e}"
                    continue
                except Exception as e:  # one unit's failure never stops the shard
                    not_scored[key] = f"error: {type(e).__name__}: {str(e)[:160]}"
                    print("UNIT-FAIL", key, not_scored[key], flush=True)
                    continue
                fh.write(json.dumps(dict(split=split, id=r["id"], affair_id=aid, idx=i, value=c["value"], kind=c["kind"],
                                         answers=ans, prompt_ids=pids, n_prompt=nps, seconds=round(time.time() - t1, 1)),
                                    ensure_ascii=False, sort_keys=True) + "\n")
                fh.flush()
                n_new += 1
                print(key, {k: round(x["p"], 3) for k, x in ans.items()}, f"{round(time.time() - t1, 1)}s", flush=True)
    summ = dict(label=LABEL, build=getattr(be, "build", "?"), split=split, shard=shard,
                assigned=sum(len(us) for us in mine.values()), scored=len(_jsonl(dst)), scored_now=n_new,
                requests_now=n_req, not_scored=not_scored, wall_s=round(time.time() - t0, 1),
                s_per_request=round((time.time() - t0) / n_req, 1) if n_req else None, n_ctx=N_CTX)
    (SHARDS / f"{_tag(split, shard)}.json").write_text(json.dumps(summ, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in summ.items() if k != "not_scored"}), "not scored:", len(not_scored), flush=True)
    return summ


# ------------------------------------------------------------------------------------------------ compose (no model)
def compose(cands: list[dict], answers: dict[int, dict], cue: bool, cfg: dict) -> list[tuple[str, str]]:
    """`roles_pointer.read`'s decision fields from the stored answers, then `roles_pointer.decide` (the code read runs),
    then read's actors in candidate order."""
    ds = []
    for i, c in enumerate(cands):
        ans = answers[i]
        d = dict(value=c["value"], kind=c["kind"], sources=c["sources"], coherence=[],
                 p_author_pos=round(ans[cfg["prompt"]]["p"], 6), p_first=None, p_author_neg=None)
        if c["kind"] == "person":
            parts = [ans[n]["p"] for n in RP._as_list(cfg["prompt_first"])]
            d.update(p_first_parts=[round(x, 6) for x in parts], p_first=round(RP.geo_mean(parts), 6))
        ds.append(d)
    RP.decide(ds, cfg, cue)
    return [(d["value"], d["role"]) for d in ds if d["role"] != "not_an_author"]


def _collect(split: str) -> tuple[dict[int, dict], dict[int, dict[int, dict]], dict]:
    """Per affair: the runner's candidates (+ cue, identity flags), the answers per candidate index, why units are
    missing."""
    aff: dict[int, dict] = {}
    conflicts = []
    for p in sorted(SHARDS.glob(f"affairs__{split}__*.jsonl")):
        for f in _jsonl(p):
            if f["affair_id"] in aff and cands_sha(aff[f["affair_id"]]["candidates"]) != cands_sha(f["candidates"]):
                conflicts.append(f["id"])
            aff.setdefault(f["affair_id"], f)
    ans: dict[int, dict[int, dict]] = collections.defaultdict(dict)
    for p in sorted(SHARDS.glob(f"{split}__*.jsonl")):
        for f in _jsonl(p):
            ans[f["affair_id"]][f["idx"]] = f["answers"]
    why: dict = {}
    for p in sorted(SHARDS.glob(f"{split}__*.json")):
        why.update(json.loads(p.read_text()).get("not_scored") or {})
    if conflicts:
        raise SystemExit(f"shards disagree on the candidates of {conflicts}")
    return aff, ans, why


def pointer_8b(split: str, cfg: dict) -> dict[int, dict]:
    """{affair_id: dict(pairs or None, why)} for every affair of the split."""
    aff, ans, why = _collect(split)
    out = {}
    for r in load_rows(split):
        aid = r["affair_id"]
        f = aff.get(aid)
        if f is None:
            out[aid] = dict(pairs=None, why="not fetched or not run")
            continue
        miss = [i for i in range(len(f["candidates"])) if i not in ans[aid]]
        if miss:
            out[aid] = dict(pairs=None, why=f"{len(miss)} of {len(f['candidates'])} candidates unscored: "
                            + "; ".join(sorted({why.get(f"{r['id']}#{i}", "not run") for i in miss}))[:240])
            continue
        out[aid] = dict(pairs=compose(f["candidates"], ans[aid], f["cue"], cfg), why=None)
    return out


# ------------------------------------------------------------------------------------------------ refit on development
def refit(cfg: dict) -> dict:
    """tau, tau_first on the 8B's development answers by PREREG10 §7's rule (eval/p10/dev.py), the rest frozen."""
    from eval.p10 import dev as DV

    rows = load_rows("dev")
    gold = {d["affair_id"]: d for d in _dev_gold()}
    aff, ans, why = _collect("dev")
    complete = [r for r in rows if r["affair_id"] in aff
                and all(i in ans[r["affair_id"]] for i in range(len(aff[r["affair_id"]]["candidates"])))]
    drows = [dict(id=r["id"], affair_id=r["affair_id"], body=r["body"], stratum=r["stratum"],
                  gold=gold[r["affair_id"]]["gold"]) for r in complete]

    def preds(c: dict) -> dict:
        return {r["affair_id"]: compose(aff[r["affair_id"]]["candidates"], ans[r["affair_id"]], aff[r["affair_id"]]["cue"],
                                        c) for r in complete}

    def summary(c: dict) -> dict:
        rs = DV._rows_for(drows, {"pointer": preds(c)})
        return dict(DV._summ(S.pooled(rs, "pointer")), macro_f1=round(DV._macro(rs, "pointer"), 4),
                    per_body={b: DV._summ(S.pooled([x for x in rs if x["body"] == b], "pointer"))
                              for b in sorted({x["body"] for x in rs})})

    cov = dict(dev_affairs=len(rows), complete=len(complete), parliaments=sorted({r["body"] for r in complete}),
               text_identical=sum(bool(aff[r["affair_id"]]["text_identical"]) for r in complete),
               missing={r["id"]: ("not fetched or not run" if r["affair_id"] not in aff else "candidates unscored")
                        for r in rows if r not in complete})
    reg = json.loads(C.DEV_RESULTS.read_text())
    out = dict(coverage=cov, rule="eval/p10/dev.py (PREREG10 §7) on the 8B's development answers: tau x tau_first over "
               "dev.TAUS x dev.TAUS; highest macro pair F1 over the 6 development parliaments, ties -> pooled F1 -> "
               "pooled precision -> larger tau -> larger tau_first; prompts (staged_v3) and lone_first_needs_cue frozen",
               gateway_registered_dev=dict(selected={k: reg["selected"][k] for k in ("tau", "tau_first", "macro_f1", "f1",
                                                                                     "precision", "recall")}),
               frozen_on_dev_8b=summary(cfg) if complete else None)
    if not rows or len(complete) < len(rows):
        out.update(available=False, reason="the refit needs all 36 development affairs rebuilt and fully scored")
        return out
    grid = []
    for t in DV.TAUS:
        for tf in DV.TAUS:
            c = dict(cfg, tau=t, tau_first=tf)
            rs = DV._rows_for(drows, {"pointer": preds(c)})
            p = S.pooled(rs, "pointer")
            grid.append(dict(tau=t, tau_first=tf, macro_f1=round(DV._macro(rs, "pointer"), 4), **DV._summ(p)))
    best = max(grid, key=lambda g: (g["macro_f1"], round(g["f1"] or 0, 6), round(g["precision"] or 0, 6), g["tau"],
                                    g["tau_first"]))
    out.update(available=True, tau=best["tau"], tau_first=best["tau_first"],
               refit_on_dev_8b=summary(dict(cfg, tau=best["tau"], tau_first=best["tau_first"])),
               grid_top=sorted(grid, key=lambda g: (-g["macro_f1"], -(g["f1"] or 0)))[:15])
    return out


# ------------------------------------------------------------------------------------------------ scoring
def _rt(x):
    return json.loads(json.dumps(x))


def score_rows(ptr: dict[int, dict], runner_cands: dict[int, list] | None = None) -> list[dict]:
    """p10_arms.jsonl's rows (arms.join) with the given pointer pairs in place of the registered pointer; the registered
    gateway pointer is kept as `pointer_registered`. Candidate recall on the runner's candidates where available."""
    gold = {g["affair_id"]: g for g in _jsonl(C.GOLD)}
    off = {r["affair_id"]: r for r in _jsonl(C.R10 / "p10_offline.jsonl")}
    reg = {r["affair_id"]: r for r in _jsonl(C.R10 / "p10_pointer.jsonl")}
    committed = {r["affair_id"]: r["candidates"] for r in _jsonl(C.CANDS10)}
    out = []
    for aid in sorted(gold, key=lambda k: gold[k]["id"]):
        g = gold[aid]
        gp = [(p["name"], p["role"]) for p in g["people"]]
        arms = dict(pointer=[tuple(x) for x in (ptr[aid]["pairs"] or [])] if aid in ptr else [],
                    pointer_registered=[tuple(x) for x in reg[aid]["pointer"]],
                    **{k: [tuple(x) for x in off[aid][k]] for k in ("rules", "opd_first", "opd_joint", "cand_joint")})
        cands = (runner_cands or {}).get(aid) or committed[aid]
        out.append(dict(id=g["id"], affair_id=aid, body=g["body"], stratum=g["stratum"], cell=g["cell"], gold=gp,
                        arms={k: S.affair_row(v, gp) for k, v in arms.items()}, cand=S.cand_row(cands, gp),
                        pointer_run=bool(ptr.get(aid, {}).get("pairs") is not None)))
    return out


def _paired_diff(rows: list[dict], a: str, b: str, seed: int, n_boot: int) -> dict:
    """a - b in pooled precision, recall and F1 on the primary cell, with the registered parliament-cluster bootstrap
    (score.bootstrap's resampling scheme and seed); descriptive (no test)."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["body"], []).append(r)
    bodies = sorted(by)
    rnd = random.Random(seed)
    ms = ("precision", "recall", "f1")

    def d(rs):
        pa, pb = S.pooled(rs, a), S.pooled(rs, b)
        return {m: None if pa[m] is None or pb[m] is None else pa[m] - pb[m] for m in ms}
    xs = {m: [] for m in ms}
    for _ in range(n_boot):
        rs = [r for x in [rnd.choice(bodies) for _ in bodies] for r in by[x]]
        for m, v in d(rs).items():
            if v is not None:
                xs[m].append(v)
    obs = d(rows)
    return {m: dict(observed=obs[m], boot_ci95=[S._pct(xs[m], 0.025), S._pct(xs[m], 0.975)]) for m in ms}


def evaluate(ptr: dict[int, dict], runner_cands: dict[int, list] | None, text_ok: dict[int, bool], n_boot: int) -> dict:
    rows = score_rows(ptr, runner_cands)
    prim = [r for r in rows if r["cell"] == "primary"]
    sec = [r for r in rows if r["cell"] != "primary"]
    arms = S.ARMS + ("pointer_registered",)
    hyp = S.hypotheses(prim, C.SEED_BOOT, n_boot)
    sub = [r for r in prim if text_ok.get(r["affair_id"])]
    regp = _registered_pairs()
    agree = sum(sorted(map(tuple, ptr.get(r["affair_id"], {}).get("pairs") or [])) == sorted(regp[r["affair_id"]])
                for r in prim)
    return dict(primary=dict(table=S.table(prim, arms), candidates=S.candidate_recall(prim), hypotheses=hyp,
                             pointer_8b_minus_registered=_paired_diff(prim, "pointer", "pointer_registered", C.SEED_BOOT,
                                                                      n_boot),
                             affairs_same_pairs_as_registered=agree,
                             text_identical_subset=dict(affairs=len(sub), table={a: S.pooled(sub, a) for a in arms})
                             if sub else None),
                secondary_it=dict(note="Lugano (5192): the rules arm is in-sample there (roles-2); outside the family",
                                  table=S.table(sec, arms) if sec else None),
                coverage=dict(affairs=len(rows), pointer_run=sum(r["pointer_run"] for r in rows),
                              primary_pointer_run=sum(r["pointer_run"] for r in prim),
                              abstentions={r["id"]: ptr.get(r["affair_id"], {}).get("why") or "not run"
                                           for r in rows if not r["pointer_run"]},
                              note="an affair the 8B did not fully score is a pointer abstention (no pairs), never an "
                                   "exclusion (PREREG10 stop rule 2)"))


def _registered_pairs() -> dict[int, list]:
    return {r["affair_id"]: [tuple(x) for x in r["pointer"]] for r in _jsonl(C.R10 / "p10_pointer.jsonl")}


def check_registered(n_boot: int = C.N_BOOT) -> dict:
    """Consistency: the scaffold, fed the registered pointer, reproduces results/p10/p10_scores.json exactly."""
    reg = json.loads(C.SCORES.read_text())
    ptr = {aid: dict(pairs=p, why=None) for aid, p in _registered_pairs().items()}
    rows = score_rows(ptr)
    prim = [r for r in rows if r["cell"] == "primary"]
    sec = [r for r in rows if r["cell"] != "primary"]
    same_table = _rt(S.table(prim)) == reg["primary"]["table"]
    same_cand = _rt(S.candidate_recall(prim)) == reg["primary"]["candidates"]
    same_sec = _rt(S.table(sec)) == reg["secondary_it"]["table"]
    same_h = _rt(S.hypotheses(prim, C.SEED_BOOT, n_boot)) == reg["primary"]["hypotheses"] if n_boot == C.N_BOOT else None
    return dict(registered_table_reproduced=same_table, registered_candidates_reproduced=same_cand,
                registered_secondary_reproduced=same_sec, registered_hypotheses_reproduced=same_h)


def holds(reg: dict, res: dict) -> dict:
    out = {}
    for h in S.FAMILY:
        a, b = reg["primary"]["hypotheses"]["tests"][h], res["primary"]["hypotheses"]["tests"][h]
        out[h] = dict(registered=dict(observed=a["observed"], p_holm=a["p_holm"], verdict=a["verdict"]),
                      gguf_8b=dict(observed=b["observed"], p_holm=b["p_holm"], verdict_analogue=b["verdict"]),
                      holds=a["verdict"] == "confirmed" and b["verdict"] == "confirmed")
    return out


def merge(n_boot: int | None = None) -> dict:
    n_boot = n_boot or C.N_BOOT
    cfg = config()
    reg = json.loads(C.SCORES.read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    aff, _ans, _why = _collect("test")
    runner_cands = {aid: f["candidates"] for aid, f in aff.items()}
    text_ok = {aid: bool(f["text_identical"]) for aid, f in aff.items()}
    fetch_rep = {}
    for p in sorted(SHARDS.glob("fetch__*.json")):
        x = json.loads(p.read_text())
        fetch_rep[p.stem] = dict(affairs=x["affairs"], fetched=x["fetched"], text_identical=x["text_identical"],
                                 failed=x["failed"], via=dict(collections.Counter(
                                     d.get("via") for s in x["status"].values() for d in s["docs"].values())))
    rf = refit(cfg)  # development only; fixed before the test variant below is scored
    variants = {"frozen": dict(cfg)}
    if rf.get("available"):
        variants["refit_dev"] = dict(cfg, tau=rf["tau"], tau_first=rf["tau_first"])
    res, outs = {}, []
    ptrs = {k: pointer_8b("test", c) for k, c in variants.items()}
    for k, c in variants.items():
        r = evaluate(ptrs[k], runner_cands, text_ok, n_boot)
        res[k] = dict(thresholds=dict(tau=c["tau"], tau_first=c["tau_first"]), holds=holds(reg, r), **r)
    for row in load_rows("test"):
        aid = row["affair_id"]
        f = aff.get(aid) or {}
        outs.append(dict(id=row["id"], affair_id=aid, body=row["body"], cell=row["cell"],
                         text_identical=f.get("text_identical"), candidates_identical=f.get("candidates_identical"),
                         **{f"pointer_8b_{k}": ptrs[k][aid]["pairs"] for k in variants},
                         why_not=ptrs["frozen"][aid]["why"]))
    _write_jsonl(OUT / "p10_pointer_8b.jsonl", outs)
    shard_summ = {p.stem: {k: v for k, v in json.loads(p.read_text()).items() if k != "not_scored"}
                  for p in sorted(SHARDS.glob("*__*_of_*.json")) if not p.stem.startswith("fetch__")}
    out = dict(label=LABEL, build=BUILD, config=dict(cfg, note="data/p10/p10_config.json (frozen)"), refit=rf,
               variants=res, fetch=fetch_rep, shards=shard_summ,
               checks=dict(check_registered(n_boot), candidates_identical=sum(bool(f.get("candidates_identical"))
                                                                               for f in aff.values()),
                           text_identical=sum(text_ok.values()), test_affairs_fetched=len(aff)),
               method="eval/p10/score.py unchanged (affair_row, pooled, table, candidate_recall, hypotheses: paired "
                      "parliament-cluster bootstrap, seed 20261102, Holm) with the 8B pairs in the pointer's place; the "
                      "other arms are the committed registered outputs; verdicts are exploratory analogues, not tests of "
                      "the registered family")
    (OUT / "p10_8b_scores.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({k: {h: (round(v["primary"]["hypotheses"]["tests"][h]["observed"] or 0, 4),
                              v["primary"]["hypotheses"]["tests"][h]["verdict"]) for h in S.FAMILY}
                      for k, v in res.items()}, indent=1))
    print(json.dumps(dict(refit_available=rf.get("available"), checks=out["checks"]), indent=1))
    return out


# ------------------------------------------------------------------------------------------------ cli
def lockcheck() -> list[str]:
    """LOCK10's committed files (eval/prereg10/lock10.py also hashes WORK inputs, absent on runners) and the committed
    inputs pinned in pins.json."""
    d = json.loads((ROOT / "eval" / "prereg10" / "LOCK10").read_text())
    bad = [f for f, h in d["p10_files"].items() if not (ROOT / f).exists() or _file_sha(ROOT / f) != h]
    pins = json.loads(PINS.read_text())["files"] if PINS.exists() else {}
    badp = [f for f, h in pins.items() if not (ROOT / f).exists() or _file_sha(ROOT / f) != h]
    print(f"LOCK10: {len(d['p10_files'])} committed files " + ("intact" if not bad else "changed: " + ", ".join(bad)))
    print(f"pins: {len(pins)} committed inputs " + ("intact" if pins and not badp else
                                                    "MISSING" if not pins else "changed: " + ", ".join(badp)))
    return bad + badp + ([] if pins else [str(PINS)])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="EXPLORATORY: the local Apertus 8B as P10's role reader")
    ap.add_argument("cmd", choices=["lockcheck", "export", "plan", "fetch", "features", "merge"])
    ap.add_argument("--split", choices=["dev", "test"], default="test")
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--shards", type=int, default=1)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if a.cmd == "lockcheck":
        return 1 if lockcheck() else 0
    if a.cmd == "export":
        export()
    elif a.cmd == "plan":
        print(json.dumps(plan(a.split, a.shards), indent=1))
    elif a.cmd == "fetch":
        fetch(a.split, a.shard)
    elif a.cmd == "features":
        features(a.split, a.shard)
    else:
        merge()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
