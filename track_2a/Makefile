# Gegenprobe (Track 2A, OpenParlData). Judges: `make run` (Docker, CPU, clean checkout).
# Development targets run on the host with .venv (python 3.11); every target is re-runnable and writes under results/.
.PHONY: figures run test lint claims census census-scan census-replay census-hash repair repair-network nightly-offline convert eval report install-nightly docker-build

PY ?= .venv/bin/python
IMAGE ?= gegenprobe:latest
export PYTHONPATH := src:.

# ---------------------------------------------------------------- judges' entry point (Docker)
GGUF ?= 0
run: docker-build
	mkdir -p out
	docker run --rm --user "$$(id -u):$$(id -g)" \
	  -e LLM_NAME -e LLM_BASE_URL -e LLM_API_KEY -e GP_GGUF=$(GGUF) -e GP_LIVE \
	  -v "$(CURDIR)/out:/app/out" $(IMAGE)

docker-build:
	docker build --build-arg GGUF=$(GGUF) -t $(IMAGE) .

# ---------------------------------------------------------------- development
test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check src eval tests

claims:
	$(PY) -m gegenprobe.claims check

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
	$(PY) -m gegenprobe.repair.run
	$(PY) -m gegenprobe.repair.demo
	$(PY) -m gegenprobe.repair.be_begin_date  # BE begin_date correction list (OPD-confirmed load timestamps)

repair-network:   # one-off measurements that fetch documents (polite: >= 1.2 s per host); results are committed
	$(PY) -m gegenprobe.repair.be sample        # pre-registered: data/repair/prereg_be_relink_sample.md
	$(PY) -m gegenprobe.repair.che backlog 50
	$(PY) -m gegenprobe.repair.che curia
	$(PY) -m gegenprobe.repair.vs scan

nightly-offline:
	$(PY) -m gegenprobe.monitor.nightly offline

# ---- nightly (owner: repair workstream)
install-nightly:
	sh deploy/nightly/install.sh

# ---- convert (owner: convert workstream)
#   convert           model-free: spike replay through calibrate.py, rules on the dev pool, convert tests
#   gold-dev / gold-heldout   draw + fetch the gold documents (polite; seeds in eval/gold/SEEDS.md)
#   gold-candidates   lattice candidates + label sheet for annotators (no rule predictions shown)
#   theta BACKEND=…   fit θ on dev labels (model run: gateway:<model>:<tag>:<cap> | openai | gguf)
#   arms  BACKEND=…   rules / pointer / cascade / naive on SPLIT (default heldout)
SPLIT ?= heldout
BACKEND ?= none
convert:
	$(PY) -m eval.replay_spikes
	$(PY) -m eval.dev_rules
	$(PY) -m pytest -q tests/test_convert.py

gold-dev:
	$(PY) -m eval.gold.sample --split dev --fetch

gold-heldout:
	$(PY) -m eval.gold.sample --split heldout --fetch

gold-candidates:
	$(PY) -m eval.gold.candidates --split $(SPLIT)

theta:
	$(PY) -m eval.arms fit --backend $(BACKEND)

arms:
	$(PY) -m eval.arms run --split $(SPLIT) --backend $(BACKEND)

# ---- eval / report (owner: integrator)
eval:  # no model: re-score every committed evaluation file, recompute H1-H4, matrix accuracy and cost
	$(PY) -m eval.replay
	$(PY) -m eval.hypotheses publicai_swiss-ai_apertus-v1.5-8b
	$(PY) -m report.matrix_accuracy

report:  # technical_report.md -> 444_Report.pdf (needs the [report] extra and Chrome/Chromium; CHROME=... to override)
	$(PY) -m report.render

# ---- figures (dev only; needs the [report] extra: matplotlib)
figures:
	$(PY) -m report.figures

# ---- evidence viewer (static site; committed copy in site/ holds excerpts only, never full texts)
site:
	$(PY) -m gegenprobe.viewer collect
	$(PY) -m gegenprobe.viewer build
