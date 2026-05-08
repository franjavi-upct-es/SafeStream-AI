// services/dashboard/src/lib/api.ts
import type {
    AuditDecision,
    AuditOut,
    ConfusionMatrixResponse,
    EventOut,
    RecentEventsResponse,
    SemanticSearchResponse,
    TimeseriesResponse,
    Verdict,
} from "./types";

// All requests go through the nginx proxy at /api in production and
// through the Vite dev server's /api proxy in dev. The trailing slash is
// stripped because every path below starts with one.
const BASE = "/api";

class ApiError extends Error {
    constructor(
        public status: number,
        message: string,
    ) {
        super(message);
    }
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${BASE}${path}`, {
        headers: {
            "Content-Type": "application/json",
            ...(init?.headers || {}),
        },
        ...init,
    });
    if (!response.ok) {
        let message = `${response.status} ${response.statusText}`;
        try {
            const body = await response.json();
            if (body?.detail) message = `${response.status}: ${body.detail}`;
        } catch {
            /* non-JSON body, ignore */
        }
        throw new ApiError(response.status, message);
    }
    return response.json() as Promise<T>;
}

export const api = {
    // Triage feed -----------------------------------------------------------
    recentEvents(params: { verdicts?: Verdict[]; limit?: number } = {}) {
        const search = new URLSearchParams();
        (params.verdicts ?? []).forEach((v) => search.append("verdicts", v));
        if (params.limit !== undefined)
            search.set("limit", String(params.limit));
        const qs = search.toString();
        return jsonFetch<RecentEventsResponse>(
            `/v1/events/recent${qs ? `?${qs}` : ""}`,
        );
    },
    getEvent(eventId: string) {
        return jsonFetch<EventOut>(`/v1/events/${eventId}`);
    },

    // Audits ----------------------------------------------------------------
    createAudit(input: {
        event_id: string;
        auditor_id: string;
        decision: AuditDecision;
        notes?: string;
    }) {
        return jsonFetch<AuditOut>("/v1/audits", {
            method: "POST",
            body: JSON.stringify(input),
        });
    },

    // Semantic search -------------------------------------------------------
    semanticSearch(input: {
        query: string;
        limit?: number;
        verdicts?: Verdict[];
        min_score?: number;
    }) {
        return jsonFetch<SemanticSearchResponse>("/v1/search/semantic", {
            method: "POST",
            body: JSON.stringify(input),
        });
    },

    // Metrics ---------------------------------------------------------------
    timeseries(
        params: { since_minutes?: number; bucket_seconds?: number } = {},
    ) {
        const search = new URLSearchParams();
        if (params.since_minutes !== undefined) {
            search.set("since_minutes", String(params.since_minutes));
        }
        if (params.bucket_seconds !== undefined) {
            search.set("bucket_seconds", String(params.bucket_seconds));
        }
        const qs = search.toString();
        return jsonFetch<TimeseriesResponse>(
            `/v1/metrics/timeseries${qs ? `?${qs}` : ""}`,
        );
    },
    confusion(params: { since_minutes?: number } = {}) {
        const qs =
            params.since_minutes !== undefined
                ? `?since_minutes=${params.since_minutes}`
                : "";
        return jsonFetch<ConfusionMatrixResponse>(`/v1/metrics/confusion${qs}`);
    },
};

export { ApiError };
