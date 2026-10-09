# Gegenprobe (Track 2A, OpenParlData). Judges: `make run` (Docker, CPU, clean checkout).
# Development targets run on the host with .venv (python 3.11); every target is re-runnable and writes under results/.
.PHONY: run test lint claims census census-scan census-replay repair convert eval report install-nightly docker-build

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

# ---- repair (owner: repair workstream)
repair:
	@echo "repair: TODO"

# ---- nightly (owner: repair workstream)
install-nightly:
	@echo "install-nightly: TODO"

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
eval:
	@echo "eval: TODO"

report:
	@echo "report: TODO"
