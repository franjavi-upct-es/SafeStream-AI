# services/inference/src/api/schemas.py
"""HTTP request/response models exposed by the REST surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from domain.verdict import Verdict


class TextClassifyRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8192)
    source_id: str | None = Field(default=None, max_length=128)


class ModelInfoOut(BaseModel):
    name: str
    version: str


class ClassifyResponse(BaseModel):
    event_id: UUID
    modality: str
    verdict: Verdict
    scores: dict[str, float]
    model: ModelInfoOut
    inference_latency_ms: int
    predicted_at: datetime


class HealthResponse(BaseModel):
    status: str
    service: str


class ReadinessResponse(BaseModel):
    status: str
    text_model_loaded: bool
    vision_model_loaded: bool
    embedder_loaded: bool
    database_reachable: bool
    vector_store_reachable: bool


# ---- Semantic search ------------------------------------------------------


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2048)
    limit: int = Field(default=10, ge=1, le=100)
    verdicts: list[Verdict] | None = Field(
        default=None,
        description="Restrict results to these verdicts. None = no filter.",
    )
    min_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Cosine similarity floor; results below are dropped.",
    )


class SemanticSearchHit(BaseModel):
    # Pydantic reserves the ``model_`` prefix; tell it the field name is fine.
    model_config = {"protected_namespaces": ()}

    event_id: UUID
    score: float
    verdict: Verdict | None = None
    modality: str | None = None
    source_id: str | None = None
    content_snippet: str | None = None
    predicted_at: datetime | None = None
    model_name: str | None = None


class SemanticSearchResponse(BaseModel):
    query: str
    count: int
    results: list[SemanticSearchHit]


# ---- Events --------------------------------------------------------------


class EventOut(BaseModel):
    """Event + latest prediction joined, used by the triage grid."""

    model_config = {"protected_namespaces": ()}

    event_id: UUID
    source_id: str | None = None
    modality: str
    content: str | None = None
    content_uri: str | None = None
    ingested_at: datetime
    verdict: Verdict | None = None
    scores: dict[str, float] | None = None
    model_name: str | None = None
    model_version: str | None = None
    inference_latency_ms: int | None = None
    predicted_at: datetime | None = None


class RecentEventsResponse(BaseModel):
    count: int
    events: list[EventOut]


# ---- Audits -------------------------------------------------------------


AuditDecision = Literal["approved", "rejected", "escalated"]


class AuditCreateRequest(BaseModel):
    event_id: UUID
    auditor_id: str = Field(..., min_length=1, max_length=128)
    decision: AuditDecision
    notes: str | None = Field(default=None, max_length=1024)


class AuditOut(BaseModel):
    id: UUID
    event_id: UUID
    auditor_id: str
    decision: AuditDecision
    notes: str | None = None
    decided_at: datetime


# ---- Metrics ------------------------------------------------------------


class TimeseriesPoint(BaseModel):
    bucket: datetime
    verdict: Verdict
    count: int


class TimeseriesResponse(BaseModel):
    bucket_seconds: int
    since: datetime
    points: list[TimeseriesPoint]


class ConfusionMatrixResponse(BaseModel):
    since: datetime
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    # Convenience derived metrics.
    precision: float | None = None
    recall: float | None = None
