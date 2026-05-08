# services/inference/src/models/base.py
"""Common shape for any classifier the inference service can host.

The two concrete implementations (``TextClassifier`` and ``VisionClassifier``)
both expose a small async interface so the worker and the REST routes never
need to know whether they are talking to a transformer or a CNN.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Identity card returned alongside every prediction."""

    name: str
    revision: str | None = None

    @property
    def version(self) -> str:
        return self.revision or "default"


@dataclass(frozen=True, slots=True)
class Prediction:
    """Raw output of a classifier call."""

    scores: dict[str, float]
    inference_latency_ms: int
    model: ModelInfo


class TextModel(Protocol):
    info: ModelInfo

    async def classify(self, text: str) -> Prediction: ...


class ImageModel(Protocol):
    info: ModelInfo

    async def classify(self, image_bytes: bytes) -> Prediction: ...
