# services/inference/src/models/text.py
"""Hugging Face based text classifier.

Loaded once at application startup and pinned to RAM. Inference itself is
synchronous (PyTorch CPU) so we run each call inside an executor thread to
keep the FastAPI event loop responsive.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from app_logging import get_logger
from typing import Any

from config import settings
from models.base import ModelInfo, Prediction
from transformers import pipeline as hf_pipeline

log = get_logger(__name__)


class TextClassifier:
    """Multi-label toxicity classifier."""

    def __init__(
        self,
        *,
        model_name: str,
        revision: str | None = None,
        max_length: int = 256,
    ) -> None:
        self.info = ModelInfo(name=model_name, revision=revision)
        self._max_length = max_length
        # A single-threaded executor protects PyTorch from concurrent calls
        # on the same module while still freeing the event loop.
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="nlp-infer",
        )
        log.info(
            "loading_text_model",
            model=model_name,
            revision=revision,
        )
        self._pipeline = hf_pipeline(
            task="text-classification",
            model=model_name,
            revision=revision,
            top_k=None,  # return all labels
            truncation=True,
            max_length=max_length,
        )
        log.info("text_model_loaded", model=model_name)

    def _run(self, text: str) -> list[dict[str, Any]]:
        # The HF pipeline returns a list-of-lists when given a single string
        # with top_k=None - flatten down to one list.
        result = self._pipeline(
            text, truncation=True, max_length=self._max_length
        )
        if result and isinstance(result[0], list):
            return result[0]
        return result  # type: ignore[return-value]

    async def classify(self, text: str) -> Prediction:
        if not text or not text.strip():
            return Prediction(
                scores={},
                inference_latency_ms=0,
                model=self.info,
            )

        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        raw = await loop.run_in_executor(self._executor, self._run, text)
        latency_ms = int((time.perf_counter() - started) * 1000)

        scores = {
            str(item["label"]).lower(): float(item["score"]) for item in raw
        }
        return Prediction(
            scores=scores,
            inference_latency_ms=latency_ms,
            model=self.info,
        )

    async def aclose(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def build_text_classifier() -> TextClassifier:
    return TextClassifier(
        model_name=settings.nlp_model_name,
        revision=settings.nlp_model_revision,
        max_length=settings.nlp_max_length,
    )
