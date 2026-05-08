# services/producer/src/config.py
"""Runtime configuration for the producer service.

Values are pulled from environment variables; sensible defaults are provided
so the service can boot inside Docker Compose without an explicit `.env`.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProducerSettings(BaseSettings):
    """Configuration loaded from the process environment."""

    model_config = SettingsConfigDict(
        env_file=None,
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    # Kafka --------------------------------------------------------------
    kafka_bootstrap_servers: str = Field(
        default="kafka:9092",
        description="Comma-separated list of Kafka bootstrap servers.",
    )
    kafka_topic_text: str = Field(
        default="content.text.raw",
        description="Topic that receives text events.",
    )
    kafka_client_id: str = Field(default="safestream-producer")

    # Dataset ------------------------------------------------------------
    dataset_path: Path = Field(
        default=Path("/app/data/sample_comments.csv"),
        description="CSV file that follows the Jigsaw schema.",
    )
    loop_dataset: bool = Field(
        default=True,
        description="Restart from the top once the dataset is exhausted.",
    )

    # Throughput ---------------------------------------------------------
    events_per_second: float = Field(
        default=10.0,
        gt=0,
        description="Target ingestion rate.",
    )

    # Observability ------------------------------------------------------
    log_level: str = Field(default="INFO")


settings = ProducerSettings()
