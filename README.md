# SafeStream AI

Real-time content moderation engine. Deep-learning models triage user-generated
content (text + images) coming off a streaming bus, persist verdicts to a
relational store, and expose embeddings through a vector store for semantic
similarity search.

This repository is structured as a Docker-Compose monorepo and built out in
phases per the architecture proposal.

## Status

| Phase     | Scope                                                             | State    |
| --------- | ----------------------------------------------------------------- | -------- |
| 1         | Infrastructure (Kafka + Postgres + Qdrant) and ingestion producer | **Done** |
| 2         | Inference engine: NLP + CV models behind FastAPI                  | **Done** |
| 3         | Semantic similarity service on Qdrant                             | **Done** |
| 4         | React/Vite/Tailwind audit dashboard with WebSocket feed           | **Done** |
| Hardening | Tests, reproducible builds, migrations, observability, DLQ, OTel  | **Done** |

## Layout

```
.
├── docker-compose.yml
├── .env.example
├── infrastructure/
│   └── postgres/init.sql       # events / predictions / audits schema
└── services/
    ├── producer/               # Streams Jigsaw-shaped events into Kafka
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   ├── data/
    │   │   ├── README.md
    │   │   └── sample_comments.csv
    │   └── src/
    │       ├── config.py       # pydantic-settings
    │       ├── dataset.py      # CSV → ContentEvent
    │       ├── producer.py     # async aiokafka loop
    │       └── schema.py       # JSON contract
    └── inference/              # FastAPI + NLP/CV models + Kafka worker
        ├── Dockerfile
        ├── requirements.txt
        └── src/
            ├── main.py         # app factory + lifespan
            ├── config.py
            ├── logging.py
            ├── api/            # REST routes, schemas, auth, rate limit
            ├── domain/         # ContentEvent, verdict logic
            ├── models/         # text + vision classifiers, registry
            ├── persistence/    # asyncpg pool + repository
            └── workers/        # Kafka consumer task
```

## Phase 1 - bring the stack up

Requires Docker Engine 24+ with Compose v2.

```bash
cp .env.example .env

# Builds the producer image and starts every service.
docker compose up -d --build

# Watch the producer push events.
docker compose logs -f producer
```

The first time the stack starts you will see:

1. `kafka` reach the healthy state (KRaft single-node).
2. `kafka-init` create the four topics (`content.text.raw`, `content.image.raw`,
   `predictions.results`, `audits.events`) and exit `0`.
3. `postgres` apply `infrastructure/postgres/init.sql`.
4. `qdrant` open ports `6333` (HTTP/dashboard) and `6334` (gRPC).
5. `producer` start emitting one event roughly every `1 / EVENTS_PER_SECOND`
   seconds.

### Smoke test

Confirm the topic exists and is receiving messages:

```bash
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka:9092 --describe --topic content.text.raw

docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 --topic content.text.raw \
  --from-beginning --max-messages 5
```

Confirm Postgres is reachable and the schema landed:

```bash
docker compose exec postgres psql -U safestream -d safestream -c "\dt"
```

Confirm Qdrant responds:

```bash
curl -s http://localhost:6333/readyz
```

### Useful knobs

All overridable via `.env` or one-off `VAR=... docker compose up`:

| Variable            | Purpose                                                  | Default                         |
| ------------------- | -------------------------------------------------------- | ------------------------------- |
| `EVENTS_PER_SECOND` | Producer pacing                                          | `10`                            |
| `DATASET_PATH`      | CSV consumed by the producer (path inside the container) | `/app/data/sample_comments.csv` |
| `LOOP_DATASET`      | Restart the file when EOF is reached                     | `true`                          |
| `LOG_LEVEL`         | Producer log verbosity                                   | `INFO`                          |

## Tearing it down

```bash
docker compose down              # keep volumes
docker compose down -v           # also wipe Kafka / Postgres / Qdrant data
```

## Tests and CI

The repo runs three test suites in parallel on every push/PR via
`.github/workflows/ci.yml`. To run them locally:

### Inference (Python)

```bash
cd services/inference
pip install -r requirements-dev.txt
pytest                           # 47 unit tests
ruff check ../..                 # lint from the repo root, picks up pyproject.toml
```

The unit tests stub `transformers`, `sentence_transformers`, the asyncpg pool
and the Qdrant client, so no live infrastructure is needed. Tests cover:

- Domain logic (verdict thresholds parametrised, event JSON round-trip).
- API-key auth (empty allow-list bypass, missing/invalid/valid keys).
- ConnectionManager (fan-out, prune dead/slow clients, concurrent broadcasts).
- Every HTTP route: `/healthz`, `/readyz` (degraded when DB is down),
  `/v1/events/recent` (verdict filter forwarding, JSON-string score parsing),
  `/v1/events/{id}` (200, 404, invalid UUID), `/v1/audits` (201, 422 invalid
  decision, 404 on FK violation), `/v1/metrics/confusion` (P/R derivations,
  divide-by-zero null handling), `/v1/metrics/timeseries` (param validation),
  `/v1/search/semantic` (503 when embedder/store unavailable, filter
  forwarding).
