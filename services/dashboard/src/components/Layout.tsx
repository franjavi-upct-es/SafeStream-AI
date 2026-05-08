// services/dashboard/src/components/Layout.tsx
import { NavLink, Outlet } from "react-router-dom";
import { useCallback, useState } from "react";

import { useEventStream } from "../lib/ws";
import type { PredictionEvent } from "../lib/types";
import { StatusBar } from "./StatusBar";
import { LiveStreamContext } from "../lib/streamContext";

const NAV_ITEMS = [
    { to: "/", label: "Triage", code: "01", end: true },
    { to: "/search", label: "Semantic", code: "02", end: false },
    { to: "/mlops", label: "MLOps", code: "03", end: false },
] as const;

/**
 * Single subscriber to the WebSocket lives at the layout level so all three
 * views observe the same stream. Each view registers a listener through
 * ``LiveStreamContext`` and gets the events it cares about.
 */
export function Layout() {
    const [received, setReceived] = useState(0);
    const [listeners] = useState(() => new Set<(e: PredictionEvent) => void>());

    const handleEvent = useCallback(
        (event: PredictionEvent) => {
            setReceived((n) => n + 1);
            listeners.forEach((listener) => {
                try {
                    listener(event);
                } catch {
                    /* one bad listener should not break the others */
                }
            });
        },
        [listeners],
    );

    const state = useEventStream({ onEvent: handleEvent });

    const subscribe = useCallback(
        (listener: (e: PredictionEvent) => void) => {
            listeners.add(listener);
            return () => listeners.delete(listener);
        },
        [listeners],
    );

    return (
        <LiveStreamContext.Provider value={{ subscribe }}>
            <div className="h-full flex flex-col">
                <StatusBar state={state} eventsReceived={received} />

                <div className="flex-1 flex min-h-0">
                    <aside className="w-48 border-r border-rule bg-panel flex flex-col">
                        <div className="px-5 py-4 border-b border-rule">
                            <div className="label">view</div>
                        </div>
                        <nav className="flex-1 py-2">
                            {NAV_ITEMS.map((item) => (
                                <NavLink
                                    key={item.to}
                                    to={item.to}
                                    end={item.end}
                                    className={({ isActive }) =>
                                        [
                                            "flex items-baseline gap-3 px-5 py-2.5 border-l-2 transition-colors",
                                            isActive
                                                ? "border-accent bg-panel-2 text-fg"
                                                : "border-transparent text-fg-dim hover:text-fg hover:bg-panel-2",
                                        ].join(" ")
                                    }
                                >
                                    <span className="font-mono text-[10px] text-fg-muted">
                                        {item.code}
                                    </span>
                                    <span className="font-display text-sm tracking-wider uppercase">
                                        {item.label}
                                    </span>
                                </NavLink>
                            ))}
                        </nav>

                        <div className="px-5 py-3 border-t border-rule font-mono text-[10px] text-fg-muted leading-relaxed">
                            <div>SAFESTREAM</div>
                            <div>BUILD 0.4.0</div>
                        </div>
                    </aside>

                    <main className="flex-1 min-w-0 overflow-hidden">
                        <Outlet />
                    </main>
                </div>
            </div>
        </LiveStreamContext.Provider>
    );
}
