# syntax=docker/dockerfile:1.7

# ---- base image with native deps for WeasyPrint + trafilatura ----
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:/usr/local/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 \
      libpangoft2-1.0-0 \
      libcairo2 \
      libgdk-pixbuf-2.0-0 \
      libffi8 \
      shared-mime-info \
      fonts-liberation \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv — fast dep resolver; pulled from the official distroless image.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# Resolve and install dependencies first so edits to src/ don't bust the
# heavy dep-install layer.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
            --extra ingest --extra classify --extra web

# Now bring in application code and config, then install the project itself.
COPY src/ ./src/
COPY config/ ./config/
COPY alembic/ ./alembic/
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev \
            --extra ingest --extra classify --extra web

# Pre-download the corroboration embedder so the first Assess click
# doesn't block on a 90 MB HF Hub download (also removes a runtime
# network dependency on huggingface.co).
ENV HF_HOME=/root/.cache/huggingface
RUN /app/.venv/bin/python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" \
    || echo "warning: embedder preload failed; runtime fallback still applies"

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
