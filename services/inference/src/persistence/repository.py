# services/inference/src/persistence/repository.py
"""Database access object.

Two responsibilities:

  * ``record_event_with_prediction`` writes the inbound event and the model's
    verdict inside one transaction. The event is the natural source of truth -
    the prediction is meaningless without it.
  * ``insert_event_only`` and ``insert_prediction`` are thin helpers used by
    the synchronous REST endpoint, which separates the two writes.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg
from domain.events import ContentEvent
from domain.verdict import Verdict
from models.base import Prediction


class ModerationRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Combined write (used by the worker)
    # ------------------------------------------------------------------
    async def record_event_with_prediction(
        self,
        *,
        event: ContentEvent,
        prediction: Prediction,
        verdict: Verdict,
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        """Insert event + prediction atomically. Returns the event UUID.

        Uses ``ON CONFLICT DO NOTHING`` on events so a Kafka redelivery after
        a partial failure does not bomb on the primary key. The prediction is
        always inserted: if the event already existed the prediction row is
        a fresh attempt by a (possibly newer) model.
        """

        meta_payload = dict(metadata or {})
        if event.ground_truth is not None:
            meta_payload.setdefault(
                "ground_truth", event.ground_truth.model_dump()
            )

        async with self._pool.acquire() as conn, conn.transaction():
            event_id = await conn.fetchval(
                """
                INSERT INTO events (
                    id, source_id, modality, content, content_uri,
                    metadata, ingested_at
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                ON CONFLICT (id) DO UPDATE
                    SET id = events.id -- no-op write to force RETURNING
                RETURNING id
                """,
                event.event_id,
                event.source_id,
                event.modality,
                event.content,
                event.content_uri,
                json.dumps(meta_payload),
                event.ingested_at,
            )
            await conn.execute(
                """
                INSERT INTO predictions (
                    event_id, model_name, model_version, scores,
                    verdict, inference_latency_ms
                )
                VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                """,
                event_id,
                prediction.model.name,
                prediction.model.version,
                json.dumps(prediction.scores),
                verdict,
                prediction.inference_latency_ms,
            )
        return event_id

    # ------------------------------------------------------------------
    # Single-purpose helpers (used by the REST endpoints)
    # ------------------------------------------------------------------
    async def insert_event(self, event: ContentEvent) -> UUID:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                """
                INSERT INTO events (
                    id, source_id, modality, content, content_uri,
                    metadata, ingested_at
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                RETURNING id
                """,
                event.event_id,
                event.source_id,
                event.modality,
                event.content,
                event.content_uri,
                json.dumps({}),
                event.ingested_at,
            )

    async def insert_prediction(
        self, *, event_id: UUID, prediction: Prediction, verdict: Verdict
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO predictions (
                    event_id, model_name, model_version, scores,
                    verdict, inference_latency_ms
                )
                VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                """,
                event_id,
                prediction.model.name,
                prediction.model.version,
                json.dumps(prediction.scores),
                verdict,
                prediction.inference_latency_ms,
            )

    # ------------------------------------------------------------------
    # Read path (dashboard endpoints)
    # ------------------------------------------------------------------
    async def list_recent_events(
        self,
        *,
        verdicts: Iterable[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent events joined with their latest prediction.

        ``verdicts`` filters on the predictions verdict; pass None for no filter.
        Used by the triage view to paint the initial grid before the WebSocket
        starts pushing live updates.
        """

        verdict_list = list(verdicts) if verdicts else None
        # DISTINCT ON pulls the latest prediction per event in one query
        # (ordered by predicted_at DESC inside each event partition).
        sql = """
            WITH latest AS (
                SELECT DISTINCT ON (event_id)
                    event_id, model_name, model_version, scores,
                    verdict, inference_latency_ms, predicted_at
                FROM predictions
                ORDER BY event_id, predicted_at DESC
            )
            SELECT
                e.id, e.source_id, e.modality, e.content, e.content_uri,
                e.metadata, e.ingested_at,
                l.model_name, l.model_version, l.scores, l.verdict,
                l.inference_latency_ms, l.predicted_at
            FROM events e
            JOIN latest l ON l.event_id = e.id
            WHERE ($1::text[] IS NULL OR l.verdict = ANY($1::text[]))
            ORDER BY l.predicted_at DESC
            LIMIT $2
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, verdict_list, limit)
        return [dict(row) for row in rows]

    async def get_event(self, event_id: UUID) -> dict[str, Any] | None:
        sql = """
            SELECT
                e.id, e.source_id, e.modality, e.content, e.content_uri,
                e.metadata, e.ingested_at,
                p.model_name, p.model_version, p.scores, p.verdict,
                p.inference_latency_ms, p.predicted_at
            FROM events e
            LEFT JOIN LATERAL (
                SELECT * FROM predictions
                WHERE event_id = e.id
                ORDER BY predicted_at DESC
                LIMIT 1
            ) p ON true
            WHERE e.id = $1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, event_id)
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Audits (human review feedback)
    # ------------------------------------------------------------------
    async def insert_audit(
        self,
        *,
        event_id: UUID,
        auditor_id: str,
        decision: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        sql = """
            INSERT INTO audits (event_id, auditor_id, decision, notes)
            VALUES ($1, $2, $3, $4)
            RETURNING id, event_id, auditor_id, decision, notes, decided_at
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                sql, event_id, auditor_id, decision, notes
            )
        return dict(row)

    # ------------------------------------------------------------------
    # MLOps metrics
    # ------------------------------------------------------------------
    async def predictions_timeseries(
        self, *, since: datetime, bucket_seconds: int = 60
    ) -> list[dict[str, Any]]:
        """Bucketed counts of predictions, grouped by verdict."""
        sql = """
            SELECT
                to_timestamp(
                    floor(extract(epoch FROM predicted_at) / $2) * $2
                ) AT TIME ZONE 'UTC' AS bucket,
                verdict,
                COUNT(*) AS count
            FROM predictions
            WHERE predicted_at >= $1
            GROUP BY bucket, verdict
            ORDER BY bucket ASC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, since, bucket_seconds)
        return [dict(row) for row in rows]

    async def confusion_matrix(
        self,
        *,
        since: datetime,
    ) -> dict[str, int]:
        """Counts of TP/FP/TN/FN against the mlops_confusion view.

        ``model_positive`` = the model returned review or block.
        ``human_positive`` = the auditor rejected the content.
        """
        sql = """
            SELECT
                model_positive,
                human_positive,
                COUNT(*) AS count
            FROM mlops_confusion
            WHERE decided_at >= $1
            GROUP BY model_positive, human_positive
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, since)
        cells = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
        for row in rows:
            mp, hp, n = (
                row["model_positive"],
                row["human_positive"],
                row["count"],
            )
            if mp and hp:
                cells["tp"] += n
            elif mp and not hp:
                cells["fp"] += n
            elif (not mp) and (not hp):
                cells["tn"] += n
            else:
                cells["fn"] += n
        return cells
