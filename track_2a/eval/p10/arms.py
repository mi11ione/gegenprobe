"""P10 arms (eval/prereg10/PREREG10.md §4). The arms read the same extracted texts the packets show; they never read a
label, and no annotator sees their output.

    PYTHONPATH=src:. .venv/bin/python -m eval.p10.arms offline
        no model: candidates, rules, opd_first, opd_joint, cand_joint -> data/p10/p10_candidates.jsonl,
        results/p10/p10_offline.jsonl
    PYTHONPATH=src:. .venv/bin/python -m eval.p10.arms pointer --backend gateway:swiss-ai/apertus-v1.5-8b:2a-p10:2.0
        the Apertus role pointer -> results/p10/p10_pointer.jsonl (+ the model cache)
    PYTHONPATH=src:. .venv/bin/python -m eval.p10.arms join      the gold and the arms -> results/p10/p10_arms.jsonl
    PYTHONPATH=src:. .venv/bin/python -m eval.p10.arms pointer --backend gguf --out results/p10/p10_pointer_8b.jsonl
        exploratory: the same pointer on the local Apertus 8B GGUF (exact forced choice; not in the family)

Arms (each prints (name, role) pairs; names are printed text):
  pointer     (a) `convert.roles_pointer.read` on the candidates of `convert.role_candidates`, with the frozen
              configuration data/p10/p10_config.json (tau, coherence rules, view); every name is a located candidate.
  rules       (b) the frozen converter role rules `convert.roles.extract(q, a, body)["actors"]` (roles-2, sha256 in
              LOCK10), unchanged.
  opd_first   (c1) no model, no document: OPD's contributor list of the affair (frozen `affair.meta.vendor` file),
  opd_joint   contributors whose harmonised role is author-like (OPD_AUTHOR / OPD_COSIGN), persons and groups, in
              OPD's order (position, id), mapped to roles by `opd_pairs` with the two readings of several OPD authors:
              'first_and_co' (the first is first signatory, the rest co-signatories) and 'joint' (all joint
              authors). H3a compares the pointer with the stronger of the two in every bootstrap resample.
  cand_joint  (c2) no model: the shared candidates with a trivial role: one candidate -> sole_author, several -> every
              candidate joint_author.
"""

from __future__ import annotations

import argparse
import json
import sys

from gegenprobe.convert import role_candidates as RC
from gegenprobe.convert import roles as R
from gegenprobe.convert import roles_pointer as RP

OPD_AUTHOR = ("author", "primary")
OPD_COSIGN = ("cosign", "co-signer")


def lang_of(stratum: str | None, q: list[str]) -> str:
    """The prompt language: the parliament's language; for a multilingual one, the first DE/FR/IT language of the
    member's text (`roles.language_of_text`), else de."""
    if stratum in RP.LANGS:
        return stratum
    for lg in R.language_of_text(q or []):
        if lg in RP.LANGS:
            return lg
    return "de"


def rules_pairs(q: list[str], a: list[str], body: str) -> list[tuple[str, str]]:
    x = R.extract(q, a, body)
    return [(p["name"]["value"], p["role"]) for p in x["actors"]]


def _opd_name(c: dict) -> str | None:
    if c.get("type") == "person":
        n = " ".join(x for x in (c.get("firstname"), c.get("lastname")) if x)
        return n or c.get("fullname")
    return c.get("fullname")


def opd_pairs(meta: dict | None, multi: str = "first_and_co") -> list[tuple[str, str]]:
    """OPD's contributors mapped to roles. author-like A (OPD_AUTHOR), co-signers S (OPD_COSIGN), each in OPD's order:
    |A| = 1 and no S -> sole_author; |A| = 1 and S -> A first_signatory, S co_signatory; |A| >= 2 -> `multi`:
    'first_and_co' (A[0] first_signatory, the rest of A and S co_signatory) or 'joint' (every A joint_author, S
    co_signatory); no A but S -> S[0] first_signatory, the rest co_signatory."""
    if not meta:
        return []
    seen, A, S = set(), [], []
    for c in meta.get("contributors") or []:
        role = c.get("role_harmonized")
        if role not in OPD_AUTHOR + OPD_COSIGN:
            continue
        n = _opd_name(c)
        k = (c.get("type"), c.get("person_id") or c.get("group_id") or n)
        if not n or k in seen:
            continue
        seen.add(k)
        (A if role in OPD_AUTHOR else S).append(n)
    if len(A) == 1:
        return [(A[0], "sole_author")] if not S else [(A[0], "first_signatory")] + [(s, "co_signatory") for s in S]
    if len(A) >= 2:
        if multi == "joint":
            return [(x, "joint_author") for x in A] + [(s, "co_signatory") for s in S]
        return [(A[0], "first_signatory")] + [(x, "co_signatory") for x in A[1:] + S]
    if S:
        return [(S[0], "first_signatory")] + [(s, "co_signatory") for s in S[1:]]
    return []


def cand_joint_pairs(cands: list[dict]) -> list[tuple[str, str]]:
    if len(cands) == 1:
        return [(cands[0]["value"], "sole_author")]
    return [(c["value"], "joint_author") for c in cands]


def pointer_pairs(res: dict) -> list[tuple[str, str]]:
    return [(x["name"]["value"], x["role"]) for x in res["actors"]]


