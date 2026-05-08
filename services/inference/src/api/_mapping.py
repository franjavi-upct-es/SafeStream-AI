# services/inference/src/api/_mapping.py
"""Tiny adapters used by multiple route modules."""

import json
from typing import Any

from api.schemas import EventOut


def event_row_to_out(row: dict[str, Any]) -> EventOut:
    """Convert a row from ``list_recent_events`` / ``get_event`` into an EventOut."""

    raw_scores = row.get("scores")
    if isinstance(raw_scores, str):
        try:
            scores = json.loads(raw_scores)
        except json.JSONDecodeError:
            scores = None
    else:
        scores = raw_scores

    return EventOut(
        event_id=row["id"],
        source_id=row.get("source_id"),
        modality=row["modality"],
        content=row.get("content"),
        content_uri=row.get("content_uri"),
        ingested_at=row["ingested_at"],
        verdict=row.get("verdict"),
        scores=scores,
        model_name=row.get("model_name"),
        model_version=row.get("model_version"),
        inference_latency_ms=row.get("inference_latency_ms"),
        predicted_at=row.get("predicted_at"),
    )
