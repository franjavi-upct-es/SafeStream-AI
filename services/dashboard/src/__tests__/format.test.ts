// services/dashboard/src/__tests__/format.test.ts
import { describe, expect, it } from "vitest";

import {
  formatRelative,
  formatScore,
  formatTime,
  shortId,
  topScore,
} from "../lib/format";

describe("formatTime", () => {
  it("returns a placeholder for null/undefined/invalid input", () => {
    expect(formatTime(null)).toBe("—");
    expect(formatTime(undefined)).toBe("—");
    expect(formatTime("not-a-date")).toBe("—");
  });

  it("formats valid ISO strings as HH:MM:SS", () => {
    const result = formatTime("2026-04-26T12:34:56Z");
    // Format: HH:MM:SS in local timezone — assert structure, not value.
    expect(result).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });
});

describe("formatRelative", () => {
  it("returns seconds for very recent times", () => {
    const now = new Date(Date.now() - 5_000).toISOString();
    expect(formatRelative(now)).toMatch(/^\d+s$/);
  });

  it("returns minutes for recent times", () => {
    const past = new Date(Date.now() - 5 * 60_000).toISOString();
    expect(formatRelative(past)).toMatch(/^\d+m$/);
  });

  it("returns hours for older times", () => {
    const past = new Date(Date.now() - 3 * 3_600_000).toISOString();
    expect(formatRelative(past)).toMatch(/^\d+h$/);
  });

  it("returns days for very old times", () => {
    const past = new Date(Date.now() - 5 * 86_400_000).toISOString();
    expect(formatRelative(past)).toMatch(/^\d+d$/);
  });

  it("handles invalid input gracefully", () => {
    expect(formatRelative(null)).toBe("—");
    expect(formatRelative("")).toBe("—");
  });
});

describe("shortId", () => {
  it("trims to first 8 chars", () => {
    expect(shortId("8f2c0b8c-1234-5678-9abc-def012345678")).toBe("8f2c0b8c");
  });
});

describe("topScore", () => {
  it("returns 0 for null", () => {
    expect(topScore(null)).toBe(0);
  });

  it("returns 0 for empty dict", () => {
    expect(topScore({})).toBe(0);
  });

  it("returns the maximum score", () => {
    expect(topScore({ toxic: 0.5, insult: 0.92, obscene: 0.13 })).toBe(0.92);
  });
});

describe("formatScore", () => {
  it("formats to two decimal places", () => {
    expect(formatScore(0.123)).toBe("0.12");
    expect(formatScore(1)).toBe("1.00");
    expect(formatScore(0)).toBe("0.00");
  });
});