- Worker indexing logic (block/review indexed, safe/image skipped, snippet
  truncation, vector-store errors swallowed).

### Producer (Python)

```bash
cd services/producer
pip install -r requirements-dev.txt
pytest                           # 8 unit tests
```

### Dashboard (Node)

```bash
cd services/dashboard
npm ci
npm run type-check               # strict tsc
npm test                         # 24 vitest tests
npm run build                    # production build (smoke test)
```

## Phase 2 - inference engine

The `inference` service hosts the FastAPI app and the Kafka consumer that
together implement the moderation pipeline.

```bash
docker compose up -d --build inference
docker compose logs -f inference
```

First boot downloads the HF weights (~440 MB for the default text model); they
persist in the `hf_cache` named volume so subsequent restarts are instant. Once
the service is `healthy`, OpenAPI docs live at <http://localhost:8000/docs>.

### What the service does on every event

For each message arriving on `content.text.raw` (and `content.image.raw` when
vision is enabled), the worker:

1. Validates the envelope against `ContentEvent`.
2. Runs the relevant classifier (text or image).
3. Maps the raw scores to a verdict (`safe` / `review` / `block`) using the
   `THRESHOLD_REVIEW` and `THRESHOLD_BLOCK` knobs.
4. Persists the event + prediction in Postgres inside one transaction.
5. Publishes a compact result to `predictions.results` for downstream consumers
   (the WebSocket gateway in Phase 4 subscribes here).

### Synchronous REST endpoints

These exist for ad-hoc testing and integrators that need an immediate verdict
without round-tripping through Kafka.

```bash
# Auth disabled by default; set API_KEYS in .env to enable.
curl -s -X POST http://localhost:8000/v1/classify/text \
  -H "Content-Type: application/json" \
  -d '{"content": "you are an absolute disgrace"}' | jq

# Image classification (only available when ENABLE_VISION=true).
curl -s -X POST http://localhost:8000/v1/classify/image \
  -F "file=@/path/to/image.jpg" | jq
```

Sample response shape:

```json
{
  "event_id": "8f2c0b8c-…",
  "modality": "text",
  "verdict": "block",
  "scores": {"toxic": 0.97, "insult": 0.84, "obscene": 0.41, …},
  "model": {"name": "unitary/toxic-bert", "version": "default"},
  "inference_latency_ms": 92,
  "predicted_at": "2026-04-26T11:23:04.512000+00:00"
}
```

### Smoke test the worker path

After the producer has been running for a while, the worker should have consumed
those events and inserted matching rows:

```bash
# Count predictions and group by verdict.
docker compose exec postgres psql -U safestream -d safestream -c "
  SELECT verdict, COUNT(*) FROM predictions GROUP BY verdict ORDER BY 2 DESC;
"

# Tail the predictions topic to see the worker's output.
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 --topic predictions.results \
  --max-messages 5
```

### Enabling the vision model

```bash
ENABLE_VISION=true docker compose up -d inference
# First start downloads ~340 MB of weights.
```

### Enabling auth + rate limiting in production-like mode

```bash
API_KEYS="dev-key-123,team-key-456" \
RATE_LIMIT="60/minute" \
docker compose up -d inference

curl -s -X POST http://localhost:8000/v1/classify/text \
  -H "X-API-Key: dev-key-123" \
  -H "Content-Type: application/json" \
  -d '{"content": "hello"}'
```

### Knobs (Phase 2)

| Variable                               | Purpose                                       | Default                          |
| -------------------------------------- | --------------------------------------------- | -------------------------------- |
| `ENABLE_TEXT`                          | Load the text model                           | `true`                           |
| `ENABLE_VISION`                        | Load the image model                          | `false`                          |
| `NLP_MODEL_NAME`                       | Any HF `text-classification` model            | `unitary/toxic-bert`             |
| `CV_MODEL_NAME`                        | Any HF `image-classification` model           | `Falconsai/nsfw_image_detection` |
| `THRESHOLD_REVIEW` / `THRESHOLD_BLOCK` | Verdict thresholds on `max(scores)`           | `0.4` / `0.8`                    |
| `WORKER_ENABLED`                       | Run the Kafka consumer alongside the API      | `true`                           |
| `WORKER_CONCURRENCY`                   | Max concurrent inference tasks per replica    | `4`                              |
| `API_KEYS`                             | Comma-separated allow-list (empty = auth off) | _(empty)_                        |
| `RATE_LIMIT`                           | Per-key/per-IP budget                         | `100/minute`                     |

