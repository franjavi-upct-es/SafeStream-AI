# services/inference/src/models/registry.py
"""Singleton container for the loaded models.

Owns the lifecycle - construction (which downloads weights and pins them in
RAM) and graceful disposal at shutdown. Exposed through ``app.state`` so both
the worker and the request handlers can grab the same instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from app_logging import get_logger

from config import settings
from models.embeddings import TextEmbedder, build_text_embedder
from models.text import TextClassifier, build_text_classifier
from models.vision import VisionClassifier, build_vision_classifier

log = get_logger(__name__)


@dataclass
class ModelRegistry:
    text: TextClassifier | None = None
    vision: VisionClassifier | None = None
    embedder: TextEmbedder | None = None

    def is_ready(self) -> bool:
        """Returns True iff every requrested model finished loading."""
        if settings.enable_text and self.text is None:
            return False
        if settings.enable_vision and self.vision is None:
            return False
        return not (settings.enable_embeddings and self.embedder is None)

    async def aclose(self) -> None:
        if self.text is not None:
            await self.text.aclose()
        if self.vision is not None:
            await self.vision.aclose()
        if self.embedder is not None:
            await self.embedder.aclose()


def build_registry() -> ModelRegistry:
    """Construct (and load) a registry honoring the enable_* flags."""
    registry = ModelRegistry()

    if settings.enable_text:
        registry.text = build_text_classifier()
    else:
        log.warning("text_model_disabled")

    if settings.enable_vision:
        registry.vision = build_vision_classifier()
    else:
        log.warning("vision_model_disabled")

    if settings.enable_embeddings:
        registry.embedder = build_text_embedder()
    else:
        log.warning("embedder_disabled")

    return registry
