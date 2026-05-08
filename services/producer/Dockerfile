# services/producer/Dockerfile
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  UV_COMPILE_BYTECODE=1 \
  UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /uvx /bin/

WORKDIR /app

# Copy the workspace lockfile and project configs
COPY pyproject.toml uv.lock ./
COPY services/producer/pyproject.toml ./services/producer/

RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --frozen --no-install-project --no-dev --package safestream-producer

COPY services/producer/src/ ./services/producer/src/

# Work from the service directory
WORKDIR /app/services/producer
RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --frozen --no-dev --package safestream-producer


# ---- Final stage ---------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  PATH="/app/.venv/bin:$PATH" \
  PYTHONPATH="/app/services/producer/src"

WORKDIR /app

COPY --from=builder /app /app

# Point to the specific service within the workspace
WORKDIR /app/services/producer

RUN useradd --create-home --uid 1001 producer
USER producer

CMD ["python", "-m", "src.producer"]