# ------------------------------------------------------------------------------------------------ the registered run
def _load_test():
    from eval.p10 import common as C
    from eval.p10 import packets as PK
    from gegenprobe.affair import meta

    rows = C._jsonl(C.AFFAIRS)
    if not rows:
        raise SystemExit(f"{C.AFFAIRS} missing: draw first")
    M = meta.load(C.META10)
    N = meta.body_names(C.NAMES10)
    return C, PK, rows, M, N


def _gold_first(C) -> None:
    """Order of operations (PREREG10 §8): the arms run only after the merged gold exists (and is committed)."""
    if not C.GOLD.exists():
        raise SystemExit(f"{C.GOLD} missing: merge and commit the gold before running any arm")


def offline() -> dict:
    C, PK, rows, M, N = _load_test()
    _gold_first(C)
    C.R10.mkdir(parents=True, exist_ok=True)
    with open(C.CANDS10, "w", encoding="utf-8") as fc, open(C.R10 / "p10_offline.jsonl", "w", encoding="utf-8") as fo:
        for e in rows:
            pages = PK.pages_of(e)
            q, a = pages["question"], pages["answer"]
            cd = RC.candidates(q, a, N.get(e["body"], []))
            fc.write(json.dumps(dict(affair_id=e["affair_id"], **cd), ensure_ascii=False) + "\n")
            fo.write(json.dumps(dict(affair_id=e["affair_id"], body=e["body"], stratum=e["stratum"],
                                     rules=rules_pairs(q, a, e["body"]),
                                     opd_first=opd_pairs(M.get(e["affair_id"]), "first_and_co"),
                                     opd_joint=opd_pairs(M.get(e["affair_id"]), "joint"),
                                     cand_joint=cand_joint_pairs(cd["candidates"])), ensure_ascii=False) + "\n")
    return dict(affairs=len(rows), candidates=str(C.CANDS10))


def pointer(spec: str, out: str | None = None) -> dict:
    from eval import arms as EA

    C, PK, rows, M, N = _load_test()
    _gold_first(C)
    cfg = json.loads(C.CONFIG.read_text())
    be = EA.backend(spec)
    if be is None:
        raise SystemExit("the pointer arm needs a model backend")
    cands = {r["affair_id"]: r for r in C._jsonl(C.CANDS10)}
    if len(cands) != len(rows):
        raise SystemExit("run `arms offline` first (the candidates are written there)")
    dest = C.R10 / "p10_pointer.jsonl" if out is None else __import__("pathlib").Path(out)
    n, stopped = 0, None
    with open(dest, "w", encoding="utf-8") as f:
        for e in rows:
            pages = PK.pages_of(e)
            q, a = pages["question"], pages["answer"]
            try:
                res = RP.read(be, q, a, cands[e["affair_id"]]["candidates"], lang_of(e["stratum"], q), cfg["pointer"])
            except RuntimeError as x:  # stop rule: the budget cap refuses the call; nothing after it is run
                if "BUDGET" not in str(x):
                    raise
                stopped = f"budget cap reached at affair {e['affair_id']}: {x}"
                break
            f.write(json.dumps(dict(affair_id=e["affair_id"], pointer=pointer_pairs(res), result=res),
                               ensure_ascii=False) + "\n")
            n += 1
    served = sorted(getattr(be, "served", set()))
    new_fp = sorted(set(served) - set(cfg.get("dev_fingerprints") or []))
    return dict(affairs=n, of=len(rows), stopped=stopped, build=be.build, served=served,
                fingerprints_not_seen_in_development=new_fp, out=str(dest))


def join() -> dict:
    """One row per affair: the gold pairs, each arm's pairs and match counts (results/p10/p10_arms.jsonl)."""
    from eval.p10 import common as C
    from eval.p10 import score as S

    gold = {g["affair_id"]: g for g in C._jsonl(C.GOLD)}
    off = {r["affair_id"]: r for r in C._jsonl(C.R10 / "p10_offline.jsonl")}
    ptr = {r["affair_id"]: r for r in C._jsonl(C.R10 / "p10_pointer.jsonl")}
    cands = {r["affair_id"]: r for r in C._jsonl(C.CANDS10)}
    if not (set(gold) == set(off)) or not set(ptr) <= set(gold):
        raise SystemExit("gold, offline arms and pointer arm cover different affairs")
    # stop rule: an affair the pointer did not reach (budget cap) counts as an abstention (no pair), never as excluded
    out = []
    for aid in sorted(gold, key=lambda k: gold[k]["id"]):
        g = gold[aid]
        gp = [(p["name"], p["role"]) for p in g["people"]]
        arms = dict(pointer=[tuple(x) for x in (ptr[aid]["pointer"] if aid in ptr else [])],
                    **{k: [tuple(x) for x in off[aid][k]] for k in ("rules", "opd_first", "opd_joint", "cand_joint")})
        out.append(dict(id=g["id"], affair_id=aid, body=g["body"], stratum=g["stratum"], cell=g["cell"], gold=gp,
                        pred={k: v for k, v in arms.items()},
                        arms={k: S.affair_row(v, gp) for k, v in arms.items()},
                        cand=S.cand_row(cands[aid]["candidates"], gp), pointer_run=aid in ptr))
    C.R10.mkdir(parents=True, exist_ok=True)
    with open(C.ARMS, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return dict(affairs=len(out), out=str(C.ARMS))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["offline", "pointer", "join"])
    ap.add_argument("--backend", default="gateway:swiss-ai/apertus-v1.5-8b:2a-p10:2.0")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    r = offline() if a.cmd == "offline" else pointer(a.backend, a.out) if a.cmd == "pointer" else join()
    print(json.dumps(r, indent=1))
    sys.exit(0)
