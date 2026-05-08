// services/dashboard/src/__tests__/api.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "../lib/api";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

describe("api.recentEvents", () => {
  it("appends each verdict as a separate query parameter", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ count: 0, events: [] }));

    await api.recentEvents({ verdicts: ["block", "review"], limit: 25 });

    expect(fetchMock).toHaveBeenCalledOnce();
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/api/v1/events/recent?");
    // URLSearchParams encodes each verdict as its own key.
    expect(url).toContain("verdicts=block");
    expect(url).toContain("verdicts=review");
    expect(url).toContain("limit=25");
  });

  it("omits the query string when no params are passed", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ count: 0, events: [] }));
    await api.recentEvents();
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe("/api/v1/events/recent");
  });
});

describe("api.semanticSearch", () => {
  it("posts the body as JSON", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ query: "x", count: 0, results: [] }),
    );

    await api.semanticSearch({
      query: "i hate you",
      verdicts: ["block"],
      min_score: 0.5,
      limit: 10,
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({
      query: "i hate you",
      verdicts: ["block"],
      min_score: 0.5,
      limit: 10,
    });
  });
});

describe("api error handling", () => {
  it("throws ApiError with the server detail on 4xx", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "missing field" }, { status: 422, statusText: "Unprocessable" }),
    );

    await expect(
      api.semanticSearch({ query: "" }),
    ).rejects.toThrow(ApiError);
  });

  it("falls back to status text when body is not JSON", async () => {
    fetchMock.mockResolvedValue(
      new Response("oops", { status: 503, statusText: "Service Unavailable" }),
    );

    await expect(api.recentEvents()).rejects.toMatchObject({
      status: 503,
    });
  });
});

describe("api.confusion", () => {
  it("appends since_minutes when provided", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        since: "2026-04-26T00:00:00Z",
        true_positive: 1,
        false_positive: 0,
        true_negative: 0,
        false_negative: 0,
        precision: null,
        recall: null,
      }),
    );

    await api.confusion({ since_minutes: 30 });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("?since_minutes=30");
  });
});
