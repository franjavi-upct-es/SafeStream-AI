// services/dashboard/src/views/Triage.tsx
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ScoreBars } from "../components/ScoreBars";
import { VerdictBadge } from "../components/VerdictBadge";
import { api, ApiError } from "../lib/api";
import {
    formatRelative,
    formatScore,
    formatTime,
    shortId,
    topScore,
} from "../lib/format";
import { useLiveEvents } from "../lib/streamContext";
import type {
    AuditDecision,
    EventOut,
    PredictionEvent,
    Verdict,
} from "../lib/types";

const MAX_ROWS = 200;
const AUDITOR_ID = "auditor-local";

const SHORTCUTS: Array<{ key: string; label: string }> = [
    { key: "j / ↓", label: "next" },
    { key: "k / ↑", label: "prev" },
    { key: "a", label: "approve" },
    { key: "r", label: "reject" },
    { key: "e", label: "escalate" },
    { key: "esc", label: "deselect" },
];

const DECISION_KEY: Record<string, AuditDecision> = {
    a: "approved",
    r: "rejected",
    e: "escalated",
};

export function Triage() {
    const [rows, setRows] = useState<EventOut[]>([]);
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [decisions, setDecisions] = useState<Record<string, AuditDecision>>(
        {},
    );
    const [error, setError] = useState<string | null>(null);
    const [loadingInitial, setLoadingInitial] = useState(true);
    const rowRefs = useRef<Map<string, HTMLTableRowElement>>(new Map());

    // Initial paint: pull recent review/block events from the API.
    useEffect(() => {
        let cancelled = false;
        api.recentEvents({ verdicts: ["review", "block"], limit: 100 })
            .then((response) => {
                if (cancelled) return;
                setRows(response.events);
                setLoadingInitial(false);
            })
            .catch((err) => {
                if (cancelled) return;
                setError(err.message ?? "Failed to load recent events.");
                setLoadingInitial(false);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    // Live updates from the WebSocket. Only review/block reach the queue;
    // safe events flow past silently.
    const onLive = useCallback((event: PredictionEvent) => {
        if (event.verdict === "safe") return;
        setRows((current) => {
            // Skip if we already have it (the worker can republish on retries).
            if (current.some((r) => r.event_id === event.event_id))
                return current;
            const next: EventOut = {
                event_id: event.event_id,
                source_id: event.source_id,
                modality: event.modality,
                content: null, // not in the WS payload; loaded on selection
                content_uri: null,
                ingested_at: event.predicted_at,
                verdict: event.verdict,
                scores: event.scores,
                model_name: event.model.name,
                model_version: event.model.version,
                inference_latency_ms: event.inference_latency_ms,
                predicted_at: event.predicted_at,
            };
            return [next, ...current].slice(0, MAX_ROWS);
        });
    }, []);
    useLiveEvents(onLive);

    // Keyboard navigation + audit shortcuts.
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            // Don't hijack typing in inputs.
            const tag = (e.target as HTMLElement)?.tagName;
            if (tag === "INPUT" || tag === "TEXTAREA") return;

            if (e.key === "Escape") {
                setSelectedId(null);
                return;
            }

            // Navigation
            if (e.key === "j" || e.key === "ArrowDown") {
                e.preventDefault();
                setSelectedId((current) => stepSelection(current, rows, +1));
                return;
            }
            if (e.key === "k" || e.key === "ArrowUp") {
                e.preventDefault();
                setSelectedId((current) => stepSelection(current, rows, -1));
                return;
            }

            // Audit decisions
            const decision = DECISION_KEY[e.key.toLowerCase()];
            if (decision && selectedId) {
                e.preventDefault();
                void submitDecision(selectedId, decision);
            }
        };

        async function submitDecision(
            eventId: string,
            decision: AuditDecision,
        ) {
            try {
                await api.createAudit({
                    event_id: eventId,
                    auditor_id: AUDITOR_ID,
                    decision,
                });
                setDecisions((d) => ({ ...d, [eventId]: decision }));
                // Auto-advance to the next un-decided row.
                setSelectedId((current) => stepSelection(current, rows, +1));
            } catch (err) {
                const message =
                    err instanceof ApiError ? err.message : "Audit failed.";
                setError(message);
            }
        }

        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [rows, selectedId]);

    // Scroll the selected row into view as the user navigates.
    useEffect(() => {
        if (!selectedId) return;
        const el = rowRefs.current.get(selectedId);
        el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }, [selectedId]);

    const selected = useMemo(
        () => rows.find((r) => r.event_id === selectedId) ?? null,
        [rows, selectedId],
    );

    return (
        <div className="h-full flex">
            {/* ---------- Queue ---------- */}
            <section className="flex-1 min-w-0 flex flex-col border-r border-rule bg-ink">
                <header className="px-8 pt-8 pb-4 border-b border-rule">
                    <div className="label mb-2">01 // triage queue</div>
                    <h1 className="font-display text-3xl tracking-wider mb-1">
                        REVIEW FEED
                    </h1>
                    <p className="text-fg-dim text-sm max-w-2xl">
                        Ambiguous and high-risk events. Safe verdicts are
                        auto-approved upstream; everything that reaches this
                        queue needs a human call.
                    </p>
                </header>

                <div className="px-8 py-3 border-b border-rule flex items-center gap-3 font-mono text-[10px] uppercase tracking-widest text-fg-muted">
                    {SHORTCUTS.map((s) => (
                        <span key={s.key} className="flex items-center gap-1.5">
                            <span className="kbd">{s.key}</span>
                            <span>{s.label}</span>
                        </span>
                    ))}
                    <span className="ml-auto text-fg-dim">
                        queue:{" "}
                        <span className="text-fg tabular-nums">
                            {rows.length}
                        </span>{" "}
                        / {MAX_ROWS}
                    </span>
                </div>

                {error && (
                    <div className="px-8 py-2 text-block text-xs font-mono border-b border-block/40 bg-block/5">
                        {error}
                    </div>
                )}

                <div className="flex-1 overflow-auto">
                    {loadingInitial && (
                        <div className="p-8 text-fg-muted font-mono text-xs">
                            Loading recent events…
                        </div>
                    )}
                    {!loadingInitial && rows.length === 0 && (
                        <div className="p-8 text-fg-muted font-mono text-xs">
                            No events yet. Start the producer and wait for
                            review-tier traffic.
                        </div>
                    )}
                    {rows.length > 0 && (
                        <table className="w-full text-sm">
                            <thead className="sticky top-0 bg-panel border-b border-rule z-10">
                                <tr className="text-left">
                                    <Th>v</Th>
                                    <Th>top</Th>
                                    <Th>id</Th>
                                    <Th className="w-full">content</Th>
                                    <Th>seen</Th>
                                    <Th>aud</Th>
                                </tr>
                            </thead>
                            <tbody>
                                {rows.map((row) => {
                                    const isSelected =
                                        row.event_id === selectedId;
                                    const decision = decisions[row.event_id];
                                    return (
                                        <tr
                                            key={row.event_id}
                                            ref={(el) => {
                                                if (el)
                                                    rowRefs.current.set(
                                                        row.event_id,
                                                        el,
                                                    );
                                                else
                                                    rowRefs.current.delete(
                                                        row.event_id,
                                                    );
                                            }}
                                            onClick={() =>
                                                setSelectedId(row.event_id)
                                            }
                                            className={[
                                                "border-b border-rule/60 cursor-pointer transition-colors",
                                                isSelected
                                                    ? "bg-panel-2"
                                                    : "hover:bg-panel-2/60",
                                            ].join(" ")}
                                        >
                                            <td className="px-4 py-2 align-middle">
                                                <div className="flex items-center gap-2">
                                                    <span
                                                        className={[
                                                            "w-0.5 h-5",
                                                            isSelected
                                                                ? "bg-accent"
                                                                : "bg-transparent",
                                                        ].join(" ")}
                                                        aria-hidden
                                                    />
                                                    <VerdictBadge
                                                        verdict={row.verdict}
                                                    />
                                                </div>
                                            </td>
                                            <td className="px-4 py-2 font-mono text-fg-dim">
                                                {formatScore(
                                                    topScore(row.scores),
                                                )}
                                            </td>
                                            <td className="px-4 py-2 font-mono text-fg-muted">
                                                {shortId(row.event_id)}
                                            </td>
                                            <td className="px-4 py-2 text-fg-dim truncate max-w-[1px]">
                                                <div className="truncate">
                                                    {row.content ?? (
                                                        <span className="text-fg-muted italic">
                                                            {row.content_uri ??
                                                                "—"}
                                                        </span>
                                                    )}
                                                </div>
                                            </td>
                                            <td className="px-4 py-2 font-mono text-xs text-fg-muted">
                                                {formatRelative(
                                                    row.predicted_at ??
                                                        row.ingested_at,
                                                )}
                                            </td>
                                            <td className="px-4 py-2">
                                                <DecisionTag
                                                    decision={decision}
                                                />
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    )}
                </div>
            </section>

            {/* ---------- Detail panel ---------- */}
            <aside className="w-[420px] flex flex-col bg-panel">
                <DetailPanel
                    event={selected}
                    decision={
                        selected ? decisions[selected.event_id] : undefined
                    }
                />
            </aside>
        </div>
    );
}

function stepSelection(
    current: string | null,
    rows: EventOut[],
    delta: 1 | -1,
): string | null {
    if (rows.length === 0) return null;
    const index = rows.findIndex((r) => r.event_id === current);
    if (index === -1) return rows[0].event_id;
    const next = Math.max(0, Math.min(rows.length - 1, index + delta));
    return rows[next].event_id;
}

function DetailPanel({
    event,
    decision,
}: {
    event: EventOut | null;
    decision?: AuditDecision;
}) {
    if (!event) {
        return (
            <div className="flex-1 flex items-center justify-center px-8 text-center">
                <div className="text-fg-muted font-mono text-xs leading-loose">
                    Select a row to inspect.
                    <br />
                    <span className="kbd mt-2 inline-block">j</span>{" "}
                    <span className="kbd">k</span> to navigate.
                </div>
            </div>
        );
    }

    return (
        <>
            <header className="px-6 py-5 border-b border-rule">
                <div className="flex items-center gap-3 mb-3">
                    <VerdictBadge verdict={event.verdict} />
                    <span className="font-mono text-[10px] text-fg-muted uppercase tracking-widest">
                        {event.modality}
                    </span>
                    {decision && (
                        <span className="ml-auto">
                            <DecisionTag decision={decision} />
                        </span>
                    )}
                </div>
                <div className="font-mono text-xs text-fg-dim break-all">
                    {event.event_id}
                </div>
            </header>

            <div className="flex-1 overflow-auto p-6 space-y-6">
                <Section title="content">
                    <pre className="font-mono text-sm whitespace-pre-wrap leading-relaxed text-fg">
                        {event.content ?? event.content_uri ?? "—"}
                    </pre>
                </Section>

                <Section title="scores">
                    <ScoreBars scores={event.scores} />
                </Section>

                <Section title="metadata">
                    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 font-mono text-xs">
                        <Meta label="source" value={event.source_id ?? "—"} />
                        <Meta
                            label="model"
                            value={
                                event.model_name
                                    ? `${event.model_name}@${event.model_version}`
                                    : "—"
                            }
                        />
                        <Meta
                            label="latency"
                            value={
                                event.inference_latency_ms !== null &&
                                event.inference_latency_ms !== undefined
                                    ? `${event.inference_latency_ms} ms`
                                    : "—"
                            }
                        />
                        <Meta
                            label="ingested"
                            value={formatTime(event.ingested_at)}
                        />
                        <Meta
                            label="predicted"
                            value={formatTime(event.predicted_at)}
                        />
                    </dl>
                </Section>
            </div>

            <footer className="border-t border-rule p-4 grid grid-cols-3 gap-2">
                <DecisionButton
                    decision="approved"
                    disabled={decision === "approved"}
                />
                <DecisionButton
                    decision="escalated"
                    disabled={decision === "escalated"}
                />
                <DecisionButton
                    decision="rejected"
                    disabled={decision === "rejected"}
                />
            </footer>
        </>
    );
}

function DecisionButton({
    decision,
    disabled,
}: {
    decision: AuditDecision;
    disabled: boolean;
}) {
    const styles: Record<AuditDecision, string> = {
        approved: "border-safe/50 text-safe hover:bg-safe/10",
        escalated: "border-escalate/50 text-escalate hover:bg-escalate/10",
        rejected: "border-block/50 text-block hover:bg-block/10",
    };
    const keyHint: Record<AuditDecision, string> = {
        approved: "a",
        escalated: "e",
        rejected: "r",
    };
    return (
        <button
            type="button"
            disabled={disabled}
            className={[
                "px-3 py-2 border bg-panel-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed",
                "font-mono text-xs uppercase tracking-widest flex items-center justify-center gap-2",
                styles[decision],
            ].join(" ")}
        >
            <span>{decision}</span>
            <span className="kbd">{keyHint[decision]}</span>
        </button>
    );
}

function Section({
    title,
    children,
}: {
    title: string;
    children: React.ReactNode;
}) {
    return (
        <section>
            <div className="label mb-2">{title}</div>
            {children}
        </section>
    );
}

function Meta({ label, value }: { label: string; value: string }) {
    return (
        <>
            <dt className="text-fg-muted uppercase tracking-widest text-[10px]">
                {label}
            </dt>
            <dd className="text-fg-dim truncate">{value}</dd>
        </>
    );
}

function DecisionTag({ decision }: { decision?: AuditDecision }) {
    if (!decision)
        return <span className="text-fg-muted font-mono text-[10px]">—</span>;
    const styles: Record<Verdict | AuditDecision, string> = {
        approved: "text-safe border-safe/40 bg-safe/5",
        escalated: "text-escalate border-escalate/40 bg-escalate/5",
        rejected: "text-block border-block/40 bg-block/5",
        // unused but TS wants exhaustiveness if Verdict gets passed in:
        safe: "",
        review: "",
        block: "",
    };
    return (
        <span
            className={`font-mono text-[10px] uppercase tracking-widest px-1.5 py-0.5 border ${styles[decision]}`}
        >
            {decision}
        </span>
    );
}

function Th({
    children,
    className = "",
}: {
    children: React.ReactNode;
    className?: string;
}) {
    return (
        <th className={`label font-mono px-4 py-2 text-left ${className}`}>
            {children}
        </th>
    );
}
