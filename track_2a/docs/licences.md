# Third-party licences, SBOM and vulnerability scan

What Gegenprobe ships, installs or runs, with each component's licence and how it is used. The machine-readable bills of
materials are in [`docs/sbom/`](sbom/) (CycloneDX 1.6 JSON). CI job `sbom-audit` (`.github/workflows/ci.yml`) regenerates
the Python ones from the hash-pinned locks, compares them with the committed files and scans every lock for known
vulnerabilities; it fails on any finding the [allowlist](sbom/vuln-allowlist.tsv) does not accept with a reason. CI job
`image-scan` builds the image and scans it, Debian packages and CPython included ([Image scan](#image-scan)).
Numbers on this page: `results/report/r19c_numbers.json` (`python -m report.r19c_numbers`), bound in `claims.d/r19_c.tsv`,
and `results/report/r20c_numbers.json` (`python -m report.r20c_numbers`), bound in `claims.d/r20_c.tsv`.

| file | what it lists | how it is made |
|---|---|---|
| [`sbom/python-runtime.cdx.json`](sbom/python-runtime.cdx.json) | the 8 Python packages the image and the nightly venv install (`requirements.lock`) | `cyclonedx-py environment` over a clean venv installed with `--require-hashes` (CI job `sbom-audit`) |
| [`sbom/python-dev.cdx.json`](sbom/python-dev.cdx.json) | the 6 test and lint packages (`requirements-dev.lock`; not in the image) | the same, over `requirements-dev.lock` |
| [`sbom/image-system.cdx.json`](sbom/image-system.cdx.json) | the image's system layer: 217 components (151 from the base image, 62 Debian packages from the Dockerfile's apt layer, 4 OCR models) | `python -I tools/sbom.py image`: Docker's SPDX attestation of the digest-pinned base image, plus [`sbom/image-apt-layer.tsv`](sbom/image-apt-layer.tsv) (the apt layer as apt printed it in CI run 38197201361; ca-certificates, which that build upgraded, now comes with the base at the same version), plus the tessdata pins of `src/gegenprobe/ocrguard.py` |
| [`sbom/audit.json`](sbom/audit.json) | the pip-audit run of 2026-10-12 over every lock | `python -I tools/sbom.py audit-summary` over pip-audit's JSON (the CI job writes the same file as an artifact) |
| [`sbom/image-scan.json`](sbom/image-scan.json) | the grype scan of 2026-10-12: the current and the previous base image, the system layer | `python -I tools/sbom.py image-scan` over grype's JSON (CI job `image-scan` writes the same file for the image it builds, as an artifact) |

## Gegenprobe itself

Code Apache-2.0 (`LICENSE`); data and results CDLA-Permissive-2.0, derived from OpenParlData.ch (CC BY 4.0, "Source:
OpenParlData.ch"); report CC-BY-4.0 (`docs/LICENSE-report.txt`). Apertus 8B and its GGUF chain: Apache-2.0, checked in
CI ([runbook, Checked in CI](runbook.md#checked-in-ci)).

## Python packages in the image and the nightly venv (`requirements.lock`)

| component | version | licence (declared in the wheel) | how Gegenprobe uses it |
|---|---|---|---|
| pydantic | 2.14.0 | MIT | schema v0.1/v0.2 models and record validation |
| pydantic-core | 2.50.0 | MIT | pydantic's compiled core |
| annotated-types | 0.8.0 | MIT | dependency of pydantic |
| typing-extensions | 4.16.0 | PSF-2.0 | dependency of pydantic |
| typing-inspection | 0.4.4 | MIT | dependency of pydantic |
| jinja2 | 3.1.6 | BSD-3-Clause (wheel classifier "BSD License") | renders the local 8B's chat template in a sandbox (`gguf_guard.py`, `llm.py`) |
| markupsafe | 3.0.4 | BSD-3-Clause | dependency of jinja2 |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0; the Linux wheels also bundle OpenBLAS (BSD-3-Clause), LAPACK (BSD-3-Clause-Open-MPI), libgfortran (GPL-3.0-or-later WITH GCC-exception-3.1) and libquadmath (LGPL-2.1-or-later), per the wheel's `LICENSE.txt` | log-probability arithmetic and calibration (`llm.py`, `convert/calibrate.py`), the evaluation's statistics |

Test-only packages are not in this lock: pytest and its dependencies moved to `requirements-dev.lock`, which the image
does not install (CI job `nightly-smoke` checks that no `pip`, `setuptools`, `wheel` or `pytest` distribution is in the
built image).

## Optional local 8B (`docker build --build-arg GGUF=1`, `requirements-gguf.lock`)

| component | version | licence | how Gegenprobe uses it |
|---|---|---|---|
| llama-cpp-python | 0.3.35 (CPU wheel, sha256-pinned per architecture) | MIT (bundles llama.cpp / ggml, MIT) | runs the pinned Apertus 8B GGUF on CPU for date suggestions |
| diskcache | 5.6.3 | Apache-2.0 | required by llama-cpp-python; Gegenprobe never creates a diskcache (see the scan below) |

## Test, lint and supply-chain tools (CI and development only)

| component | version | licence | lock |
|---|---|---|---|
| pytest | 9.1.1 | MIT | `requirements-dev.lock` |
| pluggy | 1.6.0 | MIT | `requirements-dev.lock` |
| iniconfig | 2.3.1 | MIT | `requirements-dev.lock` |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | `requirements-dev.lock` |
| pygments | 2.21.0 | BSD-2-Clause | `requirements-dev.lock` |
| ruff | 0.16.10 | MIT | `requirements-dev.lock` |
| pip-audit | 2.10.1 | Apache-2.0 | `requirements-audit.lock` (50 hash-pinned packages, own venv) |
| cyclonedx-bom | 7.5.0 | Apache-2.0 | `requirements-audit.lock` |

## The image's system components

Base: `python:3.11.17-slim-bookworm`, pinned by digest (Dockerfile); Debian 12 "bookworm" (12.15) plus CPython 3.11.17
(PSF-2.0). Its licences per package are in `sbom/image-system.cdx.json`, as Docker's attestation declares them. The
Dockerfile's apt layer applies Debian's updates (`apt-get upgrade`) and adds 62 Debian packages; the ones Gegenprobe runs
or loads (ca-certificates is requested by the Dockerfile and already in the base):

| component | version | licence | how Gegenprobe uses it |
|---|---|---|---|
| poppler-utils, libpoppler126 | 22.12.0-2+deb12u3 | GPL-2.0-only OR GPL-3.0-only (debian/copyright: "GPL-2 or GPL-3") | `pdftotext` (page-exact text) and `pdftoppm` (page images for OCR), each run as a separate process through `subprocess` |
| tesseract-ocr, libtesseract5 | 5.3.0-2 | Apache-2.0 | OCR of image-only scans, run as a separate process |
| liblept5 (Leptonica) | 1.82.0-3+b3 | BSD-2-Clause | image library tesseract loads |
| tessdata_fast deu, fra, ita, eng | commit 87416418657359cb625c412a48b6e1d6d41c29bd, sha256 per file | Apache-2.0 ([LICENSE](https://github.com/tesseract-ocr/tessdata_fast/blob/main/LICENSE)) | the OCR language models; downloaded at build time and checked file by file (`ocrguard.py`); tesseract reads only these (`TESSDATA_PREFIX`) |
| tesseract-ocr-eng, tesseract-ocr-osd | 1:4.1.0-2 | Apache-2.0 | installed as tesseract's dependencies; not read (the pinned models above are) |
| ca-certificates | 20250419~deb12u1 | MPL-2.0 (Mozilla's certificate data) and GPL-2+ (Debian's scripts) | TLS trust for every HTTPS fetch |
| make | 4.3-4.1 | GPL-3.0-or-later | installed with the image's tools; the job does not need it |

The other 54 packages of the apt layer are libraries those tools load (fonts, image codecs, cairo/pango, curl, ICU,
libxml2, NSS); each row of [`sbom/image-apt-layer.tsv`](sbom/image-apt-layer.tsv) gives its Debian source package and
the licence names its machine-readable `debian/copyright` declares, or says where the free-text one is.

**GPL tools run as separate programs.** Gegenprobe does not link poppler or any other GPL code: it starts `pdftotext`
and `pdftoppm` as separate processes and reads their output, which the FSF treats as separate programs, not one
combined work ([GPL FAQ, "mere aggregation"](https://www.gnu.org/licenses/gpl-faq.html#MereAggregation)). Gegenprobe's
own code therefore stays Apache-2.0. The repository publishes a Dockerfile, not an image. Whoever builds the image and
passes it on also passes on the GPL binaries in it (poppler, make, and GPL libraries of the base system), with the duty
to offer their source; Debian's source packages for the exact versions (snapshot.debian.org, sources.debian.org) meet
it.

## Vulnerability scan

pip-audit 2.10.1, PyPI vulnerability service, `--strict --disable-pip`, run on 2026-10-12 (`sbom/audit.json`): 66
packages across the four locks, 0 failing, 1 accepted by the allowlist:

| lock | packages | known vulnerabilities |
|---|---|---|
| `requirements.lock` (image, nightly venv) | 8 | none |
| `requirements-dev.lock` | 6 | none |
| `requirements-audit.lock` | 50 | none |
| `requirements-gguf.lock` (optional local 8B) | 2 | diskcache 5.6.3: PYSEC-2026-2447 (CVE-2025-69872), accepted |

- **diskcache, accepted.** diskcache unpickles what it reads from its cache directory, so whoever can write that
  directory can run code in the reading process; no fixed version exists. Gegenprobe never creates a diskcache, and the
  image's only writable paths are `GP_WORK`, `out/` and a private `/tmp` owned by the job's uid. The reason is in
  [`sbom/vuln-allowlist.tsv`](sbom/vuln-allowlist.tsv); the CI job accepts it for `requirements-gguf.lock` only.
- **The base image's installers, removed.** The base image ships pip 24.0, setuptools 79.0.1 (with its vendored
  packages, among them wheel 0.45.1), wheel 0.46.3 and packaging 26.3: 20 packages with 9 known vulnerabilities (pip,
  setuptools and its vendored wheel and jaraco-context). Nothing in the image runs them after the build, so the
  Dockerfile uninstalls them (pip, setuptools, wheel, packaging) right after the hash-pinned install. The inert wheels
  under Python's `ensurepip/_bundled/` stay (used only by `python -m ensurepip`).
- **Debian packages and CPython:** scanned, next section.

## Image scan

grype 0.119.0 (release archive pinned by sha256), its vulnerability database of 2026-10-11, run on 2026-10-12
([`sbom/image-scan.json`](sbom/image-scan.json)). A finding is one vulnerability in one package version; *fixable*
means Debian, or upstream for CPython, has published a fixed version. The gate fails on a fixable HIGH or CRITICAL
finding unless the Dockerfile removes the package or [`sbom/image-vuln-allowlist.tsv`](sbom/image-vuln-allowlist.tsv)
accepts it with a reason; the allowlist is empty.

| scanned | HIGH or CRITICAL | fixable | fixable and not removed by the Dockerfile |
|---|---|---|---|
| previous base, `python:3.11.14-slim-bookworm` (Debian 12.13), by digest | 162 | 91 | 89 would fail the gate: 76 in Debian packages, 13 in CPython 3.11.14 |
| current base, `python:3.11.17-slim-bookworm` (Debian 12.15), by digest | 73 | 2 | 0 (the 2 are in setuptools' vendored packages) |
| system layer of the current image (its SBOM: base and apt layer; Debian packages only) | 80 | 0 | 0 |

- **What changed.** The image now builds on `python:3.11.17-slim-bookworm` (digest-pinned on 12 Oct) and applies
  Debian's updates in its apt layer, so a later build also gets fixes published after the base image was made. Of the
  previous base's fixable findings, the 2 that the Dockerfile removes were in setuptools' vendored packages.
- **Without a fix.** 71 HIGH or CRITICAL findings in the current base have no fixed version in Debian 12 (Debian lists
  them as not fixed yet, or as not to be fixed in this release). An upgrade cannot remove them; the scan lists them, and a
  rebuild picks up each fix once Debian publishes it.
- **How it ran.** No Docker on the scanning host: grype read both base images by digest straight from the registry
  (`grype registry:IMAGE@DIGEST --platform linux/amd64`) and the system layer through `sbom/image-system.cdx.json`
  (`grype sbom:...`), then `python -I tools/sbom.py image-scan`. CI job `image-scan` builds the image and runs the same
  gate on it (`grype docker:gegenprobe:scan`), on every push; its artifact holds the scan of the image it built.
