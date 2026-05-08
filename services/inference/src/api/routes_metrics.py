# services/inference/src/api/routes_metrics.py
"""MLOps endpoints used by View 3 of the dashboard."""

# NOTE: see routes_classify - keep `from __future__ import annotations` OFF.

from datetime import UTC, datetime, timedelta

from api.deps import limiter, require_api_key
from api.schemas import (
    ConfusionMatrixResponse,
    TimeseriesPoint,
    TimeseriesResponse,
)
from fastapi import APIRouter, Depends, Query, Request
from persistence.repository import ModerationRepository

router = APIRouter(prefix="/v1", tags=["metrics"])


def _since_from_minutes(minutes: int) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


@router.get(
    "/metrics/timeseries",
    response_model=TimeseriesResponse,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("60/minute")
async def timeseries(
    request: Request,
    since_minutes: int = Query(default=60, ge=1, le=25 * 60),
    bucket_seconds: int = Query(default=60, ge=10, le=3600),
) -> TimeseriesResponse:
    since = _since_from_minutes(since_minutes)
    repo = ModerationRepository(request.app.state.db_pool)
    rows = await repo.predictions_timeseries(
        since=since, bucket_seconds=bucket_seconds
    )
    points = [
        TimeseriesPoint(
            bucket=row["bucket"], verdict=row["verdict"], count=row["count"]
        )
        for row in rows
    ]
    return TimeseriesResponse(
        bucket_seconds=bucket_seconds,
        since=since,
        points=points,
    )


@router.get(
    "/metrics/confusion",
    response_model=ConfusionMatrixResponse,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("60/minute")
async def confusion(
    request: Request,
    since_minutes: int = Query(default=60, ge=1, le=24 * 60),
) -> ConfusionMatrixResponse:
    since = _since_from_minutes(since_minutes)
    repo = ModerationRepository(request.app.state.db_pool)
    cells = await repo.confusion_matrix(since=since)

    tp, fp, tn, fn = cells["tp"], cells["fp"], cells["tn"], cells["fn"]

    # Avoid divide-by-zero so the dashboard can render clean placeholders.
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None

    return ConfusionMatrixResponse(
        since=since,
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        precision=precision,
        recall=recall,
    )
