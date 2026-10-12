"""Third-party inventory (docs/licences.md, docs/sbom/): the committed SBOMs match the locks, the image SBOM names the
components Gegenprobe runs with their licences, the vulnerability allowlist carries reasons, and CI regenerates and
scans with hash-pinned tools."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SBOM = ROOT / "docs" / "sbom"
WORKFLOWS = ROOT.parent / ".github" / "workflows"

_spec = importlib.util.spec_from_file_location("gp_sbom_tool", ROOT / "tools" / "sbom.py")
sbom = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sbom)


def _lock_pins(name: str) -> dict[str, str]:
    return {m.group(1).lower(): m.group(2)
            for m in re.finditer(r"^([A-Za-z0-9_.-]+)==([^\s;]+)[^\n]* \\$", (ROOT / name).read_text(), re.M)}


@pytest.mark.parametrize("env,lock", [("runtime", "requirements.lock"), ("dev", "requirements-dev.lock")])
def test_python_sbom_lists_exactly_the_lock(env, lock):
    bom = json.loads((SBOM / f"python-{env}.cdx.json").read_text())
    assert bom["bomFormat"] == "CycloneDX" and bom["metadata"]["component"]["name"] == "gegenprobe"
    got = {k: v[0] for k, v in sbom.components(bom).items()}
    want = {re.sub(r"[-_.]+", "-", k): v for k, v in _lock_pins(lock).items()}
    assert got == want
    assert all(v[2] for v in sbom.components(bom).values()), "every component carries a declared licence"


def test_image_sbom_names_what_gegenprobe_runs():
    bom = json.loads((SBOM / "image-system.cdx.json").read_text())
    by = {c["name"]: c for c in bom["components"]}
    lic = {n: sbom._lic(by[n]) for n in ("poppler-utils", "libpoppler126", "tesseract-ocr", "libtesseract5", "liblept5")}
    assert lic["poppler-utils"] == lic["libpoppler126"] == ["GPL-2.0-only OR GPL-3.0-only"]
    assert lic["tesseract-ocr"] == lic["libtesseract5"] == ["Apache-2.0"] and lic["liblept5"] == ["BSD-2-Clause"]
    commit, shas = sbom._tessdata()
    for lang, sha in shas.items():
        c = by[f"tessdata_fast/{lang}.traineddata"]
        assert c["version"] == commit and c["hashes"][0]["content"] == sha and sbom._lic(c) == ["Apache-2.0"]
    assert sbom._lic(next(c for c in bom["components"] if c.get("purl", "").startswith("pkg:generic/python@"))) == ["PSF-2.0"]
    assert not [c for c in bom["components"] if c.get("purl", "").startswith("pkg:pypi/")], "pip/setuptools/wheel are removed"
    props = {p["name"]: p["value"] for p in bom["metadata"]["component"]["properties"]}
    df = (ROOT / "Dockerfile").read_text()
    assert props["gegenprobe:base-image"] in df
    assert "pip uninstall -y -q pip setuptools wheel" in df and "pip 24.0" in props["gegenprobe:removed-by-dockerfile"]
    apt = [ln.split("\t") for ln in (SBOM / "image-apt-layer.tsv").read_text().splitlines() if not ln.startswith("#")]
    assert len(apt) - 1 == sum(1 for c in bom["components"] if c["properties"][0]["value"].startswith("apt-get"))


def test_allowlist_rows_have_reasons_and_only_cover_the_gguf_lock():
    rows = sbom.allowlist(SBOM / "vuln-allowlist.tsv")
    assert rows and all(r["lock"] == "requirements-gguf.lock" and len(r["justification"]) > 100 for r in rows)
    audit = json.loads((SBOM / "audit.json").read_text())
    assert audit["failing"] == 0
    assert {i for v in audit["locks"].values() for i in v["accepted"]} <= {f"{r['package']} {r['id']}" for r in rows}
    for lock in ("requirements.lock", "requirements-dev.lock", "requirements-audit.lock"):
        assert audit["locks"][lock]["known_vulnerabilities"] == 0
        assert audit["locks"][lock]["packages"] == len(_lock_pins(lock))


def test_gguf_pins_include_the_url_requirement():
    assert "llama-cpp-python==0.3.35" in sbom.pins(ROOT / "requirements-gguf.lock")


def test_audit_tools_are_hash_pinned():
    lock = (ROOT / "requirements-audit.lock").read_text()
    for pkg in ("pip-audit==2.10.1", "cyclonedx-bom==7.5.0"):
        assert re.search(rf"^{re.escape(pkg)} \\\n    --hash=sha256:[0-9a-f]{{64}}", lock, re.M), pkg
    reqs = re.findall(r"^([A-Za-z0-9_.-]+)==[^\n]* \\$", lock, re.M)
    blocks = re.findall(r"^[A-Za-z0-9_.-]+==[^\n]* \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)", lock, re.M)
    assert len(reqs) == len(blocks) == 50


@pytest.mark.skipif(not WORKFLOWS.exists(), reason="workflows live in the repository root")
def test_ci_regenerates_the_sbom_and_gates_on_known_vulnerabilities():
    ci = (WORKFLOWS / "ci.yml").read_text()
    job = ci[ci.index("  sbom-audit:"):ci.index("  make-run:")]
    assert "pip install -q --require-hashes -r requirements-audit.lock" in job
    assert "cyclonedx-py environment" in job and "tools/sbom.py compare" in job
    assert "pip-audit --strict" in job and "tools/sbom.py audit-summary" in job and "requirements-gguf.lock" in job
    assert '! grep -iE "^(pip|setuptools|wheel|pytest)=="' in ci  # nightly-smoke: no installer or test runner in the image


def test_licences_page_lists_every_runtime_component():
    page = (ROOT / "docs" / "licences.md").read_text()
    for name, ver in {**_lock_pins("requirements.lock"), **_lock_pins("requirements-dev.lock")}.items():
        assert re.search(rf"\b{re.escape(name)}\b.*\b{re.escape(ver)}\b", page, re.I), name
    for name in ("poppler-utils", "tesseract-ocr", "tessdata_fast", "liblept5", "llama-cpp-python", "diskcache"):
        assert name in page
