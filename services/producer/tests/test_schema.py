# services/producer/tests/test_schema.py
"""ContentEvent schema contract."""

from __future__ import annotations

import json
from datetime import UTC


def test_event_serializes_to_json_with_expected_keys() -> None:
    from schema import ContentEvent, JigsawLabels

    event = ContentEvent(
        source_id="x",
        content="hello",
        ground_truth=JigsawLabels(toxic=1),
    )
    payload = event.model_dump_json()
    decoded = json.loads(payload)

    expected = {
        "event_id",
        "source_id",
        "modality",
        "content",
        "content_uri",
        "ingested_at",
        "ground_truth",
    }
    assert expected.issubset(decoded.keys())
    assert decoded["ground_truth"]["toxic"] == 1


def test_default_ingested_at_is_utc_aware() -> None:
    from schema import ContentEvent

    event = ContentEvent()
    assert event.ingested_at.tzinfo is not None
    assert event.ingested_at.utcoffset() == UTC.utcoffset(event.ingested_at)
