# services/inference/src/config.py
"""Runtime configuration for the inference service.

All settings are environment-driven so the same image can run in dev, CI,
and production without code changes. Defaults are tuned for the local
Docker Compose stack defined at the repo root.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: Any) -> list[str]:
    """Permit comma-separated env strings to populate list[str] fields."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [item.strip() for item in str(value).split(",") if item.strip()]


CsvList = Annotated[list[str] | str, BeforeValidator(_split_csv)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Service ---------------------------------------------------------
    service_name: str = "safestream-inference"
    log_level: str = "INFO"

    # --- Kafka -----------------------------------------------------------
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_topic_text_in: str = "content.text.raw"
    kafka_topic_image_in: str = "content.image.raw"
    kafka_topic_predictions_out: str = "predictions.results"
    kafka_topic_dlq: str = "content.dead-letter"
    kafka_consumer_group: str = "safestream-inference"

    # Maximum number of times the worker will redeliver a message before
    # parking it on the DLQ. Tracked via a Kafka header on the record.
    worker_max_retries: int = 3

    # --- Database --------------------------------------------------------
    postgres_dsn: str = (
        "postgresql://safestream:safestream@postgres:5432/safestream"
    )
    db_min_pool: int = 1
    db_max_pool: int = 8

    # --- Models ----------------------------------------------------------
    enable_text: bool = True
    enable_vision: bool = False
    enable_embeddings: bool = True

    nlp_model_name: str = "unitary/toxic-bert"
    nlp_model_revision: str | None = None
    nlp_max_length: int = 256

    cv_model_name: str = "Falconsai/nsfw_image_detection"
    cv_model_revision: str | None = None

    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_revision: str | None = None
    # Must match the model above. all-MiniLM-L6-v2 returns 384-dim vectors.
    embedding_dim: int = 384

    # --- Vector store (Qdrant) -------------------------------------------
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "safestream_sanctioned"
    # Verdicts that trigger an upsert into the vector store.
    index_verdicts: CsvList = Field(default_factory=lambda: ["review", "block"])

    # --- Verdict thresholds (applied to max(scores)) ---------------------
    threshold_review: float = Field(default=0.4, ge=0.0, le=1.0)
    threshold_block: float = Field(default=0.8, ge=0.0, le=1.0)

    # --- Auth & rate limiting --------------------------------------------
    # Empty list disables auth; keys are accepted via the X-API-Key header.
    api_keys: CsvList = Field(default_factory=list)
    rate_limit: str = "100/minute"

    # CORS allow-list for the dashboard. Use ["*"] for fully open.
    cors_origins: CsvList = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:8080",
        ]
    )

    # --- Worker ----------------------------------------------------------
    worker_concurrency: int = Field(default=4, ge=1, le=64)
    worker_enabled: bool = True

    # --- WebSocket broadcaster -------------------------------------------
    broadcaster_enabled: bool = True
    broadcaster_consumer_group: str = "safestream-broadcaster"

    # --- Observability ---------------------------------------------------
    # OpenTelemetry. When ``otel_enabled`` is true the application emits
    # OTLP/gRPC spans to ``otel_exporter_endpoint``. Disabled by default
    # so dev runs without a collector don't pay any cost.
    otel_enabled: bool = False
    otel_service_name: str = "safestream-inference"
    otel_exporter_endpoint: str = "http://otel-collector:4317"
    otel_console_export: bool = False  # debug aid: also log spans to stdout


settings = Settings()