## Phase 3 - semantic similarity

Adds a sentence embedder and the Qdrant write/read paths that power the audit
UI's Omnibox (Phase 4 / View 2). Pipeline becomes:

```
Kafka -> classify -> persist (Postgres) -> publish (Kafka) -> commit
                                                             \
                                                              -> embed -> upsert (Qdrant)
```

The embed/index step is best-effort: it runs after the Kafka offset is
committed, so a Qdrant outage cannot stall moderation. Only verdicts in
`INDEX_VERDICTS` (default `review,block`) are indexed - `safe` events are
skipped to keep the collection focused on sanctioned content.

### Searching

```bash
curl -s -X POST http://localhost:8000/v1/search/semantic \
  -H "Content-Type: application/json" \
  -d '{
        "query": "I will hurt you",
        "limit": 5,
        "verdicts": ["block", "review"],
        "min_score": 0.5
      }' | jq
```

The endpoint embeds the query, runs a cosine search against Qdrant, and returns
hits with score, snippet, verdict and a few payload fields. The intent is to
expose evasion attempts that lexical search misses (typos, character
substitutions, paraphrases of previously-blocked content).

### Inspecting Qdrant directly

```bash
# Web dashboard
open http://localhost:6333/dashboard

# Point count
curl -s http://localhost:6333/collections/safestream_sanctioned | jq

# Confirm the collection has the right vector size and distance.
curl -s http://localhost:6333/collections/safestream_sanctioned | \
  jq '.result.config.params.vectors'
```

### Switching the embedding model

If you change `EMBEDDING_MODEL_NAME` to a model with a different vector
dimension, also update `EMBEDDING_DIM`. The embedder fails fast at startup if
the configured dimension does not match the model output. If a Qdrant collection
already exists with the old dimension, drop it first:

```bash
curl -X DELETE http://localhost:6333/collections/safestream_sanctioned
```

The service will recreate it on the next start.

### Knobs (Phase 3)

| Variable               | Purpose                                 | Default                                  |
| ---------------------- | --------------------------------------- | ---------------------------------------- |
| `ENABLE_EMBEDDINGS`    | Load the sentence embedder              | `true`                                   |
| `EMBEDDING_MODEL_NAME` | Any sentence-transformers model         | `sentence-transformers/all-MiniLM-L6-v2` |
| `EMBEDDING_DIM`        | Vector dimension (must match the model) | `384`                                    |
| `QDRANT_URL`           | Qdrant base URL                         | `http://qdrant:6333`                     |
| `QDRANT_COLLECTION`    | Collection name (cosine distance)       | `safestream_sanctioned`                  |
| `INDEX_VERDICTS`       | Verdicts that trigger upsert            | `review,block`                           |

## Phase 4 - audit console

The `dashboard` service is a React/Vite/Tailwind SPA served by nginx, which also
reverse-proxies `/api` and `/ws` to the inference service so the browser sees a
single origin.

### What's added in Phase 4

**Inference service:**

- `WebSocket /v1/stream` — live feed of every prediction.
- `GET /v1/events/recent` — initial paint of the triage grid.
- `GET /v1/events/{id}` — single-event detail.
- `POST /v1/audits` — record a human review decision.
- `GET /v1/metrics/timeseries` — bucketed verdict counts.
- `GET /v1/metrics/confusion` — TP/FP/TN/FN against `audits`, with
  precision/recall derived (null when there are no audits yet).
- `PredictionBroadcaster`: a separate Kafka consumer group
  (`safestream-broadcaster`) that fans out from `predictions.results` to every
  WebSocket client.
- `ConnectionManager` with per-client send timeout and dead-client pruning.

**Dashboard (`services/dashboard/`):**

- Three views routed at `/`, `/search`, `/mlops`.
- Single WebSocket subscription at the layout level fans out to listeners via
  `LiveStreamContext`, so we don't open one socket per view.
- Auto-reconnect with exponential backoff (capped at 30 s).
- View 1 — Triage queue: live grid limited to `review`/`block`, colour-coded
  verdict badges, detail panel with per-label score bars, keyboard shortcuts
  (`j`/`k` to navigate, `a`/`r`/`e` to audit, `Esc` to deselect, `/` to focus
  the omnibox in View 2).
- View 2 — Omnibox: cosine search with verdict filter chips and a min-score
  slider.
- View 3 — Observability: timeseries chart (Recharts) + live confusion matrix
  with derived precision/recall.

### Bring it up

```bash
docker compose up -d --build
docker compose logs -f dashboard
```

Open <http://localhost:8080> once `inference` reports healthy. Until the text
model finishes loading the first time (~440 MB), `/readyz` will report
`degraded` and the dashboard will show "loading recent events…".

### Dev mode

For tighter iteration on the UI, run Vite directly:

