// services/dashboard/src/lib/streamContext.ts
import { createContext, useContext, useEffect } from "react";

import type { PredictionEvent } from "./types";

interface StreamContextValue {
    subscribe: (listener: (e: PredictionEvent) => void) => () => void;
}

export const LiveStreamContext = createContext<StreamContextValue>({
    subscribe: () => () => {},
});

/** Convenience hook so views don't have to manage subscribe/unsubscribe. */
export function useLiveEvents(handler: (event: PredictionEvent) => void) {
    const { subscribe } = useContext(LiveStreamContext);
    useEffect(() => subscribe(handler), [subscribe, handler]);
}
