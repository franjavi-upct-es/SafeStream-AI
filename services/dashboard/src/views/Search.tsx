// services/dashboard/src/views/Search.tsx
import { FormEvent, useEffect, useRef, useState } from "react";

import { VerdictBadge } from "../components/VerdictBadge";
import { api, ApiError } from "../lib/api";
import { formatRelative, formatScore, shortId } from "../lib/format";
import type { SemanticSearchHit, Verdict } from "../lib/types";

interface SearchState {
    status: "idle" | "loading" | "success" | "error";
    hits: SemanticSearchHit[];
    error: string | null;
    lastQuery: string;
}

const ALL_VERDICTS: Verdict[] = ["block", "review", "safe"];

export function Search() {
    const inputRef = useRef<HTMLInputElement>(null);
    const [query, setQuery] = useState("");
    const [verdicts, setVerdicts] = useState<Verdict[]>(["block", "review"]);
    const [minScore, setMinScore] = useState(0.4);
    const [state, setState] = useState<SearchState>({
        status: "idle",
        hits: [],
        error: null,
        lastQuery: "",
    });

    // Focus the omnibox on mount and on `/`.
    useEffect(() => {
        inputRef.current?.focus();
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "/" && document.activeElement !== inputRef.current) {
                e.preventDefault();
                inputRef.current?.focus();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, []);

    async function onSubmit(e: FormEvent) {
        e.preventDefault();
        const trimmed = query.trim();
        if (!trimmed) return;
        setState((s) => ({ ...s, status: "loading", error: null }));
        try {
            const response = await api.semanticSearch({
                query: trimmed,
                verdicts: verdicts.length > 0 ? verdicts : undefined,
                min_score: minScore,
                limit: 25,
            });
            setState({
                status: "success",
                hits: response.results,
                error: null,
                lastQuery: trimmed,
            });
        } catch (err) {
            const message =
                err instanceof ApiError ? err.message : "Search failed.";
            setState({
                status: "error",
                hits: [],
                error: message,
                lastQuery: trimmed,
            });
        }
    }

    function toggleVerdict(v: Verdict) {
        setVerdicts((current) =>
            current.includes(v)
                ? current.filter((x) => x !== v)
                : [...current, v],
        );
    }

    return (
        <div className="h-full flex flex-col bg-ink">
            <div className="px-8 pt-8 pb-6 border-b border-rule">
                <div className="label mb-2">02 // semantic search</div>
                <h1 className="font-display text-3xl tracking-wider mb-1">
                    OMNIBOX
                </h1>
                <p className="text-fg-dim text-sm max-w-2xl">
                    Cosine search against the embedding store. Surfaces evasion
                    attempts, paraphrased violations, and coordinated patterns
                    that lexical filters miss.
                </p>
            </div>

            <div className="px-8 py-6 border-b border-rule">
                <form onSubmit={onSubmit} className="space-y-4">
                    <div className="flex items-center border border-rule bg-panel">
                        <span className="px-4 py-3 font-mono text-fg-muted select-none border-r border-rule">
                            &gt;
                        </span>
                        <input
                            ref={inputRef}
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="describe the kind of message you are looking for..."
                            className="flex-1 bg-transparent px-4 py-3 outline-none font-mono text-sm placeholder:text-fg-muted"
                            autoComplete="off"
                            spellCheck={false}
                        />
                        <button
                            type="submit"
                            className="px-5 py-3 border-l border-rule font-mono text-xs uppercase tracking-widest text-accent hover:bg-panel-2 transition-colors"
                        >
                            query
                        </button>
                    </div>

                    <div className="flex items-center gap-6 text-xs">
                        <div className="flex items-center gap-2">
                            <span className="label">verdicts</span>
                            {ALL_VERDICTS.map((v) => {
                                const active = verdicts.includes(v);
                                return (
                                    <button
                                        key={v}
                                        type="button"
                                        onClick={() => toggleVerdict(v)}
                                        className={[
                                            "font-mono uppercase text-[10px] tracking-widest px-2 py-1 border transition-colors",
                                            active
                                                ? "border-accent text-fg bg-panel-2"
                                                : "border-rule text-fg-muted hover:text-fg-dim",
                                        ].join(" ")}
                                    >
                                        {v}
                                    </button>
                                );
                            })}
                        </div>
                        <div className="flex items-center gap-3 ml-auto">
                            <span className="label">min score</span>
                            <input
                                type="range"
                                min={0}
                                max={1}
                                step={0.05}
                                value={minScore}
                                onChange={(e) =>
                                    setMinScore(parseFloat(e.target.value))
                                }
                                className="w-32 accent-orange-500"
                            />
                            <span className="font-mono text-xs text-fg w-10 text-right">
                                {minScore.toFixed(2)}
                            </span>
                        </div>
                    </div>
                </form>
            </div>

            <div className="flex-1 overflow-auto">
                {state.status === "idle" && (
                    <EmptyHint>
                        Press <span className="kbd">/</span> to focus the
                        omnibox. Try phrases, not keywords — the embedder
                        matches meaning.
                    </EmptyHint>
                )}
                {state.status === "loading" && (
                    <EmptyHint>Searching the vector store…</EmptyHint>
                )}
                {state.status === "error" && (
                    <EmptyHint tone="error">
                        {state.error ?? "Search failed."}
                    </EmptyHint>
                )}
                {state.status === "success" && state.hits.length === 0 && (
                    <EmptyHint>
                        No matches for{" "}
                        <span className="font-mono text-fg">
                            "{state.lastQuery}"
                        </span>
                        .
                    </EmptyHint>
                )}
                {state.status === "success" && state.hits.length > 0 && (
                    <ResultsTable hits={state.hits} />
                )}
            </div>
        </div>
    );
}

function ResultsTable({ hits }: { hits: SemanticSearchHit[] }) {
    return (
        <table className="w-full text-sm">
            <thead className="sticky top-0 bg-panel border-b border-rule">
                <tr className="text-left">
                    <Th>score</Th>
                    <Th>verdict</Th>
                    <Th>id</Th>
                    <Th className="w-full">snippet</Th>
                    <Th>seen</Th>
                </tr>
            </thead>
            <tbody>
                {hits.map((hit) => (
                    <tr
                        key={hit.event_id}
                        className="border-b border-rule/60 hover:bg-panel-2"
                    >
                        <td className="px-4 py-3 align-top">
                            <span className="font-mono text-fg">
                                {formatScore(hit.score)}
                            </span>
                        </td>
                        <td className="px-4 py-3 align-top">
                            <VerdictBadge verdict={hit.verdict} />
                        </td>
                        <td className="px-4 py-3 align-top font-mono text-fg-dim">
                            {shortId(hit.event_id)}
                        </td>
                        <td className="px-4 py-3 align-top text-fg-dim">
                            {hit.content_snippet ?? (
                                <em className="text-fg-muted">—</em>
                            )}
                        </td>
                        <td className="px-4 py-3 align-top font-mono text-fg-muted text-xs">
                            {formatRelative(hit.predicted_at)}
                        </td>
                    </tr>
                ))}
            </tbody>
        </table>
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

function EmptyHint({
    children,
    tone = "neutral",
}: {
    children: React.ReactNode;
    tone?: "neutral" | "error";
}) {
    return (
        <div className="flex items-center justify-center h-full">
            <div
                className={[
                    "max-w-md text-sm font-mono px-6 py-4 border",
                    tone === "error"
                        ? "text-block border-block/40 bg-block/5"
                        : "text-fg-dim border-rule bg-panel-2",
                ].join(" ")}
            >
                {children}
            </div>
        </div>
    );
}