```bash
cd services/dashboard
npm install
npm run dev
```

Vite serves at <http://localhost:5173> and proxies `/api` and `/ws` to the
inference service running in Docker on `localhost:8000`. CORS is already
allow-listed for `http://localhost:5173` by default.

### Visual language

The console is styled as a dark **control room / Bloomberg-terminal**:

- Background: dotted-grid CSS pattern over `#07070a`.
- Display: Archivo Black; body: IBM Plex Sans; numerics + IDs: JetBrains Mono.
- One accent (orange `#fb923c`) for selection / focus / call-to-action.
- Verdict colours used as the only chromatic budget: green safe, amber review,
  rose block, lavender escalate.
- All borders 1 px, no rounding.

### Knobs (Phase 4)

| Variable                     | Purpose                             | Default                                       |
| ---------------------------- | ----------------------------------- | --------------------------------------------- |
| `BROADCASTER_ENABLED`        | Run the Kafka→WebSocket broadcaster | `true`                                        |
| `BROADCASTER_CONSUMER_GROUP` | Distinct group from the worker      | `safestream-broadcaster`                      |
| `CORS_ORIGINS`               | Allow-list for the dashboard        | `http://localhost:5173,http://localhost:8080` |

## Hardening

Five rounds of post-Phase-4 hardening landed in this iteration. Each one is
covered by tests; CI runs them on every push.

### 1. Test suites and CI

- **94 tests** across the three services (62 inference, 8 producer, 24
  dashboard).
- The inference suite stubs heavy ML libs (`transformers`,
  `sentence_transformers`) so unit tests run without torch installed.
- `ruff` lint clean across all Python sources.
- `.github/workflows/ci.yml` runs four parallel jobs: inference, producer,
  dashboard, and a multi-arch Docker build smoke test (amd64 + arm64).

```bash
# Run everything locally:
( cd services/inference && pytest )
( cd services/producer  && pytest )
( cd services/dashboard && npm test && npm run build )
ruff check .
```

### 2. Reproducible builds

Each Python service has its own `pyproject.toml` and `uv.lock`. Dockerfiles use
a multi-stage build that runs `uv sync --frozen` from the lock, so the same
image hash builds from the same lock on every machine.

The `inference` lock has 78 packages, the `producer` lock has 17. ML extras live
behind an optional group (`uv sync --extra ml`) so CI can install the test
surface without pulling 700 MB of torch wheels.

### 3. Migrations and metrics

- **Alembic** replaces the previous `init.sql`. The first migration
  (`0001_initial_schema`) recreates the `events`/`predictions`/`audits` tables
  and the `mlops_confusion` view. A new compose service `migrate` runs
  `alembic upgrade head` before the API starts.
- The DSN normaliser (`alembic/dsn.py`) translates `postgresql+asyncpg://` to
  the synchronous psycopg2 URL Alembic needs, and is unit-tested parametrically.
- **Prometheus** instrumentation via `prometheus-fastapi-instrumentator`. The
  API exposes `/metrics` with: standard HTTP histograms / counters per route
  template, the `safestream_inflight_requests` gauge with method + handler
  labels, and a test that verifies the endpoint shape.

### 4. Worker / broadcaster split + DLQ

- The container that used to host _everything_ now ships a single image with
  three roles selected via CLI: `python -m src.cli api`,
  `python -m src.cli worker`, and `python -m src.cli broadcaster`.
- Compose runs `inference` (API + broadcaster, owns the WebSocket clients) and
  `worker` (dedicated moderation pipeline) as separate services using the same
  image with different `command` and a YAML anchor (`<<: *inference_env`) for
  shared env. Scale workers with `docker compose up --scale worker=3`.
- **Dead-letter topic** `content.dead-letter`. The worker tracks attempts via
  Kafka headers and, after `WORKER_MAX_RETRIES` (default 3), parks the record on
  the DLQ with `x-safestream-dlq-reason` and the original topic in headers.
  Validation errors and unhandled modalities go straight to the DLQ on attempt
  1 - no retry would help.

### 5. OpenTelemetry traces (opt-in)

- `setup_tracing()` is called at process start and instruments FastAPI, aiokafka
  and asyncpg in one shot. The aiokafka instrumentation injects W3C
  `traceparent` headers into produced records, so a trace started in the API
  survives the Kafka hop and continues inside the worker span.
- The provider exports OTLP/gRPC. A new `obs` Compose profile brings up an
  OpenTelemetry Collector and Jaeger:

   ```bash
   cp .env.example .env                        # set OTEL_ENABLED=true
   docker compose --profile obs up -d
   open http://localhost:16686                 # Jaeger UI
   ```

   Without the profile and without `OTEL_ENABLED=true`, all the OTel code paths
   are no-ops; the deps are installed but the SDK never starts.
