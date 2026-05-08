# services/inference/Dockerfile
# Reproducible build using uv. Two stages: builder resolves the locked
# dependency tree into a virtualenv, runtime copies that venv plus the
# source over a clean base.

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  UV_COMPILE_BYTECODE=1 \
  UV_LINK_MODE=copy

# uv binaries from a pinned realease tag.
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /uvx /bin/

# libgomp is a runtime dep of torch; install it in the builder so the wheel
# pre-link checks succeed.
RUN apt-get update \
  && apt-get install -y --no-install-recommends libgomp1 \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the workspace lockfile and project configs
COPY pyproject.toml uv.lock ./
COPY services/inference/pyproject.toml ./services/inference/

RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --frozen --no-install-project --no-dev --extra ml --package safestream-inference

COPY services/inference/src/ ./services/inference/src/
COPY services/inference/alembic/ ./services/inference/alembic/
COPY services/inference/alembic.ini ./services/inference/

# Work from the service directory for runtime
WORKDIR /app/services/inference
RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --frozen --no-dev --extra ml --package safestream-inference


# ---- Final stage ---------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  PATH="/app/.venv/bin:$PATH" \
  PYTHONPATH="/app/services/inference/src" \
  HF_HOME=/app/.hf-cache

# curl: docker healthcheck. libgomp1: torch runtime dep.
RUN apt-get update \
  && apt-get install -y --no-install-recommends curl libgomp1 \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app /app

# Point to the specific service within the workspace
WORKDIR /app/services/inference

RUN useradd --create-home --uid 1001 inference \
  && mkdir -p /app/.hf-cache \
  && chown -R inference:inference /app
USER inference

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
