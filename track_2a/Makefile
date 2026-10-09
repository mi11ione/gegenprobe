# Gegenprobe (Track 2A, OpenParlData). Judges: `make run` (Docker, CPU, clean checkout).
# Development targets run on the host with .venv (python 3.11); every target is re-runnable and writes under results/.
.PHONY: run test lint claims census repair convert eval report install-nightly docker-build

PY ?= .venv/bin/python
IMAGE ?= gegenprobe:latest
export PYTHONPATH := src:.

# ---------------------------------------------------------------- judges' entry point (Docker)
run: docker-build
	docker run --rm \
	  -e LLM_NAME -e LLM_BASE_URL -e LLM_API_KEY -e GP_GGUF -e GP_LIVE \
	  -v "$(CURDIR)/out:/app/out" $(IMAGE)

docker-build:
	docker build -t $(IMAGE) .

# ---------------------------------------------------------------- development
test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check src eval tests

claims:
	$(PY) -m gegenprobe.claims check

# ---- census (owner: census workstream)
census:
	@echo "census: TODO"

# ---- repair (owner: repair workstream)
repair:
	@echo "repair: TODO"

# ---- nightly (owner: repair workstream)
install-nightly:
	@echo "install-nightly: TODO"

# ---- convert (owner: convert workstream)
convert:
	@echo "convert: TODO"

# ---- eval / report (owner: integrator)
eval:
	@echo "eval: TODO"

report:
	@echo "report: TODO"
