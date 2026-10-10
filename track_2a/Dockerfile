# Gegenprobe: judges' runtime. CPU only, no GPU, no host dependencies.
# Build:  docker build -t gegenprobe .            (default: replay + live slice over LLM_BASE_URL if set)
#         docker build --build-arg GGUF=1 ...      (adds llama-cpp-python for the optional local 8B GGUF slice)
# Base image pinned by digest (python:3.11.14-slim-bookworm, multi-arch index, resolved 2026-10-10).
FROM python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d

ARG GGUF=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src:/app GP_WORK=/tmp/gp-work HOME=/tmp

# poppler (pdftotext/pdftoppm) for page-exact text; tesseract with German, French and Italian models for image-only scans
RUN apt-get update && apt-get install -y --no-install-recommends \
      poppler-utils tesseract-ocr tesseract-ocr-deu tesseract-ocr-fra tesseract-ocr-ita ca-certificates make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Python dependencies are hash-pinned (requirements.lock: sha256 of every PyPI file of each pinned version).
COPY requirements.lock requirements-gguf.lock ./
RUN pip install --require-hashes -r requirements.lock \
    && if [ "$GGUF" = "1" ]; then pip install --require-hashes --no-deps -r requirements-gguf.lock; fi

COPY . .
# runs as the caller's uid (make run passes --user), so results in ./out stay owned by the judge

CMD ["python", "-m", "gegenprobe.run"]
