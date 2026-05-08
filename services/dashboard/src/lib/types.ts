// services/dashboard/src/lib/types.ts
// Mirrors the FastAPI pydantic schemas. Keep in sync with
// services/inference/src/api/schemas.py.

export type Verdict = "safe" | "review" | "block";

export type AuditDecision = "approved" | "rejected" | "escalated";

export interface EventOut {
    event_id: string;
    source_id: string | null;
    modality: "text" | "image";
    content: string | null;
    content_uri: string | null;
    ingested_at: string;
    verdict: Verdict | null;
    scores: Record<string, number> | null;
    model_name: string | null;
    model_version: string | null;
    inference_latency_ms: number | null;
    predicted_at: string | null;
}

export interface RecentEventsResponse {
    count: number;
    events: EventOut[];
}

export interface AuditOut {
    id: string;
    event_id: string;
    auditor_id: string;
    decision: AuditDecision;
    notes: string | null;
    decided_at: string;
}

export interface SemanticSearchHit {
    event_id: string;
    score: number;
    verdict: Verdict | null;
    modality: string | null;
    source_id: string | null;
    content_snippet: string | null;
    predicted_at: string | null;
    model_name: string | null;
}

export interface SemanticSearchResponse {
    query: string;
    count: number;
    results: SemanticSearchHit[];
}

export interface TimeseriesPoint {
    bucket: string;
    verdict: Verdict;
    count: number;
}

export interface TimeseriesResponse {
    bucket_seconds: number;
    since: string;
    points: TimeseriesPoint[];
}

export interface ConfusionMatrixResponse {
    since: string;
    true_positive: number;
    false_positive: number;
    true_negative: number;
    false_negative: number;
    precision: number | null;
    recall: number | null;
}

/**
 * Payload pushed onto the WebSocket by the broadcaster - matches the worker's
 * ``_publish_result`` shape verbatim.
 */
export interface PredictionEvent {
    event_id: string;
    source_id: string | null;
    modality: "text" | "image";
    verdict: Verdict;
    scores: Record<string, number>;
    model: { name: string; version: string };
    inference_latency_ms: number;
    predicted_at: string;
}
