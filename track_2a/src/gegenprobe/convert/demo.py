"""`make run` step 4: sample documents through the cascade (metadata -> rules -> Apertus closed-set pointer), validated.

Documents: data/convert/demo_docs.json (dev split only, never held-out; plus the BE 2024.RRGR.91 RRB from the repair sample).
PDFs are fetched by pinned sha256 (pdftext.fetch_pdf) and never committed; offline, uncached documents are skipped.

Per document
  1 cascade, rules path (no model): -> schema_v0_1.DocExtraction (pydantic-validated), span re-check of every value,
    footer-distractor and self-deletion harnesses (validate.harness)
  2 Apertus pointer on the same document (every document, not only the cascade residue, so its margin is visible):
      live backend (ctx["backend"]: LLM_BASE_URL or GGUF) -> fresh scores, compared with the committed cache;
      otherwise   -> replay of the committed hash-keyed cache (data/model_cache); no cached entry -> "rules-only"
  3 cascade with the pointer on the residue, when θ for the build is committed (data/convert/theta/<build>.json)

Live-vs-cache tolerance (fixed): same decision and |Δ margin| <= 1.0 nat. Basis: the measured prefill-vs-decode noise on the
Public AI vLLM backend is σ = 0.26 nats per log-probability (spikes/live §a); a margin combines lp(null) and a logsumexp
over candidates, so 1.0 nat is ~2.7σ of a difference of two such terms. A live endpoint that is not the committed build is
reported, not failed: θ does not transfer across builds (spikes/inversions F2), so its decisions are shown as uncalibrated.

Status: FAIL only on a real check failure (invalid schema object, span re-check, distractor chosen, live/cache disagreement on
the committed build). Missing network or missing cache entries give SKIP / rules-only, never FAIL.
"""
from __future__ import annotations

import json
import os
import urllib.parse
from pathlib import Path

from .. import llm, pdftext
from ..paths import DATA, WORK
from ..validate import distractor, recheck, self_deletion
from . import cascade, pointer, rules

DEMO = DATA / "convert" / "demo_docs.json"
THETA_DIR = DATA / "convert" / "theta"
COMMITTED_BUILD = "publicai:swiss-ai/apertus-v1.5-8b"   # the build whose scores and θ are committed
TOL_MARGIN = 1.0


def _theta(build: str) -> float | None:
    p = THETA_DIR / f"{llm._slug(build)}.json"
    return json.loads(p.read_text())["answer_date"]["theta"] if p.exists() else None


def replay_backend():
    """Cache-only backend for the committed build: never touches the network."""
    be = llm.OpenAICompat(base_url="http://offline.invalid", api_key="", model="swiss-ai/apertus-v1.5-8b",
                          build=COMMITTED_BUILD, cache_readonly=True)
    be.offline = True
    return be


def live_backend(kind: str, out: Path):
    """Live backend whose results go to out/model_cache (never into the committed cache). Returns (backend, θ-build)."""
    if kind == "gguf":
        be = llm.GGUF()
        be.cache = llm.ModelCache("live:" + be.build, root=out / "model_cache")
        return be, be.build
    be = llm.OpenAICompat()
    host = urllib.parse.urlsplit(be.base).netloc
    calib = f"publicai:{be.model}" if host == "api.publicai.co" else be.model
    be.cache = llm.ModelCache("live:" + calib, root=out / "model_cache")
    return be, calib


def _pages(d: dict, online: bool) -> tuple[dict | None, str]:
    p = pdftext.PDF_CACHE / f"{d['sha256']}.pdf"
    if not p.exists():
        if not online:
            return None, "offline and PDF not cached"
        try:
            pdftext.fetch_pdf(d["url"], expect_sha256=d["sha256"])
        except Exception as e:  # noqa: BLE001 - network/source failures are reported, not fatal
            return None, f"fetch failed: {type(e).__name__}: {str(e)[:120]}"
    return pdftext.extract(d["sha256"], ocr=True), ""


def _rules_converter(lang: str, image_only: bool, extractor: str):
    def conv(pages: list[str], field: str):
        rec = dict(doc_id="opd:harness", extractor=extractor,
                   fields={"answer_date": cascade.answer_date(dict(pages=pages, lang=lang, image_only=image_only), None, None)})
        return cascade.to_schema(rec, pages=pages).answer_date
    return conv


def _checks(x, pages: list[str]) -> list[dict]:
    out = []
    for name in ("answer_date", "recommendation", "related_affair"):
        v = getattr(x, name)
        if v is not None and v.kind == "value" and v.page is not None:
            c = recheck(v, pages)
            out.append(dict(field=name, check="span", ok=c.ok, code=c.code, detail=c.detail))
    return out


