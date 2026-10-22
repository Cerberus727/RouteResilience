import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Evaluation } from "../api/types";
import { Reports } from "../pages/Reports";
import { useWorkspace, WorkspaceProvider } from "../state/workspace";

function ev(failed: string[], affected: string[]): Evaluation {
  return {
    failed,
    network: {
      segments_total: 3, segments_failed: failed.length, weak_components: 1, strong_components: 1 + affected.length,
      baseline_weak_components: 1, baseline_strong_components: 1, main_nodes_baseline: 4, main_nodes: 4 - affected.length,
      cut_off_nodes: affected.length, affected_segments: affected.length, affected_km: 0.1 * affected.length,
      affected_segment_ids: affected, affected_truncated: false,
    },
    sampled: null,
    route: null,
  };
}

const REGION = { region_id: "r1", bbox: [80, 13, 80.01, 13.01], coverage: "full", built_seconds: 0.1, analysis_state: "idle", places: [],
  summary: { segments: 3, nodes: 4, directed_edges: 6, total_km: 1, oneway_segments: 0, weak_components: 1, strong_components: 1, main_scc_nodes: 4, main_scc_share: 1, intersections: 1, dead_ends: 2, highway_classes: {} } };
const ROADS = { type: "FeatureCollection", features: ["1:0", "2:0", "3:0"].map((sid, i) => ({ type: "Feature", id: i, geometry: { type: "LineString", coordinates: [[80, 13], [80.001, 13]] }, properties: { sid, way: i, hw: "residential", name: `Road ${i}`, ow: 0, len: 100 } })) };

/** Fake backend: '3:0' is a spur, so failing '2:0' cuts it off. */
function mockBackend() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });
    if (url.endsWith("/api/geo/regions")) return json(REGION);
    if (url.endsWith("/roads")) return json(ROADS);
    if (url.endsWith("/evaluate")) {
      const body = JSON.parse(String(init?.body));
      if (body.failed.includes("9:9")) return json({ detail: "Unknown segment id(s) for this region: 9:9", code: undefined }, 400);
      return json(ev(body.failed, body.failed.includes("2:0") ? ["3:0"] : []));
    }
    return json({ detail: "unmocked" }, 404);
  });
}

let api_: ReturnType<typeof useWorkspace>;
function Probe() {
  api_ = useWorkspace();
  return <div data-testid="state">{api_.failed.join(",")}|{api_.steps.length}|{api_.regained.join(",")}|{api_.error?.message ?? ""}</div>;
}

describe("workspace simulation state", () => {
  it("records fail / restore steps from backend evaluations and detects regained roads", async () => {
    mockBackend();
    render(<WorkspaceProvider><Probe /></WorkspaceProvider>);
    await act(async () => { await api_.loadRegion(); });
    expect(screen.getByTestId("state").textContent).toBe("|1||");
    await act(async () => { await api_.fail("2:0"); });
    expect(screen.getByTestId("state").textContent).toBe("2:0|2||");
    expect(api_.current?.network.cut_off_nodes).toBe(1);
    await act(async () => { await api_.restore("2:0"); });
    // the spur that had been cut off is reported as regained
    expect(screen.getByTestId("state").textContent).toBe("|3|3:0|");
    expect(api_.steps.map((s) => s.action)).toEqual(["baseline", "fail", "restore"]);
    expect(api_.current?.network.cut_off_nodes).toBe(0);
  });

  it("keeps the previous state when the backend rejects a step", async () => {
    mockBackend();
    render(<WorkspaceProvider><Probe /></WorkspaceProvider>);
    await act(async () => { await api_.loadRegion(); });
    await act(async () => { await api_.fail("9:9"); });
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("|1||Unknown segment id(s) for this region: 9:9"));
  });

  it("ignores closing an already-closed road", async () => {
    const spy = mockBackend();
    render(<WorkspaceProvider><Probe /></WorkspaceProvider>);
    await act(async () => { await api_.loadRegion(); });
    await act(async () => { await api_.fail("1:0"); });
    const calls = spy.mock.calls.length;
    await act(async () => { await api_.fail("1:0"); });
    expect(spy.mock.calls.length).toBe(calls);
    expect(api_.steps.length).toBe(2);
  });
});

describe("Reports page", () => {
  it("shows empty states without inventing runs", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      const body = url.endsWith("/api/runs") ? [] : url.endsWith("/api/experiments") ? [] : {};
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    render(<MemoryRouter><WorkspaceProvider><Reports /></WorkspaceProvider></MemoryRouter>);
    expect(await screen.findByText("No saved runs yet")).toBeInTheDocument();
    expect(screen.getByText(/No unsaved simulation/)).toBeInTheDocument();
  });

  it("shows an error state when runs cannot be listed", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const ok = String(input).endsWith("/api/experiments");
      return new Response(JSON.stringify(ok ? [] : { detail: "disk full", code: "run_error" }), { status: ok ? 200 : 500, headers: { "Content-Type": "application/json" } });
    });
    render(<MemoryRouter><WorkspaceProvider><Reports /></WorkspaceProvider></MemoryRouter>);
    expect(await screen.findByText(/Could not list saved runs/)).toBeInTheDocument();
    expect(screen.getByText("disk full")).toBeInTheDocument();
  });
});
