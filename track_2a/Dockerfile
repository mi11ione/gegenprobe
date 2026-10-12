# Gegenprobe: judges' runtime. CPU only, no GPU, no host dependencies.
# Build:  docker build -t gegenprobe .            (default: replay + live slice over LLM_BASE_URL if set)
#         docker build --build-arg GGUF=1 ...      (adds llama-cpp-python for the optional local 8B GGUF slice)
# Base image pinned by digest (python:3.11.14-slim-bookworm, multi-arch index, resolved 2026-10-10).
FROM python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d

ARG GGUF=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src:/app GP_WORK=/tmp/gp-work HOME=/tmp

# poppler (pdftotext/pdftoppm) for page-exact text; tesseract for image-only scans (its language models: next step)
RUN apt-get update && apt-get install -y --no-install-recommends \
      poppler-utils tesseract-ocr ca-certificates make \
    && rm -rf /var/lib/apt/lists/* \
    && dpkg-query -W poppler-utils tesseract-ocr > /usr/local/share/gegenprobe-apt-versions.txt
# Debian packages are not version-pinned by apt (the digest-pinned base fixes the release, the Debian mirror the build
# date); the file above records what this build got.
# OCR language models: exactly the ones the OCR numbers were measured with (docs/runbook.md, OCR): tessdata_fast at commit
# 87416418657359cb625c412a48b6e1d6d41c29bd (deu, fra, ita, eng), downloaded by gegenprobe/ocrguard.py (stdlib only; the
# commit and the sha256 of each file are its TESSDATA_COMMIT / TESSDATA_SHA256) and checked file by file: a mismatch
# fails the build. tesseract reads only this directory (TESSDATA_PREFIX), and GP_OCR_REQUIRE_PINNED=1 makes every OCR
# call refuse with a typed ocr_failed if the files ever differ from the pins.
ENV TESSDATA_PREFIX=/usr/local/share/tessdata-pinned GP_OCR_REQUIRE_PINNED=1
COPY src/gegenprobe/ocrguard.py /usr/local/share/gegenprobe-ocrguard.py
RUN python /usr/local/share/gegenprobe-ocrguard.py install-pinned "$TESSDATA_PREFIX" \
    && python /usr/local/share/gegenprobe-ocrguard.py \
    && rm /usr/local/share/gegenprobe-ocrguard.py \
    && sha256sum "$TESSDATA_PREFIX"/*.traineddata >> /usr/local/share/gegenprobe-apt-versions.txt

WORKDIR /app
# Python dependencies are hash-pinned (requirements.lock: sha256 of every PyPI file of each pinned version; runtime only,
# the test tools are in requirements-dev.lock, which the image does not install). The installers the base image ships
# (pip 24.0, setuptools 79.0.1, wheel 0.45.1: known vulnerabilities, docs/licences.md) are removed once the install is
# done; nothing in the image runs them.
COPY requirements.lock requirements-gguf.lock ./
RUN pip install --require-hashes -r requirements.lock \
    && if [ "$GGUF" = "1" ]; then pip install --require-hashes --no-deps -r requirements-gguf.lock; fi \
    && pip uninstall -y -q pip setuptools wheel

COPY . .
# Never runs as root: the default user is the unprivileged `gp` (uid 10001). `make run` passes the caller's uid (--user) so
# results in ./out stay owned by the judge, and 10001 when the caller is root (uid 0 is never passed); it also runs the
# container with --read-only, a tmpfs /tmp, --cap-drop ALL and no-new-privileges. The nightly unit runs it as 10001 on
# /var/lib/gegenprobe with the same flags.
RUN useradd --system --uid 10001 --gid 0 --home-dir /tmp --no-create-home --shell /usr/sbin/nologin gp \
    && mkdir -p /app/out && chown 10001:0 /app/out && chmod 0775 /app/out
USER 10001:0

CMD ["python", "-m", "gegenprobe.run"]
