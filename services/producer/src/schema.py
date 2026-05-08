# services/producer/src/schema.py
"""JSON contracts emitted to Kafka.

Keeping these as Pydantic models gives us:
  * Validation at the producer side (we never publish a malformed event).
  * A single source of truth for the inference service to import later.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

Modality = Literal["text", "image"]


class JigsawLabels(BaseModel):
    """Ground-truth labels carried by Jigsaw rows.

    They are passed through the pipeline only so we can later compute
    offline metrics; the inference service must NOT use them.
    """

    toxic: int = 0
    severe_toxic: int = 0
    obscene: int = 0
    threat: int = 0
    insult: int = 0
    identity_hate: int = 0


class ContentEvent(BaseModel):
    """A single piece of user-generated content travelling through the bus."""

    event_id: UUID = Field(default_factory=uuid4)
    source_id: str | None = Field(
        default=None,
        description="Identifier from the upstream dataset / customer system.",
    )
    modality: Modality = "text"
    content: str | None = None
    content_uri: str | None = None
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
    )
    ground_truth: JigsawLabels | None = None
