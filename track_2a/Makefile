# Gegenprobe (Track 2A, OpenParlData). Judges: `make run` (Docker, CPU, clean checkout).
# Development targets run on the host with .venv (python 3.11); every target is re-runnable and writes under results/.
.PHONY: schema-v02 parts-detect qa-detect dev-install gold-dev-fetch site deploy-site figures run test lint claims census census-corrected census-scan census-replay census-hash repair repair-network adapters-write adapters-canary repair-manifest nightly-offline nightly-smoke nightly-notify-test convert eval report install-nightly docker-build

PY ?= .venv/bin/python
IMAGE ?= gegenprobe:latest
export PYTHONPATH := src:.

# ---------------------------------------------------------------- judges' entry point (Docker)
# Container hardening: never uid 0 (a root caller runs as the image's unprivileged uid 10001, which then owns out/ and
# .work/make-run), read-only root filesystem, private /tmp (tmpfs), all capabilities dropped, no privilege escalation.
# Writable: out/ (RUN_OUT: results, evidence viewer), .work/make-run (GP_WORK: PDF/text caches, GGUF weights; kept between runs,
# delete it for a cold run) and /tmp.
GGUF ?= 0
RUN_WORK ?= $(CURDIR)/.work/make-run
RUN_OUT ?= $(CURDIR)/out
run: docker-build
	mkdir -p "$(RUN_OUT)" "$(RUN_WORK)"
	@if [ "$$(id -u)" = 0 ]; then chown -R 10001:0 "$(RUN_OUT)" "$(RUN_WORK)"; fi
	u=$$(id -u); g=$$(id -g); if [ "$$u" = 0 ]; then u=10001; g=0; fi; \
	docker run --rm --user "$$u:$$g" \
	  --read-only --tmpfs /tmp:rw,nosuid,nodev,size=2g \
	  --cap-drop ALL --security-opt no-new-privileges \
	  -e LLM_NAME -e LLM_BASE_URL -e LLM_API_KEY -e GP_GGUF=$(GGUF) -e GP_LIVE -e GP_WORK=/var/gegenprobe/work \
	  -v "$(RUN_WORK):/var/gegenprobe/work" -v "$(RUN_OUT):/app/out" $(IMAGE)

docker-build:
	docker build --build-arg GGUF=$(GGUF) -t $(IMAGE) .

# ---------------------------------------------------------------- development
# dev-install: editable install of this checkout into .venv (no dependency changes: --no-deps). It puts
# gegenprobe-robots9309.pth into the venv's site-packages, so every interpreter of the venv boots the RFC 9309 matcher and
# the fail-closed fetch guard even without PYTHONPATH (docs/runbook.md "Fail-closed"). Uses pip, or uv for a uv-made venv.
dev-install:
	$(PY) -m pip --version >/dev/null 2>&1 && $(PY) -m pip install --no-deps -e . || uv pip install --python $(PY) --no-deps -e .

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check src eval tests

# claims: every number recomputed and bound (claims.tsv, claims_anchor.json, claims_strict.json), then 444_Report.pdf
#         checked against technical_report.md (every report anchor phrase in the PDF's text; needs pdftotext)
claims:
	$(PY) -m gegenprobe.claims check
	$(PY) -m report.pdf_check

# numbers: the summary-number files regenerated in memory from committed inputs and compared byte for byte (make run: step numbers)
numbers:
	$(PY) -m report.numbers_step

# schema-v02: schema/gegenprobe_schema_v0_2.py (P8's roles) -> results/schema/v0_2/: JSON Schema, the 66 P8 gold affairs as
#             v0.2 records and p8_validation.json (all valid; v0.1 samples upgraded losslessly); then the converter's own
#             P3, P3b and P5 records carried to v0.2 ({p3,p3b,p5}_records.jsonl, samples/) and validation_all.json over
#             all four sets; then each record's document parts (tables, annexes, images, scanned pages, signatures) from
#             the committed detections (gegenprobe.schema.v0_2_parts; `make parts-detect` re-detects them from the cached
#             PDFs) and the `document_parts` counts in validation_all.json; then the P3/P3b records' Q/A items from the
#             committed pairing (results/schema/v0_2/qa_pairs.jsonl; `make qa-detect` re-pairs from the cached texts) and
#             the `qa_pairing` counts. No network, no model.
schema-v02:
	$(PY) -m gegenprobe.schema.p8_v0_2
	$(PY) -m gegenprobe.schema.v0_2_all
	$(PY) -m gegenprobe.schema.v0_2_parts

parts-detect:
	$(PY) -m gegenprobe.schema.v0_2_parts detect

