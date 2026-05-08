# services/inference/src/api/routes_search.py
"""Semantic search endpoint - drives the audit UI's Omnibox (Phase 4 / View 2).

The flow is straightforward:

    user query  ->  embedder.embed(query)  ->  vector_store.search(...)
                ->  shape Qdrant payloads back into HTTP response

Both the embedder and the vector store may be unavailable (model disabled,
Qdrant down at startup, etc). The handler returns 503 in those cases rather
than failing opaquely.
"""

# NOTE: Same caveat as routes_classify - do NOT add `from __future__ import
# annotations` here. FastAPI + slowapi cannot resolve forward refs in body
# parameters when annotations are stringified.

from datetime import datetime

from api.deps import limiter, require_api_key
from api.schemas import (
    SemanticSearchHit,
    SemanticSearchRequest,
    SemanticSearchResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status

router = APIRouter(prefix="/v1", tags=["search"])


def _coerce_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


@router.post(
    "/search/semantic",
    response_model=SemanticSearchResponse,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("60/minute")
async def semantic_search(
    request: Request,
    payload: SemanticSearchRequest,
) -> SemanticSearchResponse:
    embedder = request.app.state.models.embedder
    vector_store = request.app.state.vector_store

    if embedder is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding model is disabled on this deployment.",
        )
    if vector_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector store is unavailable.",
        )

    embedding = await embedder.embed(payload.query)
    hits = await vector_store.search(
        vector=embedding.vector,
        limit=payload.limit,
        verdicts=payload.verdicts,
        min_score=payload.min_score,
    )

    results = [
        SemanticSearchHit(
            event_id=hit.event_id,
            score=hit.score,
            verdict=hit.payload.get("verdict"),
            modality=hit.payload.get("modality"),
            source_id=hit.payload.get("source_id"),
            content_snippet=hit.payload.get("content_snippet"),
            predicted_at=_coerce_datetime(hit.payload.get("predicted_at")),
            model_name=hit.payload.get("model_name"),
        )
        for hit in hits
    ]

    return SemanticSearchResponse(
        query=payload.query,
        count=len(results),
        results=results,
    )
