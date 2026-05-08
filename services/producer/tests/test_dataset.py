# services/producer/tests/test_dataset.py
"""Producer unit tests.

Covers the CSV iterator, label coercion edge cases, and the JSON
contract emitted to Kafka.
"""

from __future__ import annotations

import csv
import itertools
from pathlib import Path

import pytest


def _write_csv(
    path: Path, rows: list[dict[str, str]], fieldnames: list[str]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_iter_events_yields_one_event_per_row(tmp_path: Path) -> None:
    from dataset import iter_events

    csv_path = tmp_path / "tiny.csv"
    _write_csv(
        csv_path,
        rows=[
            {"id": "1", "comment_text": "hi", "toxic": "0"},
            {"id": "2", "comment_text": "you are awful", "toxic": "1"},
        ],
        fieldnames=["id", "comment_text", "toxic"],
    )

    events = list(iter_events(csv_path, loop=False))

    assert len(events) == 2
    assert events[0].source_id == "1"
    assert events[0].content == "hi"
    assert events[1].ground_truth is not None
    assert events[1].ground_truth.toxic == 1


def test_iter_events_loops_when_requested(tmp_path: Path) -> None:
    """``loop=True`` restarts from the top after EOF."""
    from dataset import iter_events

    csv_path = tmp_path / "loop.csv"
    _write_csv(
        csv_path,
        rows=[
            {"id": "1", "comment_text": "a"},
            {"id": "2", "comment_text": "b"},
        ],
        fieldnames=["id", "comment_text"],
    )

    events = list(itertools.islice(iter_events(csv_path, loop=True), 5))

    assert len(events) == 5
    # Cycles: 1, 2, 1, 2, 1
    assert [e.source_id for e in events] == ["1", "2", "1", "2", "1"]


def test_iter_events_handles_float_labels(tmp_path: Path) -> None:
    """Some Jigsaw mirrors store label columns as ``"0.0"`` / ``"1.0"``."""
    from dataset import iter_events

    csv_path = tmp_path / "floats.csv"
    _write_csv(
        csv_path,
        rows=[
            {"id": "1", "comment_text": "x", "toxic": "1.0", "insult": "0.0"}
        ],
        fieldnames=["id", "comment_text", "toxic", "insult"],
    )

    [event] = list(iter_events(csv_path, loop=False))
    assert event.ground_truth is not None
    assert event.ground_truth.toxic == 1
    assert event.ground_truth.insult == 0


def test_iter_events_handles_blank_label_cells(tmp_path: Path) -> None:
    """Missing label values must default to 0, not crash."""
    from dataset import iter_events

    csv_path = tmp_path / "blanks.csv"
    _write_csv(
        csv_path,
        rows=[{"id": "1", "comment_text": "x", "toxic": ""}],
        fieldnames=["id", "comment_text", "toxic"],
    )

    [event] = list(iter_events(csv_path, loop=False))
    assert event.ground_truth is not None
    assert event.ground_truth.toxic == 0


def test_iter_events_raises_on_missing_columns(tmp_path: Path) -> None:
    from dataset import iter_events

    csv_path = tmp_path / "broken.csv"
    _write_csv(
        csv_path,
        rows=[{"foo": "bar"}],
        fieldnames=["foo"],
    )

    with pytest.raises(ValueError, match="missing required columns"):
        next(iter_events(csv_path, loop=False))


def test_iter_events_raises_on_missing_file(tmp_path: Path) -> None:
    from dataset import iter_events

    with pytest.raises(FileNotFoundError):
        next(iter_events(tmp_path / "nope.csv", loop=False))