# qa-detect: the P5 pairing rules (gegenprobe.qa.extract, no model) over the P3 and P3b documents' cached texts ->
#            results/schema/v0_2/qa_pairs.jsonl, which schema-v02 puts into the records' qa[0].items (gegenprobe.schema.v0_2_qa)
qa-detect:
	$(PY) -m gegenprobe.schema.v0_2_qa detect

# ---- census (owner: census workstream)
# census:        re-extract data/census from the full exports in GP_OPD_RAW / GP_DOCS_META (if present) and recompute results/census
# census-scan:   re-stream the 97 docs_* + 19 texts_* exports (~6 GB, ~25 min) into GP_DOCS_META/partX (only after a new snapshot)
# census-replay: recompute from the committed data/census only and assert equality with results/census (make run step 2)
census:
	$(PY) -m gegenprobe.census

census-scan:
	$(PY) -m gegenprobe.census.scan $${GP_DOCS_META:-.work/docs_meta}/partX

census-replay:
	$(PY) -m gegenprobe.census.replay

# census-corrected: the derived layer over the registered census (results/census/corrected.json): where each of the 16,749
#                   registered gap rows is once the repair routes looked (census/corrected.py); no network, no model
census-corrected:
	$(PY) -m gegenprobe.census.corrected

census-hash:  # network: two small docs exports; tests OPD's hash identifier rule
	$(PY) -m gegenprobe.census.hash_check

# ---- repair (owner: repair workstream)
# Model-free. Needs the census tables (data/census), the cached exports (GP_OPD_RAW, GP_DOCS_META) and the canton OGD tables
# (WORK/be_ogd; `$(PY) -m gegenprobe.repair.be fetch-ogd`). Network steps: sample (40 PDFs), che backlog, che curia, vs scan.
repair:
	$(PY) -m gegenprobe.repair.be list          # 2,459 relink + 49 fetch; exits 1 unless identical to the outreach fixture
	$(PY) -m gegenprobe.repair.be placement
	$(PY) -m gegenprobe.repair.be verify40      # 40 cached source PDFs (spikes/recovery)
	$(PY) -m gegenprobe.repair.be recheck       # post-hoc parser v2 on the pre-registered sample (cached texts)
	$(PY) -m gegenprobe.repair.che reproduce
	$(PY) -m gegenprobe.repair.agenda
	$(PY) -m gegenprobe.repair.vs list
	$(PY) -m gegenprobe.repair.ocr probe 3
	$(PY) -m gegenprobe.repair.che list
	$(PY) -m gegenprobe.repair.verify_all summary   # per-row checks of every BE relink/fetch row (fetched by repair-network)
	$(PY) -m gegenprobe.repair.run
	$(PY) -m gegenprobe.repair.reconcile_be
	-$(PY) -m gegenprobe.repair.acceptance         # relink documents OPD has attached (6 Oct snapshot: 0; exits 1 until the fix ships)
	$(PY) -m gegenprobe.repair.demo
	$(PY) -m gegenprobe.repair.be_begin_date  # BE begin_date correction list (OPD-confirmed load timestamps)
	$(PY) -m gegenprobe.repair.manifest       # results/repair/MANIFEST.json: every list, which wins on overlap

# ---- source adapters (owner: repair workstream; docs/adapters.md, docs/runbook.md "Adapters: operating plan")
# adapters-write:  rebuild results/repair/adapters/ from the WORK checkpoints (no network), then the manifest
# adapters-canary: network (RFC 9309 robots, polite): re-check one known affair per external source; exit 3 on alerts
adapters-write:
	$(PY) -m gegenprobe.repair.adapters.run --write
	$(PY) -m gegenprobe.repair.manifest

adapters-canary:
	$(PY) -m gegenprobe.repair.adapters.canary run

repair-manifest:
	$(PY) -m gegenprobe.repair.manifest

repair-network:   # one-off measurements that fetch documents (polite: >= 1.2 s per host); results are committed
	$(PY) -m gegenprobe.repair.be sample        # pre-registered: data/repair/prereg_be_relink_sample.md
	$(PY) -m gegenprobe.repair.verify_all run   # every BE relink/fetch row: fetch + triple check (~50 min, resumable)
	$(PY) -m gegenprobe.repair.che backlog 50
	$(PY) -m gegenprobe.repair.che curia
	$(PY) -m gegenprobe.repair.vs scan

nightly-offline:
	$(PY) -m gegenprobe.monitor.nightly offline; rc=$$?; [ $$rc -eq 0 ] || [ $$rc -eq 3 ]   # 3 = alerts fired

