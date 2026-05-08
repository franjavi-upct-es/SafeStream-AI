// services/dashboard/src/components/ScoreBars.tsx
import { formatScore } from "../lib/format";

interface Props {
    scores: Record<string, number> | null;
}

/**
 * Render every label/score pair as a horizontal bar. The bar colour
 * intensities with the score so the reviewer's eye is drawn to the
 * highest-confidence labels without having to read the numbers.
 */
export function ScoreBars({ scores }: Props) {
    if (!scores || Object.keys(scores).length == 0) {
        return <div className="text-fg-muted text-xs">No scores recorded.</div>;
    }
    const entries = Object.entries(scores).sort((a, b) => b[1] - a[1]);

    return (
        <div className="space-y-1.5">
            {entries.map(([label, value]) => (
                <div key={label} className="flex items-center gap-3">
                    <div className="font-mono text-[11pt] uppercase tracking-wider text-fg-dim w-32 truncate">
                        {label.replace(/_/g, " ")}
                    </div>
                    <div className="relative flex-1 h-1.5 bg-panel-2">
                        <div
                            className="absolute inset-y-0 left-0"
                            style={{
                                width: `${Math.min(100, value * 100)}%`,
                                background: barColor(value),
                            }}
                        />
                    </div>
                    <div className="font-mono text-[11px] text-fg w-10 text-right">
                        {formatScore(value)}
                    </div>
                </div>
            ))}
        </div>
    );
}

function barColor(value: number): string {
    if (value >= 0.8) return "var(--block)";
    if (value >= 0.4) return "var(--review)";
    return "var(--safe)";
}
