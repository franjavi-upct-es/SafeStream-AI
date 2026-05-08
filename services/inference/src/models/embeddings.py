# services/inference/src/models/embeddings.py
"""Sentence embedding model.

Same pattern as the NLP and CV classifiers: weights are loaded into RAM
once at startup, calls run in a single-threaded executor to keep the event
loop free, and the public surface is a thin async method.

The vector returned matches ``settings.embedding_dim`` exactly. If the
configured model produces a different dimension at load time, the wrapper
fails fast - this avoids silently breaking the Qdrant collection.
"""

import asyncio
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from app_logging import get_logger

from config import settings
from models.base import ModelInfo
from sentence_transformers import SentenceTransformer

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Embedding:
    vector: list[float]
    inference_latency_ms: int
    model: ModelInfo


class TextEmbedder:
    """Generate dense vectors for a piece of text or a batch."""

    def __init__(
        self,
        *,
        model_name: str,
        revision: str | None = None,
        expected_dim: int,
    ) -> None:
        self.info = ModelInfo(name=model_name, revision=revision)
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="emb-infer",
        )
        log.info("loading_embedding_model", model=model_name, revision=revision)
        self._model = SentenceTransformer(model_name, revision=revision)
        actual_dim = int(self._model.get_sentence_embedding_dimension())
        if actual_dim != expected_dim:
            raise RuntimeError(
                f"Embedding model {model_name!r} produces {actual_dim}-dim "
                f"vectors but EMBEDDING_DIM is set to {expected_dim}. "
                f"Update EMBEDDING_DIM and (if a Qdrant collection already "
                f"exists with the wrong size) re-create the collection."
            )
        self._dim = actual_dim
        log.info("embedding_model_loaded", model=model_name, dim=actual_dim)

    @property
    def dim(self) -> int:
        return self._dim

    def _run_one(self, text: str) -> list[float]:
        # ``encode`` accepts a single string and returns a 1-D ndarray.
        vector = self._model.encode(
            text,
            normalize_embeddings=True,  # cosine distance == dot product
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vector.tolist()

    def _run_batch(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            batch_size=32,
        )
        return [v.tolist() for v in vectors]

    async def embed(self, text: str) -> Embedding:
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")

        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        vector = await loop.run_in_executor(self._executor, self._run_one, text)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return Embedding(
            vector=vector,
            inference_latency_ms=latency_ms,
            model=self.info,
        )

    async def embed_batch(self, texts: Sequence[str]) -> list[Embedding]:
        if not texts:
            return []
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        vectors = await loop.run_in_executor(
            self._executor,
            self._run_batch,
            texts,
        )
        # Approximate per-item latency by sharing the wall-clock cost.
        latency_ms = max(
            1, int((time.perf_counter() - started) * 1000 / len(texts))
        )
        return [
            Embedding(
                vector=v, inference_latency_ms=latency_ms, model=self.info
            )
            for v in vectors
        ]

    async def aclose(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def build_text_embedder() -> TextEmbedder:
    return TextEmbedder(
        model_name=settings.embedding_model_name,
        revision=settings.embedding_model_revision,
        expected_dim=settings.embedding_dim,
    )
