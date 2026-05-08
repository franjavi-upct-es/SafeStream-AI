// services/dashboard/src/components/VerdictBadge.tsx
import type { Verdict } from "../lib/types";

const STYLES: Record<Verdict, string> = {
    safe: "text-safe border-safe/40 bg-safe/5",
    review: "text-review border-review/40 bg-review/5",
    block: "text-block border-block/50 bg-block/5",
};

interface Props {
    verdict: Verdict | null;
    className?: string;
}

export function VerdictBadge({ verdict, className = "" }: Props) {
    if (!verdict) {
        return (
            <span
                className={`font-mono text-[10px] uppercase tracking-widest px-1.5 py-0.5 border border-rule text-fg-muted ${className}`}
            >
                ---
            </span>
        );
    }
    return (
        <span
            className={`font-mono text-[10px] uppercase tracking-widest px-1.5 py-0.5 border ${STYLES[verdict]} ${className}`}
        >
            {verdict}
        </span>
    );
}
