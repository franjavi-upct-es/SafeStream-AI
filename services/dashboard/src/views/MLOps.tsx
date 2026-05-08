// services/dashboard/src/views/MLOps.tsx
import { useEffect, useMemo, useState } from "react";
import {
    CartesianGrid,
    Line,
    LineChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";

import { api } from "../lib/api";
import type {
    ConfusionMatrixResponse,
    TimeseriesResponse,
    Verdict,
} from "../lib/types";

const RANGES = [
    { label: "15m", minutes: 15 },
    { label: "1h", minutes: 60 },
    { label: "6h", minutes: 360 },
    { label: "24h", minutes: 1440 },
] as const;

const VERDICT_COLORS: Record<Verdict, string> = {
    safe: "var(--safe)",
    review: "var(--review)",
    block: "var(--block)",
};

interface ChartPoint {
    bucket: string;
    safe: number;
    review: number;
    block: number;
}

export function MLOps() {
    const [minutes, setMinutes] = useState<number>(60);
    const [series, setSeries] = useState<TimeseriesResponse | null>(null);
    const [confusion, setConfusion] = useState<ConfusionMatrixResponse | null>(
        null,
    );
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError(null);

        Promise.all([
            api.timeseries({
                since_minutes: minutes,
                bucket_seconds: bucketFor(minutes),
            }),
            api.confusion({ since_minutes: minutes }),
        ])
            .then(([t, c]) => {
                if (cancelled) return;
                setSeries(t);
                setConfusion(c);
            })
            .catch((err) => {
                if (cancelled) return;
                setError(err.message ?? "Failed to load metrics.");
            })
            .finally(() => !cancelled && setLoading(false));

        // Refresh every 15 seconds while the view is mounted.
        const id = window.setInterval(() => {
            api.timeseries({
                since_minutes: minutes,
                bucket_seconds: bucketFor(minutes),
            })
                .then((t) => !cancelled && setSeries(t))
                .catch(() => undefined);
            api.confusion({ since_minutes: minutes })
                .then((c) => !cancelled && setConfusion(c))
                .catch(() => undefined);
        }, 15_000);

        return () => {
            cancelled = true;
            window.clearInterval(id);
        };
    }, [minutes]);

    const chartData = useMemo<ChartPoint[]>(() => {
        if (!series) return [];
        const buckets = new Map<string, ChartPoint>();
        for (const point of series.points) {
            const existing = buckets.get(point.bucket) ?? {
                bucket: point.bucket,
                safe: 0,
                review: 0,
                block: 0,
            };
            existing[point.verdict] = point.count;
            buckets.set(point.bucket, existing);
        }
        return Array.from(buckets.values()).sort((a, b) =>
            a.bucket.localeCompare(b.bucket),
        );
    }, [series]);

    return (
        <div className="h-full overflow-auto bg-ink">
            <div className="px-8 pt-8 pb-6 border-b border-rule">
                <div className="label mb-2">03 // mlops analytics</div>
                <h1 className="font-display text-3xl tracking-wider mb-1">
                    OBSERVABILITY
                </h1>
                <p className="text-fg-dim text-sm max-w-2xl">
                    Throughput by verdict and the live confusion matrix vs.
                    human audits. Significant drift in false positive / false
                    negative rates is the earliest signal that a retraining
                    cycle is due.
                </p>
            </div>

            <div className="px-8 py-4 border-b border-rule flex items-center gap-2">
                <span className="label mr-2">range</span>
                {RANGES.map((r) => (
                    <button
                        key={r.label}
                        onClick={() => setMinutes(r.minutes)}
                        className={[
                            "font-mono uppercase text-[10px] tracking-widest px-2.5 py-1 border transition-colors",
                            minutes === r.minutes
                                ? "border-accent text-fg bg-panel-2"
                                : "border-rule text-fg-muted hover:text-fg-dim",
                        ].join(" ")}
                    >
                        {r.label}
                    </button>
                ))}
                {loading && <span className="label ml-4">loading…</span>}
                {error && (
                    <span className="text-block text-xs ml-4">{error}</span>
                )}
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 p-8">
                <section className="xl:col-span-2 surface">
                    <div className="px-5 py-3 border-b border-rule flex items-center justify-between">
                        <span className="label">
                            events / verdict over time
                        </span>
                        <Legend />
                    </div>
                    <div className="h-72 p-4">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart
                                data={chartData}
                                margin={{
                                    top: 8,
                                    right: 8,
                                    bottom: 0,
                                    left: -16,
                                }}
                            >
                                <CartesianGrid
                                    stroke="var(--rule)"
                                    strokeDasharray="2 4"
                                    vertical={false}
                                />
                                <XAxis
                                    dataKey="bucket"
                                    stroke="var(--fg-muted)"
                                    tick={{
                                        fontSize: 10,
                                        fontFamily: "JetBrains Mono",
                                    }}
                                    tickFormatter={(v) =>
                                        formatTick(v, minutes)
                                    }
                                />
                                <YAxis
                                    stroke="var(--fg-muted)"
                                    tick={{
                                        fontSize: 10,
                                        fontFamily: "JetBrains Mono",
                                    }}
                                    allowDecimals={false}
                                />
                                <Tooltip
                                    contentStyle={{
                                        background: "var(--panel)",
                                        border: "1px solid var(--rule)",
                                        fontFamily: "JetBrains Mono",
                                        fontSize: 11,
                                    }}
                                    labelFormatter={(v) =>
                                        formatTooltipLabel(v as string)
                                    }
                                />
                                <Line
                                    type="monotone"
                                    dataKey="block"
                                    stroke={VERDICT_COLORS.block}
                                    strokeWidth={1.5}
                                    dot={false}
                                />
                                <Line
                                    type="monotone"
                                    dataKey="review"
                                    stroke={VERDICT_COLORS.review}
                                    strokeWidth={1.5}
                                    dot={false}
                                />
                                <Line
                                    type="monotone"
                                    dataKey="safe"
                                    stroke={VERDICT_COLORS.safe}
                                    strokeWidth={1.5}
                                    dot={false}
                                />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </section>

                <section className="surface">
                    <div className="px-5 py-3 border-b border-rule">
                        <span className="label">confusion matrix</span>
                    </div>
                    <ConfusionGrid data={confusion} />
                </section>
            </div>
        </div>
    );
}

