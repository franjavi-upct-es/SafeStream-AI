# services/inference/src/domain/events.py
"""Inbound event contract.

This intentionally duplicates ``services/producer/src/schema.py``: each service
owns its copy of the JSON contract so it can be deployed independently. The
contract is documented in README.md - if you change one, change the other.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

Modality = Literal["text", "image"]


class JigsawLabels(BaseModel):
    toxic: int = 0
    severe_toxic: int = 0
    obscene: int = 0
    threat: int = 0
    insult: int = 0
    identity_hate: int = 0


class ContentEvent(BaseModel):
    """Inbound payload pulled off the Kafka topics."""

    event_id: UUID = Field(default_factory=uuid4)
    source_id: str | None = None
    modality: Modality = "text"
    content: str | None = None
    content_uri: str | None = None
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
    )
    ground_truth: JigsawLabels | None = None
