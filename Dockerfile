# ── Stage 1: Builder ─────────────────────────────────────────────────────────
# Install Python deps in an isolated layer so the final image stays lean.
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# System-level C-libraries required by pytesseract, Pillow, and python-docx (lxml backup)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev \
    libleptonica-dev \
    libpng-dev \
    libjpeg-dev \
    libtiff-dev \
    libxml2-dev \
    libxslt-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata \
    DELTA_CONTEXT_DB=/data/delta_context.sqlite

# Only runtime libraries — no build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libpng16-16 \
    libjpeg62-turbo \
    libtiff6 \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Application source (This automatically pulls in the new Phase 7A parsers)
COPY src/ ./src/

# Persistent data volume — SQLite DB lives here
VOLUME ["/data"]

# Health-check: verify the DB module imports cleanly
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "from src.engine.db import DB; print('ok')" || exit 1

# Entrypoint: run the MCP server
CMD ["python", "-m", "src.mcp_server.server"]