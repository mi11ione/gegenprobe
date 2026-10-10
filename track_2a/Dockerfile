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
    && rm -rf /var/lib/apt/lists/* \
    && dpkg-query -W poppler-utils tesseract-ocr tesseract-ocr-deu tesseract-ocr-fra tesseract-ocr-ita \
       > /usr/local/share/gegenprobe-apt-versions.txt
# Debian packages are not version-pinned by apt (the digest-pinned base fixes the release, the Debian mirror the build
# date); the file above records what this build got. OCR language data differs from the measured setup: see docs/runbook.md.

WORKDIR /app
# Python dependencies are hash-pinned (requirements.lock: sha256 of every PyPI file of each pinned version).
COPY requirements.lock requirements-gguf.lock ./
RUN pip install --require-hashes -r requirements.lock \
    && if [ "$GGUF" = "1" ]; then pip install --require-hashes --no-deps -r requirements-gguf.lock; fi

COPY . .
# Never runs as root: the default user is the unprivileged `gp` (uid 10001). `make run` passes the caller's uid (--user) so
# results in ./out stay owned by the judge, and 10001 when the caller is root (uid 0 is never passed); it also runs the
# container with --read-only, a tmpfs /tmp, --cap-drop ALL and no-new-privileges. The nightly unit runs it as 10001 on
# /var/lib/gegenprobe with the same flags.
RUN useradd --system --uid 10001 --gid 0 --home-dir /tmp --no-create-home --shell /usr/sbin/nologin gp \
    && mkdir -p /app/out && chown 10001:0 /app/out && chmod 0775 /app/out
USER 10001:0

CMD ["python", "-m", "gegenprobe.run"]
