// services/dashboard/src/lib/format.ts
export function formatTime(iso: string | null | undefined): string {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleTimeString("en-GB", { hour12: false });
}

export function formatRelative(iso: string | null | undefined): string {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    const seconds = Math.floor((Date.now() - d.getTime()) / 1000);
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h`;
    return `${Math.floor(seconds / 86_400)}d`;
}

export function shortId(uuid: string): string {
    return uuid.slice(0, 8);
}

export function topScore(scores: Record<string, number> | null): number {
    if (!scores) return 0;
    const values = Object.values(scores);
    return values.length === 0 ? 0 : Math.max(...values);
}

export function formatScore(value: number): string {
    return value.toFixed(2);
}
