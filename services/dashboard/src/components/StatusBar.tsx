// services/dashboard/src/components/StatusBar.tsx
import type { ConnectionState } from "../lib/ws";

interface Props {
    state: ConnectionState;
    eventsReceived: number;
}

const STATE_DOT: Record<ConnectionState, string> = {
    idle: "bg-fg-muted",
    connecting: "bg-review animate-pulse",
    open: "bg-safe",
    closed: "bg-block animate-pulse",
};

const STATE_LABEL: Record<ConnectionState, string> = {
    idle: "OFFLINE",
    connecting: "CONNECTING",
    open: "LIVE",
    closed: "RECONNECTING",
};

export function StatusBar({ state, eventsReceived }: Props) {
    return (
        <header className="h-12 border-b border-rule bg-panel flex items-center justify-between px-6 select-none">
            <div className="flex items-center gap-6">
                <div className="font-display text-base tracking-widest leading-none">
                    SAFE<span className="text-accent">/</span>STREAM
                </div>
                <div className="label">audit console &middot; v1.0</div>
            </div>

            <div className="flex items-center gap-6 font-mono text-[11px] tracking-wider">
                <div className="flex items-center gap-2">
                    <span
                        className={`w-1.5 h-1.5 ${STATE_DOT[state]}`}
                        aria-hidden
                    />
                    <span className="text-fg-dim">{STATE_LABEL[state]}</span>
                </div>
                <div className="text-fg-dim">
                    <span className="text-fg-muted">RX</span>{" "}
                    <span className="text-fg tabular-nums">
                        {eventsReceived}
                    </span>
                </div>
            </div>
        </header>
    );
}
