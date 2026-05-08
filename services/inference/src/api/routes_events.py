# services/inference/src/api/routes_events.py
"""Read-only routes that back the triage grid and detail panel."""

# NOTE: see routes_classify - keep `from __future__ import annotations` OFF.

from uuid import UUID

from api._mapping import event_row_to_out
from api.deps import limiter, require_api_key
from api.schemas import EventOut, RecentEventsResponse
from domain.verdict import Verdict
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from persistence.repository import ModerationRepository

router = APIRouter(prefix="/v1", tags=["events"])


@router.get(
    "/events/recent",
    response_model=RecentEventsResponse,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("120/minute")
async def list_recent(
    request: Request,
    verdicts: list[Verdict] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> RecentEventsResponse:
    """Recent events with their latest predictions.

    The dashboard's triage view calls this on first paint to fill the grid
    before the WebSocket starts pushing live updates.
    """
    repo = ModerationRepository(request.app.state.db_pool)
    rows = await repo.list_recent_events(verdicts=verdicts, limit=limit)
    events = [event_row_to_out(r) for r in rows]
    return RecentEventsResponse(count=len(events), events=events)


@router.get(
    "/events/{event_id}",
    response_model=EventOut,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("240/minute")
async def get_event(request: Request, event_id: UUID) -> EventOut:
    repo = ModerationRepository(request.app.state.db_pool)
    row = await repo.get_event(request.app.state.db_pool)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {event_id} not found.",
        )
    return event_row_to_out(row)
