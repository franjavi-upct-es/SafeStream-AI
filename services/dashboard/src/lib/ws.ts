// services/dashboard/src/lib/ws.ts
import { useEffect, useRef, useState } from "react";

import type { PredictionEvent } from "./types";

export type ConnectionState = "idle" | "connecting" | "open" | "closed";

interface UseEventStreamOptions {
    /** Called for every prediction received. */
    onEvent: (event: PredictionEvent) => void;
    /** Disable the connection entirely (e.g. when the view is unmounted). */
    enabled?: boolean;
    /** Optional API key sent as a query string parameter. */
    apiKey?: string;
}

/**
 * Subscribe to /ws/v1/stream. Reconnects with exponential backoff up to
 * 30 seconds between attempts. Designed to survive idle network cycles
 * (laptops sleeping, transient outages).
 */
export function useEventStream({
    onEvent,
    enabled = true,
    apiKey,
}: UseEventStreamOptions): ConnectionState {
    const [state, setState] = useState<ConnectionState>("idle");
    // Keep onEvent in a ref so changes do not tear down the socket.
    const onEventRef = useRef(onEvent);
    onEventRef.current = onEvent;

    useEffect(() => {
        if (!enabled) {
            setState("idle");
            return;
        }

        let socket: WebSocket | null = null;
        let attempt = 0;
        let reconnectTimer: number | null = null;
        let cancelled = false;

        const connect = () => {
            if (cancelled) return;
            setState("connecting");

            const proto =
                window.location.protocol === "https:" ? "wss:" : "ws:";
            const qs = apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : "";
            const url = `${proto}//${window.location.host}/ws/v1/stream${qs}`;
            socket = new WebSocket(url);

            socket.onopen = () => {
                attempt = 0;
                setState("open");
            };
            socket.onmessage = (msg) => {
                try {
                    const parsed = JSON.parse(msg.data) as PredictionEvent;
                    onEventRef.current(parsed);
                } catch {
                    // Ignore malformed payloads - protocol is JSON-only.
                }
            };
            socket.onerror = () => {
                // onclose will fire next; do nothing here.
            };
            socket.onclose = () => {
                setState("closed");
                if (cancelled) return;
                attempt += 1;
                const delay = Math.min(30_000, 500 * 2 ** attempt);
                reconnectTimer = window.setTimeout(connect, delay);
            };
        };

        connect();

        return () => {
            cancelled = true;
            if (reconnectTimer !== null) clearTimeout(reconnectTimer);
            if (socket) {
                socket.onopen = null;
                socket.onmessage = null;
                socket.onerror = null;
                socket.onclose = null;
                try {
                    socket.close();
                } catch {
                    /* noop */
                }
            }
        };
    }, [enabled, apiKey]);

    return state;
}
