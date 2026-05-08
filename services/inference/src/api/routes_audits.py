# services/inference/src/api/routes_audits.py
"""Records human review decisions.

Each row written here feeds the ``mlops_confusion`` view, which in turn
drives View 3's confusion matrix. There is no PUT/DELETE - audits are
append-only by design (an auditor's history is part of the audit trail).
"""

# NOTE: see routes_classify - keep `from __future__ import annotations` OFF.

import asyncpg
from api.deps import limiter, require_api_key
from api.schemas import AuditCreateRequest, AuditOut
from fastapi import APIRouter, Depends, HTTPException, Request, status
from persistence.repository import ModerationRepository

router = APIRouter(prefix="/v1", tags=["audits"])


@router.post(
    "/audits",
    status_code=status.HTTP_201_CREATED,
    response_model=AuditOut,
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("120/minute")
async def create_audit(
    request: Request,
    payload: AuditCreateRequest,
) -> AuditOut:
    repo = ModerationRepository(request.app.state.db_pool)
    try:
        row = await repo.insert_audit(
            event_id=payload.event_id,
            auditor_id=payload.auditor_id,
            decision=payload.decision,
            notes=payload.notes,
        )
    except asyncpg.ForeignKeyViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event {payload.event_id} does not exist.",
        ) from exc
    return AuditOut(**row)
