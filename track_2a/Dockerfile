# Gegenprobe: judges' runtime. CPU only, no GPU, no host dependencies.
# Build:  docker build -t gegenprobe .            (default: replay + live slice over LLM_BASE_URL if set)
#         docker build --build-arg GGUF=1 ...      (adds llama-cpp-python for the optional local 8B GGUF slice)
FROM python:3.11.14-slim-bookworm

ARG GGUF=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src:/app GP_WORK=/tmp/gp-work HOME=/tmp

# poppler (pdftotext/pdftoppm) for page-exact text; tesseract with German, French and Italian models for image-only scans
RUN apt-get update && apt-get install -y --no-install-recommends \
      poppler-utils tesseract-ocr tesseract-ocr-deu tesseract-ocr-fra tesseract-ocr-ita ca-certificates make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && if [ "$GGUF" = "1" ]; then pip install --only-binary=:all: \
         --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu llama-cpp-python==0.3.35; fi

COPY . .
# runs as the caller's uid (make run passes --user), so results in ./out stay owned by the judge

CMD ["python", "-m", "gegenprobe.run"]