nightly-smoke:   # three offline nights on synthetic fixture exports (seconds; CI runs it inside the read-only image too)
	$(PY) -m gegenprobe.monitor.smoke

nightly-notify-test:   # sends one test message through the channels configured in the environment (GP_ALERT_*)
	$(PY) -m gegenprobe.monitor.notify test

# ---- nightly (owner: repair workstream)
install-nightly:
	sh deploy/nightly/install.sh

# ---- operations (docs/runbook.md)
# cache-clean: delete the cached PDFs and texts under GP_WORK (pdf/, text/) older than GP_CACHE_MAX_AGE_DAYS (default 30;
#              0 = never expire); every network night of the nightly job does the same. DRY=1 lists without deleting.
# ocr-models:  a host without Docker: the pinned tessdata_fast models (deu, fra, ita, eng) into TESSDATA_DIR, each sha256
#              checked against ocrguard.TESSDATA_SHA256, tesseract checked with them; prints `export TESSDATA_PREFIX=...`
.PHONY: cache-clean ocr-models
TESSDATA_DIR ?= $(or $(GP_WORK),$(CURDIR)/.work)/tessdata-pinned
cache-clean:
	$(PY) -m gegenprobe.cache_retention $(if $(DRY),--dry-run)

ocr-models:
	$(PY) -m gegenprobe.ocr_models "$(TESSDATA_DIR)"

# ---- convert (owner: convert workstream)
#   convert           model-free: spike replay through calibrate.py, rules on the dev pool, convert tests
#   gold-dev / gold-heldout   draw + fetch the gold documents (polite; seeds in eval/gold/SEEDS.md)
#   gold-candidates   lattice candidates + label sheet for annotators (no rule predictions shown)
#   theta BACKEND=…   fit θ on dev labels (model run: openai | gguf | gateway:<model>:<tag>:<cap>, the last development only)
#   arms  BACKEND=…   rules / pointer / cascade / naive on SPLIT (default heldout)
#   gold-dev-fetch    fetch the committed dev documents by URL, sha256-verified (no re-draw; what a θ refit needs)
# The locked modules (eval/arms.py, eval/gold/sample.py) name the developer's spike and gateway folders literally; they
# run through eval/devrun.py, which takes those folders from GP_SPIKES_DIR / GP_GATEWAY_DIR (GP_SPIKES_DIR=none: θ on
# the 97 committed dev documents only). See docs/runbook.md "Development-only paths".
SPLIT ?= heldout
BACKEND ?= none
convert:
	$(PY) -m eval.replay_spikes
	$(PY) -m eval.dev_rules
	$(PY) -m pytest -q tests/test_convert.py

gold-dev:
	$(PY) -m eval.devrun eval.gold.sample --split dev --fetch

gold-dev-fetch:
	$(PY) -m eval.run_arms fetch --split dev

gold-heldout:
	$(PY) -m eval.devrun eval.gold.sample --split heldout --fetch

gold-candidates:
	$(PY) -m eval.gold.candidates --split $(SPLIT)

theta:
	$(PY) -m eval.devrun eval.arms fit --backend $(BACKEND)

arms:
	$(PY) -m eval.devrun eval.arms run --split $(SPLIT) --backend $(BACKEND)

# ---- eval / report (owner: integrator)
eval:  # no model: re-score every committed evaluation file, recompute H1-H4, matrix accuracy and cost
	$(PY) -m eval.replay
	$(PY) -m eval.hypotheses publicai_swiss-ai_apertus-v1.5-8b
	$(PY) -m eval.breadth  # post hoc: P1/P2 by language x level x born-digital/scanned -> results/eval/breadth_p1_p2.json
	$(PY) -m report.matrix_accuracy

report:  # technical_report.md -> 444_Report.pdf (needs the [report] extra and Chrome/Chromium; CHROME=... to override), then the PDF check
	$(PY) -m report.render
	$(PY) -m report.pdf_check

# ---- figures (dev only; needs the [report] extra: matplotlib)
figures:
	$(PY) -m report.figures

# ---- evidence viewer (static site; committed copy in site/ holds excerpts only, never full texts); `build` also writes
#      site/_headers (CSP with the inline blocks' sha256, HSTS, nosniff, referrer policy), which deploy-site ships
site:
	$(PY) -m gegenprobe.viewer collect
	$(PY) -m gegenprobe.viewer build

# ---- evidence viewer on Cloudflare (static assets; token read from CLOUDFLARE_API_TOKEN, never stored in the repo)
deploy-site: site
	cd deploy/site && npx --yes wrangler@4.149.0 deploy