def run_doc(d: dict, ctx: dict, live, live_build: str | None, replay) -> dict:
    t, why = _pages(d, ctx.get("online", False))
    if t is None:
        return dict(name=d["name"], status="SKIP", reason=why)
    pages, img = t["pages"], t["image_only"]
    lang = d["lang"] if d.get("lang") in ("de", "fr", "it") else {"fr": "fr", "it": "it", "oc": "it"}.get(d["cell"][:2], "de")
    meta = dict(source="canton" if d["doc_id"].startswith("be-ogd") else "opd", url=d["url"], language=lang,
                n_pages=len(pages), image_only=img)
    res = dict(name=d["name"], doc_id=d["doc_id"], cell=d["cell"], extractor=t["extractor"], expected=d["expected_answer_date"],
               checks=[])
    # 1 rules path
    rec = cascade.convert(dict(pages=pages, lang=lang, image_only=img, affair_type=d.get("affair_type"), body=d.get("body"),
                               doc_id=d["doc_id"], sha256=d["sha256"], extractor=t["extractor"]), backend=None)
    x = cascade.to_schema(rec, pages=pages, doc=meta)
    res["rules"] = json.loads(x.model_dump_json())
    res["checks"] += _checks(x, pages)
    conv = _rules_converter(lang, img, t["extractor"])
    for h in (distractor(conv, pages, "answer_date", lang=lang), self_deletion(conv, pages, "answer_date")):
        res["checks"].append(dict(field="answer_date", check=h.test, ok=h.result != "fail", code=h.result, detail=h.detail,
                                  before=h.before, after=h.after))
    # 2 pointer: replay (committed build) and live
    theta_c = _theta(COMMITTED_BUILD)
    try:
        p = pointer.answer_date(replay, pages, lang, theta_c if theta_c is not None else 0.0, anchors=rules.anchors(pages))
        res["pointer_replay"] = dict(value=p.value if theta_c is not None else None, margin=p.margin, theta=theta_c,
                                     argmax=max(p.candidates, key=lambda c: c[1])[0] if p.candidates else None,
                                     n_candidates=len(p.candidates), build=COMMITTED_BUILD)
    except llm.CacheMiss:
        res["pointer_replay"] = None
    if live is not None:
        th = _theta(live_build)
        p = pointer.answer_date(live, pages, lang, th if th is not None else 0.0, anchors=rules.anchors(pages))
        lv = dict(margin=p.margin, theta=th, build=live_build, calibrated=th is not None,
                  argmax=max(p.candidates, key=lambda c: c[1])[0] if p.candidates else None, n_candidates=len(p.candidates))
        lv["value"] = p.value if th is not None else None
        res["pointer_live"] = lv
        rp = res.get("pointer_replay")
        if rp and live_build == COMMITTED_BUILD and p.candidates:
            same = (rp["margin"] > theta_c) == (p.margin > theta_c) and (p.margin > theta_c or rp["argmax"] == lv["argmax"])
            dm = abs(rp["margin"] - p.margin)
            res["checks"].append(dict(field="answer_date", check="live_vs_cache", ok=same and dm <= TOL_MARGIN,
                                      code="ok" if same and dm <= TOL_MARGIN else "drift", detail=f"|Δmargin|={dm:.2f} nats"))
    # 3 cascade with the pointer on the residue (committed θ; live backend if it is the committed build, else replay)
    be = live if (live is not None and live_build == COMMITTED_BUILD) else replay
    if theta_c is not None:
        try:
            rec2 = cascade.convert(dict(pages=pages, lang=lang, image_only=img, affair_type=d.get("affair_type"),
                                        doc_id=d["doc_id"], sha256=d["sha256"], extractor=t["extractor"]),
                                   backend=be, thetas={"answer_date": theta_c})
            x2 = cascade.to_schema(rec2, pages=pages, doc=meta)
            res["cascade"] = json.loads(x2.model_dump_json())
            res["checks"] += _checks(x2, pages)
        except llm.CacheMiss:
            res["cascade"] = None
    a = res.get("cascade") or res["rules"]
    got = a["answer_date"].get("value") if a["answer_date"]["kind"] == "value" else None
    res["answer_date"] = dict(value=got, route=a["answer_date"]["route"],
                              null_reason=a["answer_date"].get("null_reason"), matches_expected=got == d["expected_answer_date"])
    res["status"] = "FAIL" if any(not c["ok"] and c["check"] != "self_deletion" for c in res["checks"]) else "PASS"
    return res


def main(ctx: dict) -> dict:
    out = Path(ctx.get("out", "out"))
    od = out / "convert_samples"
    od.mkdir(parents=True, exist_ok=True)
    if (WORK / "tessdata").exists() and not os.environ.get("TESSDATA_PREFIX"):
        os.environ["TESSDATA_PREFIX"] = str(WORK / "tessdata")
    live, live_build = (None, None)
    if ctx.get("backend") in ("openai", "gguf"):
        live, live_build = live_backend(ctx["backend"], out)
    replay = replay_backend()
    docs = json.loads(DEMO.read_text())["docs"]
    rows = []
    for d in docs:
        r = run_doc(d, ctx, live, live_build, replay)
        rows.append(r)
        (od / f"{d['name']}.json").write_text(json.dumps(r, indent=1, ensure_ascii=False, default=str))
    done = [r for r in rows if r["status"] != "SKIP"]
    fails = [r["name"] for r in rows if r["status"] == "FAIL"]
    n_check = sum(len(r["checks"]) for r in done)
    sd = [c for r in done for c in r["checks"] if c["check"] == "self_deletion"]
    match = sum(r["answer_date"]["matches_expected"] for r in done)
    ptr = sum(1 for r in done if r.get("pointer_replay") or r.get("pointer_live"))
    summary = (f"{len(done)}/{len(docs)} docs converted, {n_check} checks, {len(fails)} failing; answer date = expected "
               f"{match}/{len(done)}; pointer scores for {ptr} docs ({'live ' + str(live_build) if live else 'replay'}); "
               f"self-deletion {sum(c['code'] == 'pass' for c in sd)} pass / {sum(c['code'] == 'fail' for c in sd)} fail / "
               f"{sum(c['code'] == 'skipped' for c in sd)} n/a")
    status = "FAIL" if fails else ("SKIP" if not done else "PASS")
    table = [dict(doc=r["name"], status=r["status"], expected=r.get("expected"), got=(r.get("answer_date") or {}).get("value"),
                  route=(r.get("answer_date") or {}).get("route"), reason=r.get("reason")) for r in rows]
    return dict(status=status, summary=summary, failing=fails, docs=table)
