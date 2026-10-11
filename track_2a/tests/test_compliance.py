"""robots.txt compliance (docs/incidents.md, 2026-10-09/10): the project-wide audit tool (gegenprobe.compliance.audit) and
the fallback to OPD's own copies (gegenprobe.compliance.mirror) that every fetch path inherits through src/sitecustomize.py.
Offline: robots.txt texts are inline, urlopen is stubbed."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import types

import pytest

from gegenprobe import net, pdftext
from gegenprobe.compliance import audit, mirror
from gegenprobe.paths import DATA, RESULTS, ROOT

TI_ROBOTS = ("User-agent: *\nAllow: /\nDisallow: /poteri/gc/ricerca-messaggi-e-atti/ricerca/\n"
             "Disallow: /user_librerie/php/GC/allegato.php\n")
ORIG = "https://www4.ti.ch/user_librerie/php/GC/allegato.php?allid=131009"
COPY = "https://files.openparldata.ch/doc/TI/" + "ab" * 32
PDF = b"%PDF-1.4\n% OPD copy\n"


class _Resp(io.BytesIO):
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ---------------------------------------------------------------- mirror: routing
def test_patch_net_routes_mapped_urls_to_opd_and_is_idempotent(monkeypatch):
    calls = []
    fake = types.SimpleNamespace(open_url=lambda url, *a, **kw: calls.append(url) or "resp")
    monkeypatch.setattr(mirror, "_map", {mirror.key(ORIG): COPY})
    mirror.patch_net(fake)
    first = fake.open_url
    mirror.patch_net(fake)
    assert fake.open_url is first and mirror.installed(fake)
    fake.open_url(ORIG)
    fake.open_url(ORIG.replace("allegato.php", "allegato%2Ephp"))  # spelling variants map to the same document
    fake.open_url("https://www4.ti.ch/poteri/gc/")  # unmapped: unchanged
    fake.open_url("file:///tmp/x.pdf")
    assert calls == [COPY, COPY, "https://www4.ti.ch/poteri/gc/", "file:///tmp/x.pdf"]


def test_key_ignores_percent_escapes():
    assert mirror.key("https://x.ch/a%20b?c=1") == mirror.key("https://x.ch/a b?c=1")


def test_load_reads_entries(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(dict(entries=[dict(url=ORIG, mirror_url=COPY), dict(url="https://a.ch/x", mirror_url=None)])))
    assert mirror.load(p) == {mirror.key(ORIG): COPY}


def test_net_in_this_process_is_patched():
    assert mirror.installed(net)


@pytest.mark.parametrize("env", [{"PYTHONPATH": "src:."}, {"PYTHONPATH": "/app/src:/app"}])
def test_sitecustomize_patches_net_at_import(env, tmp_path):
    """Every entry point (Makefile, Dockerfile, units) gets the routing from sitecustomize, before any driver runs."""
    pp = env["PYTHONPATH"].replace("/app", str(ROOT))
    code = ("import sys; from gegenprobe import net; m = sys.modules['_gegenprobe_mirror']; "
            "assert m.installed(net), 'not patched'; print('ok')")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                       env={"PYTHONPATH": pp, "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}, timeout=120)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


@pytest.fixture
def stub_web(monkeypatch, tmp_path):
    """robots.txt for both hosts inline; the parliament's document path must never be requested."""
    monkeypatch.setattr(net, "_robots", {})
    monkeypatch.setattr(net, "_robots_note", {})
    monkeypatch.setattr(net, "_robots_lenient", {})
    monkeypatch.setattr(net, "_wait", lambda host: None)
    monkeypatch.setattr(pdftext, "PDF_CACHE", tmp_path / "pdf")
    seen = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        seen.append(url)
        if url == "https://www4.ti.ch/robots.txt":
            return _Resp(TI_ROBOTS.encode())
        if url == "https://files.openparldata.ch/robots.txt":
            raise net.urllib.error.HTTPError(url, 404, "nf", {}, None)
        if url == COPY:
            return _Resp(PDF)
        pytest.fail(f"unexpected request: {url}")

    monkeypatch.setattr(net.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setitem(net.open_url.__globals__, "_map", {mirror.key(ORIG): COPY})
    return seen


def test_locked_fetch_pdf_reads_opds_copy_not_the_parliament(stub_web):
    """pdftext.fetch_pdf (LOCK2-5) with a pinned sha256, as eval/rederive.py and eval/replay_all.py call it: the original
    is disallowed, the bytes come from OPD's copy, and www4.ti.ch sees no request at all."""
    sha = hashlib.sha256(PDF).hexdigest()
    got, path = pdftext.fetch_pdf(ORIG, expect_sha256=sha)
    assert got == sha and path.read_bytes() == PDF
    assert not any(u.startswith("https://www4.ti.ch") for u in stub_web)
    assert COPY in stub_web


def test_driver_open_url_falls_back_to_opd(stub_web):
    """eval/run_arms.py, eval/run_arms_p2.py and eval/p6/run_8b.py call net.open_url directly."""
    with net.open_url(ORIG, timeout=30, tries=2) as r:
        assert r.read() == PDF
    assert not any(u.startswith("https://www4.ti.ch") for u in stub_web)


def test_unmapped_disallowed_url_is_still_refused(stub_web):
    with pytest.raises(net.Disallowed):
        net.get("https://www4.ti.ch/user_librerie/php/GC/allegato.php?allid=1")
    assert "https://www4.ti.ch/robots.txt" in stub_web and not any("allid=1" in u for u in stub_web)


def test_sampler_path_uses_the_same_layer(stub_web):
    """Samplers fetch through pdftext.fetch_pdf without a pinned hash (eval/gold2/sample.py:fetch_one and its users)."""
    sha, _ = pdftext.fetch_pdf(ORIG)
    assert sha == hashlib.sha256(PDF).hexdigest()


# ---------------------------------------------------------------- audit tool
def test_classify_error():
    assert audit.classify_error("Disallowed: https://www.sz.ch/route/x (robots.txt ...)") == (
        "refused", "https://www.sz.ch/route/x")
    assert audit.classify_error("FetchError: not_a_pdf: https://a.ch/x.doc returned 7 bytes")[0] == "get_discarded"
    assert audit.classify_error("not a PDF")[0] == "get_discarded"
    assert audit.classify_error("text too short after extraction (0 chars)") == ("download", None)
    assert audit.classify_error("HTTPError: HTTP Error 404: Not Found") == ("failed", None)


def test_judge_rfc9309_vs_first_match():
    v, fm = audit.judge(ORIG, TI_ROBOTS, "HTTP 200")
    assert v == "disallowed" and fm is True  # the incident: first match allowed it
    assert audit.judge("https://www4.ti.ch/poteri/gc/", TI_ROBOTS, "HTTP 200")[0] == "allowed"
    assert audit.judge(ORIG, None, "HTTP 404 (no restrictions)")[0] == "no_restrictions"
    assert audit.judge(ORIG, None, "unreachable (URLError)")[0] == "host_unreachable"


def test_strongest_request_kind():
    assert audit.strongest(["refused", "download"]) == "download"
    assert audit.strongest(["failed", "headers_only"]) == "headers_only"


def test_affair_log_reconstructs_question_and_answer(tmp_path):
    p = tmp_path / "log.jsonl"
    rows = [dict(affair_id=1, body="TI", accepted=True, q_error=None, a_error=None),
            dict(affair_id=2, body="TI", accepted=False, q_error="Disallowed: https://www4.ti.ch/q2", a_error=None),
            dict(affair_id=3, body="TI", accepted=False, q_error=None,
                 a_error="FetchError: not_a_pdf: https://www4.ti.ch/a3 returned 9 bytes without a PDF header")]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    pairs = {("TI", a): dict(question=dict(url=f"https://www4.ti.ch/q{a}", doc_id=10 + a),
                             answer=dict(url=f"https://www4.ti.ch/a{a}", doc_id=20 + a)) for a in (1, 2, 3)}
    got = [(r["url"].rsplit("/", 1)[1], r["request"]) for r in audit.affair_log("m", p, pairs, {})]
    assert got == [("q1", "download"), ("a1", "download"), ("q2", "refused"), ("q3", "download"), ("a3", "get_discarded")]


def test_summarize_counts_distinct_urls_and_lists_disallowed():
    robots = {"https://www4.ti.ch": dict(status="HTTP 200", text=TI_ROBOTS, read="2026-10-11"),
              "https://files.openparldata.ch": dict(status="HTTP 404 (no restrictions)", text=None, read="2026-10-11")}
    rows = [dict(module="gold", url=ORIG, request="download", source="a", date="2026-10-09", doc_id=1, sha256="s"),
            dict(module="gold", url=ORIG, request="download", source="log", date="2026-10-09", doc_id=1),
            dict(module="ci", url=ORIG, request="download", source="ci", date="2026-10-10"),
            dict(module="gold", url="https://www4.ti.ch/user_librerie/php/GC/allegato.php?allid=2", request="refused",
                 source="log", date="2026-10-10"),
            dict(module="gold", url=COPY, request="download", source="a", date="2026-10-11")]
    s = audit.summarize(rows, robots)
    g = s["modules"]["gold"]
    assert g["distinct_urls"] == 3 and g["disallowed_distinct_urls_by_request"] == {"download": 1, "refused": 1}
    assert [x["url"] for x in g["disallowed_urls"]] == [ORIG] and g["disallowed_urls"][0]["doc_ids"] == ["1"]
    h = s["hosts"]["https://www4.ti.ch"]
    assert h["disallowed_download_records"] == 3 and h["disallowed_allowed_by_first_match"] == 1
    assert s["hosts"]["https://files.openparldata.ch"]["disallowed_distinct_urls_by_request"] == {}


# ---------------------------------------------------------------- committed outputs agree
AUDIT = RESULTS / "compliance" / "robots_audit_all.json"
MAP = DATA / "compliance" / "mirror_urls.json"


@pytest.mark.skipif(not AUDIT.exists() or not MAP.exists(), reason="audit or mirror map not built")
def test_every_disallowed_eval_document_has_an_opd_copy():
    a = json.loads(AUDIT.read_text())
    m = {mirror.key(e["url"]): e for e in json.loads(MAP.read_text())["entries"]}
    eval_mods = [k for k in a["modules"] if k.startswith(("gold", "p6", "convert_demo", "ci_make_run"))]
    need = {x["url"] for k in eval_mods for x in a["modules"][k]["disallowed_urls"] if x["request"] == "download"}
    assert need, "the audit lists the Ticino documents"
    missing = sorted(u for u in need if not (m.get(mirror.key(u)) or {}).get("mirror_url"))
    assert not missing, missing
    assert all(m[mirror.key(u)]["mirror_url"].startswith("https://files.openparldata.ch/doc/") for u in need)


@pytest.mark.skipif(not AUDIT.exists(), reason="audit not built")
def test_audit_offline_rerun_reproduces_the_committed_verdicts(tmp_path, monkeypatch):
    """--offline re-judges with the committed robots.txt copies; the per-host verdicts must not move."""
    a = json.loads(AUDIT.read_text())
    texts = {h: (audit.ROBOTS_DIR / (h.split("://", 1)[1] + ".txt")) for h in a["hosts"] if h.startswith("http")}
    for h, v in a["hosts"].items():
        if v.get("disallowed_urls"):
            t = texts[h].read_text(encoding="utf-8")
            assert hashlib.sha256(t.encode()).hexdigest() == v["robots_sha256"]
            assert all(audit.judge(x["url"], t, v["robots"])[0] == "disallowed" for x in v["disallowed_urls"])
