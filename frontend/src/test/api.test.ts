import { describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api/client";

const respond = (status: number, body: unknown) =>
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

describe("api client", () => {
  it("surfaces backend detail and code", async () => {
    respond(409, { detail: "This area is outside every indexed extent.", code: "not_indexed" });
    const err = await api.loadRegion([81, 14, 81.01, 14.01]).catch((e: ApiError) => e) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.code).toBe("not_indexed");
  });

  it("formats FastAPI validation errors", async () => {
    respond(422, { detail: [{ loc: ["body", "failed"], msg: "duplicate segment ids" }] });
    const err = await api.evaluate("r1", ["1:0", "1:0"], null, null).catch((e: ApiError) => e) as ApiError;
    expect(err.message).toBe("failed: duplicate segment ids");
  });

  it("reports an unreachable backend clearly", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const err = await api.health().catch((e: ApiError) => e) as ApiError;
    expect(err.status).toBe(0);
    expect(err.code).toBe("network");
  });

  it("sends origin/destination only when both are set", async () => {
    const spy = respond(200, {});
    await api.evaluate("r1", ["5:0"], [80.2, 13.0], null);
    expect(JSON.parse(spy.mock.calls[0][1]!.body as string)).toEqual({ failed: ["5:0"] });
    await api.evaluate("r1", [], [80.2, 13.0], [80.3, 13.1]);
    expect(JSON.parse(spy.mock.calls[1][1]!.body as string)).toEqual({ failed: [], origin: { lon: 80.2, lat: 13.0 }, destination: { lon: 80.3, lat: 13.1 } });
  });

  it("encodes path parameters", async () => {
    const spy = respond(200, {});
    await api.segment("abc", "123:4/../x");
    expect(spy.mock.calls[0][0]).toBe("/api/geo/regions/abc/segments/123%3A4%2F..%2Fx");
  });
});
