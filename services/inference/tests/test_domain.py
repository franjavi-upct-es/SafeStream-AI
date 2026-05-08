# services/inference/tests/test_domain.py
"""Unit tests for the small domain modules.

These exercise pure logic: no FastAPI, no asyncio, no fixtures beyond
the auto-applied settings reset.
"""

from __future__ import annotations

from datetime import UTC

import pytest


@pytest.mark.parametrize(
    "scores,expected",
    [
        ({}, "safe"),
        ({"toxic": 0.05}, "safe"),
        # right at the review boundary
        ({"toxic": 0.39}, "safe"),
        ({"toxic": 0.40}, "review"),
        # mixed signals: only the max counts
        ({"toxic": 0.79, "insult": 0.10}, "review"),
        ({"toxic": 0.20, "insult": 0.95}, "block"),
        # right at the block boundary
        ({"toxic": 0.80}, "block"),
    ],
)
def test_derive_verdict_thresholds(
    scores: dict[str, float], expected: str
) -> None:
    from domain.verdict import derive_verdict

    assert derive_verdict(scores) == expected


def test_derive_verdict_custom_thresholds() -> None:
    from domain.verdict import derive_verdict

    # With looser thresholds, the same scores fall in different buckets.
    assert (
        derive_verdict(
            {"toxic": 0.2}, threshold_review=0.1, threshold_block=0.5
        )
        == "review"
    )
    assert (
        derive_verdict(
            {"toxic": 0.6}, threshold_review=0.1, threshold_block=0.5
        )
        == "block"
    )


def test_content_event_round_trip() -> None:
    """JSON serialization must preserve every field through the pipeline."""
    from domain.events import ContentEvent, JigsawLabels

    original = ContentEvent(
        source_id="abc-123",
        modality="text",
        content="hello world",
        ground_truth=JigsawLabels(toxic=1, insult=1),
    )
    payload = original.model_dump_json()
    decoded = ContentEvent.model_validate_json(payload)

    assert decoded.event_id == original.event_id
    assert decoded.source_id == "abc-123"
    assert decoded.content == "hello world"
    assert decoded.ground_truth is not None
    assert decoded.ground_truth.toxic == 1
    assert decoded.ground_truth.insult == 1


def test_content_event_default_ingested_at_is_utc() -> None:
    from domain.events import ContentEvent

    event = ContentEvent(content="x")
    assert event.ingested_at.tzinfo is not None
    assert event.ingested_at.utcoffset() == UTC.utcoffset(event.ingested_at)
