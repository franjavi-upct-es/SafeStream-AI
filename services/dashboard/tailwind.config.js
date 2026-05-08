// services/dashboard/tailwind.config.js
/** @type {import('tailwindcss').Config} */
export default {
    content: ["./index.html", "./src/**/*.{ts,tsx}"],
    theme: {
        extend: {
            colors: {
                // Surfaces ------------------------------------------------------
                ink: "var(--ink)",
                panel: "var(--panel)",
                "panel-2": "var(--panel-2)",
                grid: "var(--grid)",
                rule: "var(--rule)",
                // Text ----------------------------------------------------------
                fg: "var(--fg)",
                "fg-dim": "var(--fg-dim)",
                "fg-muted": "var(--fg-muted)",
                // Verdicts ------------------------------------------------------
                safe: "var(--safe)",
                review: "var(--review)",
                block: "var(--block)",
                escalate: "var(--escalate)",
                accent: "var(--accent)",
            },
            fontFamily: {
                display: ['"Archivo Black"', "Impact", "sans-serif"],
                sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
                mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
            },
            letterSpacing: {
                wider: "0.04em",
                widest: "0.18em",
            },
            borderRadius: {
                // The control-room aesthetic uses sharp edges everywhere.
                none: "0",
            },
        },
    },
    plugins: [],
};
