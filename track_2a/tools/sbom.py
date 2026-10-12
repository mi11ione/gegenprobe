"""Software bill of materials helpers (stdlib only; run with `python -I tools/sbom.py ...`). docs/licences.md is the
human-readable table; docs/sbom/ holds the machine-readable files.

  compare COMMITTED REGENERATED     two CycloneDX JSON files list the same components (name, version, purl, licences) and
                                    the same root component; exit 1 with the difference. CI job `sbom-audit` regenerates
                                    docs/sbom/python-*.cdx.json with cyclonedx-py from the hash-pinned locks and compares.
  pins LOCK                         `name==version` for every requirement of a hash-pinned lock, URL requirements
                                    included (llama-cpp-python's wheel URL -> llama-cpp-python==0.3.35), for pip-audit
                                    --no-deps (pip-audit does not resolve URL requirements by itself).
  ignore-args ALLOWLIST             `--ignore-vuln ID` for each row of docs/sbom/vuln-allowlist.tsv (id, lock, package,
                                    justification, reviewed); a row without a justification is an error.
  audit-summary OUT LOCK=JSON ... [--date=D]  docs/sbom/audit.json from pip-audit's JSON output per lock (`-f json`): packages
                                    scanned, known vulnerabilities found, those the allowlist accepts, the rest;
                                    `removed:NAME=JSON` records a scan of packages the Dockerfile uninstalls (not gated).
  image BASE_SPDX APT_TSV OUT       docs/sbom/image-system.cdx.json: the image's system layer. BASE_SPDX is the SPDX
                                    document Docker publishes as an attestation of the digest-pinned base image (blob
                                    sha256:8e82fecd..., fetched from registry-1.docker.io; its in-toto envelope or the bare
                                    document), APT_TSV is docs/sbom/image-apt-layer.tsv (the apt layer as apt printed it in
                                    CI); the pinned tessdata_fast models come from src/gegenprobe/ocrguard.py. The base image's
                                    Python packages (pip, setuptools with its vendored packages, wheel) are listed as
                                    removed: the Dockerfile uninstalls them after the hash-pinned install. An apt row that
                                    the base already holds at the same version is listed once (as base).
  image-scan OUT NAME=GRYPE_JSON ... [--gate=NAME,...] [--date=D]
                                    docs/sbom/image-scan.json from grype's JSON output (`grype -o json`) per scan target:
                                    findings (vulnerability, package, version) by severity and fix state, the HIGH and
                                    CRITICAL ones Debian or upstream has fixed ("fixable"), those in packages the
                                    Dockerfile uninstalls (pip, setuptools with its vendored packages, wheel, packaging:
                                    recorded, not gated), those docs/sbom/image-vuln-allowlist.tsv accepts with a reason,
                                    and the rest (failing). Exit 1 when a scan named in --gate (default: every scan) has a
                                    failing finding. CI job `image-scan` gates the built image with it.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_IMAGE = "python:3.11.17-slim-bookworm@sha256:0a310eeecf4e1f5a0743f9a6520c90c88d089c903ca5fd283f501e3a805f5f89"
BASE_AMD64 = "sha256:8a00ecb83ed9d0864dfd102a1bdb2067fda907ceb30bb86d09da9ee558b19590"
BASE_SBOM_BLOB = "sha256:8e82fecd7f2bdf51d09344ca57edd1762cc3a1021d1a358ba1fc5a0588ded92b"
# the base image before R20 (python 3.11.14, Debian 12.13): its system layer had fixable HIGH/CRITICAL vulnerabilities in
# CPython and 21 Debian packages (docs/licences.md, "Image scan"); docs/sbom/image-scan.json keeps that scan for comparison
PREVIOUS_BASE_IMAGE = "python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d"
TESSDATA_REPO = "https://github.com/tesseract-ocr/tessdata_fast"


def _lic(c: dict) -> list[str]:
    out = []
    for e in c.get("licenses") or []:
        if "expression" in e:
            out.append(e["expression"])
        else:
            lic = e.get("license") or {}
            out.append(lic.get("id") or lic.get("name") or "")
    return sorted(out)


def components(bom: dict) -> dict[str, tuple]:
    return {re.sub(r"[-_.]+", "-", c["name"]).lower(): (c.get("version"), c.get("purl"), tuple(_lic(c)))
            for c in bom.get("components") or []}


def compare(a: Path, b: Path) -> list[str]:
    ba, bb = json.loads(a.read_text(encoding="utf-8")), json.loads(b.read_text(encoding="utf-8"))
    errs = []
    ra, rb = (ba.get("metadata") or {}).get("component") or {}, (bb.get("metadata") or {}).get("component") or {}
    if (ra.get("name"), ra.get("version")) != (rb.get("name"), rb.get("version")):
        errs.append(f"root component {ra.get('name')} {ra.get('version')} != {rb.get('name')} {rb.get('version')}")
    ca, cb = components(ba), components(bb)
    for k in sorted(set(ca) | set(cb)):
        if ca.get(k) != cb.get(k):
            errs.append(f"{k}: committed {ca.get(k)} != regenerated {cb.get(k)}")
    return errs


def pins(lock: Path) -> list[str]:
    out = []
    for line in lock.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", line)
        if m:
            out.append(f"{m.group(1)}=={m.group(2)}")
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+) @ \S+/([A-Za-z0-9_.]+)-([0-9][^-]*)-[^/\s]*\.whl", line)
        if m:
            out.append(f"{m.group(1)}=={m.group(3)}")
    return sorted(set(out))


def allowlist(path: Path) -> list[dict]:
    rows = [r for r in csv.DictReader(io.StringIO("".join(
        ln for ln in path.read_text(encoding="utf-8").splitlines(keepends=True) if not ln.startswith("#"))), delimiter="\t")]
    for r in rows:
        if not (r.get("id") and r.get("justification", "").strip() and r.get("reviewed")):
            raise SystemExit(f"{path}: row {r} needs an id, a justification and a review date")
    return rows


def audit_summary(pairs: list[str], allow: Path, date: str) -> dict:
    ok = {r["id"]: r["lock"] for r in allowlist(allow)}
    out = {"tool": "pip-audit 2.10.1 (requirements-audit.lock), PyPI vulnerability service, --strict --disable-pip",
           "run": date, "locks": {}}
    for pair in pairs:
        lock, js = pair.split("=", 1)
        deps = json.loads(Path(js).read_text(encoding="utf-8"))["dependencies"]
        found = sorted({(d["name"], d["version"], v["id"]) for d in deps for v in d.get("vulns") or []})
        if lock.startswith("removed:"):  # scanned, then uninstalled by the Dockerfile: recorded, not gated
            out.setdefault("removed_from_image", {})[lock[8:]] = {
                "packages": len(deps), "known_vulnerabilities": len(found),
                "found": [f"{n} {v} {i}" for n, v, i in found]}
            continue
        accepted = [f for f in found if ok.get(f[2]) == Path(lock).name]
        out["locks"][Path(lock).name] = {
            "packages": len(deps), "known_vulnerabilities": len(found),
            "accepted": [f"{n} {v} {i}" for n, v, i in accepted],
            "failing": [f"{n} {v} {i}" for n, v, i in found if (n, v, i) not in accepted]}
    out["packages"] = sum(v["packages"] for v in out["locks"].values())
    out["failing"] = sum(len(v["failing"]) for v in out["locks"].values())
    out["accepted"] = sum(len(v["accepted"]) for v in out["locks"].values())
    return out


# packages the Dockerfile uninstalls after the hash-pinned install (a base-image scan still finds them)
REMOVED_BY_DOCKERFILE = re.compile(r"/site-packages/(?:pip|setuptools|wheel|packaging)(?:[-/]|$)")
HIGH_CRITICAL = ("Critical", "High")


def image_scan(pairs: list[str], allow: Path, date: str, gate: list[str] | None = None) -> dict:
    """grype JSON per target -> counts and the gate (see `image-scan` above). A finding is one (vulnerability, package,
    version, type), however many files grype matched it in; `fixable` = grype's fix state "fixed" (a fixed version
    exists in the distribution or upstream)."""
    ok = {(r["id"], r["package"]) for r in allowlist(allow)} if allow.exists() else set()
    out: dict = {"tool": "", "run": date, "fail_on": "fixable HIGH or CRITICAL, not removed by the Dockerfile, not in "
                 "docs/sbom/image-vuln-allowlist.tsv", "scans": {}}
    for pair in pairs:
        name, js = pair.split("=", 1)
        d = json.loads(Path(js).read_text(encoding="utf-8"))
        desc = d.get("descriptor") or {}
        out["tool"] = f"grype {desc.get('version', '?')}"
        src = (d.get("source") or {}).get("target")
        found: dict[tuple, dict] = {}
        for m in d.get("matches") or []:
            v, a = m["vulnerability"], m["artifact"]
            key = (v["id"], a["name"], a["version"], a["type"])
            paths = [loc.get("path", "") for loc in a.get("locations") or []]
            x = found.setdefault(key, {"severity": v.get("severity", "Unknown"),
                                       "state": (v.get("fix") or {}).get("state") or "unknown",
                                       "fix": sorted((v.get("fix") or {}).get("versions") or []), "removed": False})
            x["removed"] = x["removed"] or any(REMOVED_BY_DOCKERFILE.search(p) for p in paths)
        by: dict[str, dict[str, int]] = {}
        for x in found.values():
            row = by.setdefault(x["severity"], {})
            row[x["state"]] = row.get(x["state"], 0) + 1

        def line(k: tuple, found: dict = found) -> str:
            x = found[k]
            return f"{k[3]} {k[1]} {k[2]} {k[0]} {x['severity']}" + (f" (fixed in {', '.join(x['fix'])})" if x["fix"] else "")

        hc = sorted(k for k, x in found.items() if x["severity"] in HIGH_CRITICAL)
        fixable = [k for k in hc if found[k]["state"] == "fixed"]
        removed = [k for k in fixable if found[k]["removed"]]
        accepted = [k for k in fixable if k not in removed and (k[0], k[1]) in ok]
        failing = [k for k in fixable if k not in removed and k not in accepted]
        types = sorted({k[3] for k in fixable})
        dist = d.get("distro") or {}
        out["scans"][name] = {
            "target": src.get("userInput") if isinstance(src, dict) else src,
            "distro": " ".join(str(x) for x in (dist.get("name"), dist.get("version")) if x),
            "db_built": ((desc.get("db") or {}).get("status") or {}).get("built"),
            "gated": gate is None or name in gate,
            "findings": len(found),
            "by_severity_and_fix_state": {s: dict(sorted(r.items())) for s, r in sorted(by.items())},
            "high_critical": len(hc),
            "high_critical_fixable": len(fixable),
            "high_critical_fixable_by_type": {t: sum(1 for k in fixable if k[3] == t) for t in types},
            "high_critical_without_fix": len(hc) - len(fixable),
            "removed_by_dockerfile": [line(k) for k in removed],
            "accepted": [line(k) for k in accepted],
            "failing": [line(k) for k in failing],
        }
    out["failing"] = sum(len(s["failing"]) for s in out["scans"].values() if s["gated"])
    return out


def _tessdata() -> tuple[str, dict[str, str]]:
    src = (ROOT / "src" / "gegenprobe" / "ocrguard.py").read_text(encoding="utf-8")
    commit = re.search(r'^TESSDATA_COMMIT = "([0-9a-f]{40})"', src, re.M).group(1)
    block = re.search(r"^TESSDATA_SHA256 = \{(.*?)\}", src, re.M | re.S).group(1)
    return commit, dict(re.findall(r'"(\w+)": "([0-9a-f]{64})"', block))


def image(base_spdx: Path, apt_tsv: Path) -> dict:
    doc = json.loads(base_spdx.read_text(encoding="utf-8"))
    doc = doc.get("predicate", doc)
    comps, removed = [], []
    for p in doc.get("packages") or []:
        purl = next((r["referenceLocator"] for r in p.get("externalRefs") or [] if r.get("referenceType") == "purl"), None)
        if not purl:
            continue
        if purl.startswith("pkg:pypi/"):  # pip, setuptools (with its _vendor packages) and wheel: uninstalled by the Dockerfile
            removed.append(f"{p['name']} {p.get('versionInfo', '')}")
            continue
        c = {"type": "library" if purl.startswith("pkg:pypi") else "application" if purl.startswith("pkg:generic")
             else "operating-system" if p["name"] == "debian" else "library",
             "name": p["name"], "version": p.get("versionInfo", ""), "purl": purl,
             "properties": [{"name": "gegenprobe:layer", "value": "base image (Docker's SBOM attestation)"}]}
        lic = "PSF-2.0" if purl.startswith("pkg:generic/python@") else p.get("licenseDeclared")
        if lic and lic not in ("NOASSERTION", "NONE"):
            c["licenses"] = [{"expression": lic}]
        comps.append(c)
    rows = [r for r in csv.DictReader(io.StringIO("".join(
        ln for ln in apt_tsv.read_text(encoding="utf-8").splitlines(keepends=True) if not ln.startswith("#"))), delimiter="\t")]
    base_debs = {(c["name"], c["version"]) for c in comps if c["purl"].startswith("pkg:deb/")}
    in_base = sorted(f"{r['package']} {r['version']}" for r in rows if (r["package"], r["version"]) in base_debs)
    for r in rows:
        if f"{r['package']} {r['version']}" in in_base:  # requested by the apt layer, already in the base at that version
            continue
        purl = (f"pkg:deb/debian/{r['package']}@{r['version']}?arch={r['arch']}&distro=debian-12"
                + (f"&upstream={r['source']}" if r["source"] != r["package"] else ""))
        c = {"type": "library", "name": r["package"], "version": r["version"], "purl": purl,
             "properties": [{"name": "gegenprobe:layer", "value": "apt-get layer (Dockerfile)"},
                            {"name": "gegenprobe:debian-source", "value": f"{r['source']} {r['source_version']}"},
                            {"name": "gegenprobe:licence-basis", "value": r["licence_basis"]}]}
        if r["licence"] and r["licence_basis"].startswith("spdx"):
            c["licenses"] = [{"expression": r["licence"]}]
        elif r["licence"]:
            c["licenses"] = [{"license": {"name": n.strip()}} for n in r["licence"].split(" | ")]
        comps.append(c)
    commit, shas = _tessdata()
    for lang, sha in sorted(shas.items()):
        comps.append({"type": "data", "name": f"tessdata_fast/{lang}.traineddata", "version": commit,
                      "licenses": [{"license": {"id": "Apache-2.0"}}], "hashes": [{"alg": "SHA-256", "content": sha}],
                      "externalReferences": [{"type": "distribution", "url": f"{TESSDATA_REPO}/raw/{commit}/{lang}.traineddata"}],
                      "properties": [{"name": "gegenprobe:layer", "value": "tessdata (ocrguard install-pinned, sha256)"}]})
    comps.sort(key=lambda c: (c["properties"][0]["value"], c["name"]))
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
            "metadata": {"component": {"type": "container", "name": "gegenprobe", "version": "0.1.0",
                                       "description": "system layer of the Docker image (Dockerfile; linux/amd64)",
                                       "properties": [{"name": "gegenprobe:base-image", "value": BASE_IMAGE},
                                                      {"name": "gegenprobe:base-image-amd64", "value": BASE_AMD64},
                                                      {"name": "gegenprobe:base-sbom-blob", "value": BASE_SBOM_BLOB},
                                                      {"name": "gegenprobe:removed-by-dockerfile",
                                                       "value": "; ".join(sorted(removed))},
                                                      {"name": "gegenprobe:apt-requested-already-in-base",
                                                       "value": "; ".join(in_base)}]}},
            "components": comps}


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "compare" and len(argv) == 3:
        errs = compare(Path(argv[1]), Path(argv[2]))
        for e in errs:
            print("SBOM DIFF", e)
        print(f"sbom compare: {len(components(json.loads(Path(argv[1]).read_text())))} components, {len(errs)} differences")
        return 1 if errs else 0
    if cmd == "pins" and len(argv) == 2:
        print("\n".join(pins(Path(argv[1]))))
        return 0
    if cmd == "ignore-args" and len(argv) == 2:
        print(" ".join(f"--ignore-vuln {r['id']}" for r in allowlist(Path(argv[1]))))
        return 0
    if cmd == "audit-summary" and len(argv) >= 3:
        date = next((a.split("=", 1)[1] for a in argv[2:] if a.startswith("--date=")), "")
        rep = audit_summary([a for a in argv[2:] if not a.startswith("--")], ROOT / "docs/sbom/vuln-allowlist.tsv", date)
        Path(argv[1]).write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
        print(f"audit: {rep['packages']} packages, {rep['failing']} failing, {rep['accepted']} accepted (allowlist)")
        return 1 if rep["failing"] else 0
    if cmd == "image-scan" and len(argv) >= 3:
        opt = dict(a[2:].split("=", 1) for a in argv[2:] if a.startswith("--") and "=" in a)
        gate = [g for g in opt["gate"].split(",") if g] if "gate" in opt else None
        rep = image_scan([a for a in argv[2:] if not a.startswith("--")], ROOT / "docs/sbom/image-vuln-allowlist.tsv",
                         opt.get("date", ""), gate)
        Path(argv[1]).write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
        for name, sc in rep["scans"].items():
            print(f"image scan {name}: {sc['findings']} findings, {sc['high_critical']} HIGH/CRITICAL, "
                  f"{sc['high_critical_fixable']} of them fixable ({len(sc['removed_by_dockerfile'])} in packages the "
                  f"Dockerfile removes, {len(sc['accepted'])} accepted, {len(sc['failing'])} failing)"
                  + ("" if sc["gated"] else " [not gated]"))
            for f in sc["failing"]:
                print(f"  FAIL {f}")
        return 1 if rep["failing"] else 0
    if cmd == "image" and len(argv) == 4:
        Path(argv[3]).write_text(json.dumps(image(Path(argv[1]), Path(argv[2])), indent=1, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
