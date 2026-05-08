# services/producer/src/dataset.py
"""Streaming iterator over a Jigsaw-shaped CSV.

The Jigsaw Toxic Comment Classification Challenge dataset has the columns:

    id, comment_text, toxic, severe_toxic, obscene, threat, insult, identity_hate

This module yields one ``ContentEvent`` per row, optionally looping forever so
the producer can keep feeding the broker during long demos without needing a
huge CSV.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from schema import ContentEvent, JigsawLabels

_LABEL_COLUMNS = (
    "toxic",
    "severe_toxic",
    "obscene",
    "threat",
    "insult",
    "identity_hate",
)


def _coerce_int(value: str | None) -> int:
    """Best-effort cast to int; missing / blank cells become 0."""
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except ValueError:
        # Some Jigsaw mirrors store labels as floats ("0.0"). Handle gracefully.
        return int(float(value))


def _row_to_event(row: dict[str, str]) -> ContentEvent:
    labels = JigsawLabels(
        **{column: _coerce_int(row.get(column)) for column in _LABEL_COLUMNS}
    )
    return ContentEvent(
        source_id=row.get("id") or None,
        modality="text",
        content=row.get("comment_text", ""),
        ground_truth=labels,
    )


def iter_events(path: Path, *, loop: bool = False) -> Iterator[ContentEvent]:
    """Yield ``ContentEvent`` instances read from the CSV at ``path``.

    Parameters
    ----------
    path:
        File-system path to the dataset.
    loop:
        When True, restart from the top of the file after EOF.
    """

    if not path.exists():
        raise FileNotFoundError(f"Dataset not found at {path!s}")

    while True:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = {"id", "comment_text"} - set(reader.fieldnames or [])
            if missing:
                raise ValueError(
                    f"Dataset {path!s} is missing required columns: {sorted(missing)}"
                )
            for row in reader:
                yield _row_to_event(row)

        if not loop:
            return