function Legend() {
    return (
        <div className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-widest">
            {(["block", "review", "safe"] as Verdict[]).map((v) => (
                <span key={v} className="flex items-center gap-1.5 text-fg-dim">
                    <span
                        className="w-2 h-2"
                        style={{ background: VERDICT_COLORS[v] }}
                        aria-hidden
                    />
                    {v}
                </span>
            ))}
        </div>
    );
}

function ConfusionGrid({ data }: { data: ConfusionMatrixResponse | null }) {
    if (!data) {
        return (
            <div className="p-6 text-fg-muted text-xs font-mono">
                No data yet.
            </div>
        );
    }
    const total =
        data.true_positive +
        data.false_positive +
        data.true_negative +
        data.false_negative;

    return (
        <div className="p-5 space-y-5">
            <div className="grid grid-cols-2 gap-px bg-rule border border-rule">
                <Cell
                    label="True positive"
                    value={data.true_positive}
                    tone="block"
                    total={total}
                />
                <Cell
                    label="False positive"
                    value={data.false_positive}
                    tone="review"
                    total={total}
                />
                <Cell
                    label="False negative"
                    value={data.false_negative}
                    tone="review"
                    total={total}
                />
                <Cell
                    label="True negative"
                    value={data.true_negative}
                    tone="safe"
                    total={total}
                />
            </div>

            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 font-mono text-xs">
                <Stat name="precision" value={data.precision} />
                <Stat name="recall" value={data.recall} />
                <Stat
                    name="audited"
                    value={total === 0 ? null : total}
                    format={(v) => v.toFixed(0)}
                />
                <Stat
                    name="window"
                    value={null}
                    render={
                        <span className="text-fg-dim">
                            since{" "}
                            <span className="text-fg">
                                {new Date(data.since).toLocaleTimeString(
                                    "en-GB",
                                    {
                                        hour12: false,
                                    },
                                )}
                            </span>
                        </span>
                    }
                />
            </dl>
        </div>
    );
}

function Cell({
    label,
    value,
    tone,
    total,
}: {
    label: string;
    value: number;
    tone: Verdict;
    total: number;
}) {
    const pct = total === 0 ? 0 : (value / total) * 100;
    return (
        <div className="bg-panel p-4">
            <div className="label mb-2">{label}</div>
            <div className="flex items-baseline gap-2">
                <span
                    className="font-display text-3xl tracking-wider"
                    style={{ color: VERDICT_COLORS[tone] }}
                >
                    {value}
                </span>
                <span className="font-mono text-fg-muted text-xs">
                    {pct.toFixed(1)}%
                </span>
            </div>
        </div>
    );
}

function Stat({
    name,
    value,
    format = (v: number) => v.toFixed(3),
    render,
}: {
    name: string;
    value: number | null;
    format?: (v: number) => string;
    render?: React.ReactNode;
}) {
    return (
        <div className="flex items-center justify-between border-b border-rule/60 pb-1">
            <dt className="label">{name}</dt>
            <dd>
                {render ??
                    (value === null ? (
                        <span className="text-fg-muted">—</span>
                    ) : (
                        <span className="text-fg">{format(value)}</span>
                    ))}
            </dd>
        </div>
    );
}

function bucketFor(minutes: number): number {
    if (minutes <= 15) return 30;
    if (minutes <= 60) return 60;
    if (minutes <= 360) return 300;
    return 1800;
}

function formatTick(iso: string, minutes: number): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    if (minutes <= 60) {
        return d.toLocaleTimeString("en-GB", {
            hour12: false,
            hour: "2-digit",
            minute: "2-digit",
        });
    }
    return d.toLocaleString("en-GB", {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        day: "2-digit",
        month: "short",
    });
}

function formatTooltipLabel(iso: string): string {
    const d = new Date(iso);
    return Number.isNaN(d.getTime())
        ? iso
        : d.toISOString().replace("T", " ").slice(0, 19);
}
