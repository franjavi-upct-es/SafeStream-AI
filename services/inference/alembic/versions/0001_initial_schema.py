"""initial schema

Mirrors what ``infrastructure/postgres/init.sql`` used to do on a clean
volume: events, predictions, audits, plus the mlops_confusion view.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-04-26 22:00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgcrypto provides gen_random_uuid().
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id       TEXT,
            modality        TEXT NOT NULL CHECK (modality IN ('text', 'image')),
            content         TEXT,
            content_uri     TEXT,
            metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
            ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_ingested_at ON events (ingested_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_source_id ON events (source_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS predictions (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id                UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            model_name              TEXT NOT NULL,
            model_version           TEXT NOT NULL,
            scores                  JSONB NOT NULL,
            verdict                 TEXT NOT NULL CHECK (verdict IN ('safe', 'review', 'block')),
            inference_latency_ms    INTEGER NOT NULL CHECK (inference_latency_ms >= 0),
            predicted_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_predictions_event_id ON predictions (event_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_predictions_predicted_at ON predictions (predicted_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_predictions_verdict ON predictions (verdict)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audits (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id        UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            auditor_id      TEXT NOT NULL,
            decision        TEXT NOT NULL CHECK (decision IN ('approved', 'rejected', 'escalated')),
            notes           TEXT,
            decided_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audits_event_id ON audits (event_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audits_decided_at ON audits (decided_at DESC)"
    )

    op.execute(
        """
        CREATE OR REPLACE VIEW mlops_confusion AS
        SELECT
            p.event_id,
            p.predicted_at,
            a.decided_at,
            p.verdict                                     AS model_verdict,
            a.decision                                    AS human_decision,
            (p.verdict IN ('review', 'block'))            AS model_positive,
            (a.decision = 'rejected')                     AS human_positive
        FROM predictions p
        JOIN audits a ON a.event_id = p.event_id
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS mlops_confusion")
    op.execute("DROP TABLE IF EXISTS audits")
    op.execute("DROP TABLE IF EXISTS predictions")
    op.execute("DROP TABLE IF EXISTS events")
    # Don't drop the extension - it may be used by other databases.
