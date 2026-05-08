# services/inference/src/api/routes_classify.py
"""Synchronous classification endpoints.

These are not the primary path - production traffic flows through Kafka and
the worker. They exist for two reasons:

  1. Smoke testing the loaded models without a broker round-trip.
  2. Letting integrators evaluate single payloads on demand (e.g. tooling
     that needs an immediate verdict before submitting content).

Both endpoints persist the event and the prediction so they appear in the
auditing UI just like worker-driven traffic.
"""

# NOTE: Do NOT add `from __future__ import annotations` here. FastAPI's body
# parameter resolution combined with slowapi's @limiter.limit decorator loses
# the module globals when annotations are stringified, causing NameError on
# Pydantic-bound body schemas at app startup.

from datetime import UTC, datetime

from api.deps import limiter, require_api_key
from api.schemas import ClassifyResponse, ModelInfoOut, TextClassifyRequest
from domain.events import ContentEvent
from domain.verdict import derive_verdict
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from persistence.repository import ModerationRepository

router = APIRouter(prefix="/v1", tags=["classify"])

# Cap uploads at 5 MiB to bound memory pressure on the inference worker.
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


@router.post(
    "/classify/text",
    response_model=ClassifyResponse,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("60/minute")
async def classify_text(
    request: Request, payload: TextClassifyRequest
) -> ClassifyResponse:
    registry = request.app.state.models
    if registry.text is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Text model is disabled on this development.",
        )

    event = ContentEvent(
        source_id=payload.source_id, modality="text", content=payload.content
    )
    prediction = await registry.text.classify(payload.content)
    verdict = derive_verdict(prediction.scores)

    pool = request.app.state.db_pool
    repo = ModerationRepository(pool)
    event_id = await repo.insert_event(event)
    await repo.insert_prediction(
        event_id=event_id, prediction=prediction, verdict=verdict
    )

    return ClassifyResponse(
        event_id=event_id,
        modality="text",
        verdict=verdict,
        scores=prediction.scores,
        model=ModelInfoOut(
            name=prediction.model.name,
            version=prediction.model.version,
        ),
        inference_latency_ms=prediction.inference_latency_ms,
        predicted_at=datetime.now(UTC),
    )


@router.post(
    "/classify/image",
    response_model=ClassifyResponse,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("30/minute")
async def classify_image(
    request: Request, file: UploadFile
) -> ClassifyResponse:
    registry = request.app.state.models
    if registry.vision is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vision model is disabled on this deployment.",
        )

    image_bytes = await file.read(_MAX_IMAGE_BYTES + 1)
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image larger tha {_MAX_IMAGE_BYTES} bytes.",
        )
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty upload.",
        )

    event = ContentEvent(
        modality="image", content_uri=f"upload://{file.filename or 'unnamed'}"
    )
    prediction = await registry.vision.classify(image_bytes)
    verdict = derive_verdict(prediction.scores)

    pool = request.app.state.db_pool
    repo = ModerationRepository(pool)
    event_id = await repo.insert_event(event)
    await repo.insert_prediction(
        event_id=event_id, prediction=prediction, verdict=verdict
    )

    return ClassifyResponse(
        event_id=event_id,
        modality="image",
        verdict=verdict,
        scores=prediction.scores,
        model=ModelInfoOut(
            name=prediction.model.name, version=prediction.model.version
        ),
        inference_latency_ms=prediction.inference_latency_ms,
        predicted_at=datetime.now(UTC),
    )
