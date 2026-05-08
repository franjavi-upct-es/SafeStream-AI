# services/inference/src/models/vision.py
"""Hugging Face based image classififer (binary safe / unsafe by default).

Loaded only when ``ENABLE_VISION=true`` so first-time local runs stay light.
"""

from __future__ import annotations

import asyncio
import io
import time
from concurrent.futures import ThreadPoolExecutor
from app_logging import get_logger
from typing import Any

from config import settings
from models.base import ModelInfo, Prediction
from PIL import Image
from transformers import pipeline as hf_pipeline

log = get_logger(__name__)


class VisionClassifier:
    def __init__(
        self,
        *,
        model_name: str,
        revision: str | None = None,
    ) -> None:
        self.info = ModelInfo(name=model_name, revision=revision)
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="cv-infer",
        )
        log.info(
            "loading_vision_model",
            model=model_name,
            revision=revision,
        )
        self._pipeline = hf_pipeline(
            task="image-classification",
            model=model_name,
            revision=revision,
            top_k=None,
        )
        log.info("vision_model_loaded", model=model_name)

    def _decode(self, image_bytes: bytes) -> Image.Image:
        img = Image.open(io.BytesIO(image_bytes))
        # Many vision models chocke on RGBA / palette modes.
        if img.mode != "RGB":
            img = img.convert("RGB")
        return img

    def _run(self, image_bytes: bytes) -> list[dict[str, Any]]:
        image = self._decode(image_bytes)
        result = self._pipeline(image)
        if result and isinstance(result[0], list):
            return result[0]
        return result  # type: ignore[return-value]

    async def classify(self, image_bytes: bytes) -> Prediction:
        if not image_bytes:
            return Prediction(
                scores={},
                inference_latency_ms=0,
                model=self.info,
            )

        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        raw = await loop.run_in_executor(self._executor, self._run, image_bytes)
        latency_ms = int((time.perf_counter() - started) * 1000)

        scores = {
            str(item["label"]).lower(): float(item["score"]) for item in raw
        }
        return Prediction(
            scores=scores, inference_latency_ms=latency_ms, model=self.info
        )

    async def aclose(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def build_vision_classifier() -> VisionClassifier:
    return VisionClassifier(
        model_name=settings.cv_model_name, revision=settings.cv_model_revision
    )
