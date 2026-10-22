import { Activity, Camera, Crosshair, Expand, Minus, MousePointer2, Navigation, PanelRightClose, PanelRightOpen, Plus, RotateCcw, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { BBox, GeoStatus, LngLat, RoadCollection, SearchHit } from "../api/types";
import { Spinner } from "../components/ui";
import { MapView, type MapHandle, type MapMode } from "../map/MapView";
import { downloadBlob } from "../lib/download";
import { useWorkspace } from "../state/workspace";
import { CriticalTab } from "../workspace/CriticalTab";
import { InspectTab } from "../workspace/InspectTab";
import { LayersCard } from "../workspace/LayersCard";
import { RegionCard } from "../workspace/RegionCard";
import { SearchBox } from "../workspace/SearchBox";
import { SimulateTab } from "../workspace/SimulateTab";

type Tab = "inspect" | "simulate" | "critical";
const FALLBACK_VIEW: BBox = [80.215, 13.02, 80.265, 13.065];

export function MapWorkspace() {
  const ws = useWorkspace();
  const mapRef = useRef<MapHandle>(null);
  const [mode, setMode] = useState<MapMode>("select");
  const [tab, setTab] = useState<Tab>("simulate");
  const [panelOpen, setPanelOpen] = useState(() => typeof window === "undefined" || window.innerWidth >= 1024);
  const [basemapError, setBasemapError] = useState<string | null>(null);
  const [status, setStatus] = useState<GeoStatus | null>(null);
  const [intersections, setIntersections] = useState<GeoJSON.FeatureCollection | null>(null);
  const [matches, setMatches] = useState<string[]>([]);
  const [zoom, setZoom] = useState(13);

  useEffect(() => { api.geoStatus().then(setStatus).catch(() => undefined); }, [ws.region?.region_id]);
  useEffect(() => {
    setIntersections(null);
    if (ws.region) api.intersections(ws.region.region_id).then(setIntersections).catch(() => setIntersections(null));
  }, [ws.region?.region_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const roadsFC = useMemo<RoadCollection | null>(() => (ws.region ? { type: "FeatureCollection", features: [...ws.roads.values()] } : null),
    [ws.roadsVersion]); // eslint-disable-line react-hooks/exhaustive-deps

  const ev = ws.current;
  const affected = useMemo(() => [...(ev?.network.affected_segment_ids ?? []), ...(ev?.route?.unreachable_from_origin_segment_ids ?? [])], [ev]);
  const res = ws.analysis?.state === "done" ? ws.analysis.result : undefined;

  const zoomToSegment = (sid: string) => {
    const f = ws.roads.get(sid);
    if (!f) return;
    const xs = f.geometry.coordinates.map((c) => c[0]), ys = f.geometry.coordinates.map((c) => c[1]);
    mapRef.current?.fitBounds([Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)], { padding: 160 });
  };

  const onPick = (kind: "origin" | "destination", p: LngLat) => {
    if (kind === "origin") {
      ws.setEndpoints(p, ws.destination);
      setMode(ws.destination ? "select" : "destination");
    } else {
      ws.setEndpoints(ws.origin, p);
      setMode("select");
    }
    setTab("simulate");
    setPanelOpen(true);
  };

  const onSearch = (h: SearchHit) => {
    if (h.bbox) mapRef.current?.fitBounds(h.bbox, { padding: 120 });
    else mapRef.current?.flyTo([h.lon, h.lat], 15);
    setMatches(h.segment_ids ?? []);
    if (h.segment_ids?.length) { ws.select({ kind: "segment", sid: h.segment_ids[0] }); setTab("inspect"); setPanelOpen(true); }
  };

  const exportImage = () => {
    const url = mapRef.current?.exportPNG();
    if (!url) { alert("The map image could not be exported: the current basemap does not allow canvas export. Switch the basemap to 'None' or 'Dark' and try again."); return; }
    fetch(url).then((r) => r.blob()).then((b) => downloadBlob(b, `routeresilience_map_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.png`));
  };

  const failedCount = ws.failed.length;
  const route = ev?.route;

  return (
    <div className="relative h-full w-full overflow-hidden">
      <MapView
        ref={mapRef}
        initialBounds={status?.default_region ?? FALLBACK_VIEW}
        mode={mode}
        roads={roadsFC}
        regionBBox={ws.region?.bbox ?? null}
        extents={status?.extents.map((e) => e.bbox) ?? []}
        intersections={intersections}
        criticalNodes={res?.intersections ?? []}
        selectedSid={ws.selection?.kind === "segment" ? ws.selection.sid : null}
        selectedNid={ws.selection?.kind === "node" ? ws.selection.nid : null}
        failed={ws.failed}
        affected={affected}
        regained={ws.regained}
        matches={matches}
        critScores={res?.segment_scores ?? null}
        baselineRoute={route && ws.failed.length ? route.baseline.coords : null}
        currentRoute={route?.current.available ? route.current.coords : null}
        origin={ws.origin}
        destination={ws.destination}
        layers={ws.layers}
        basemap={ws.basemap}
        onSelectSegment={(sid) => { ws.select(sid ? { kind: "segment", sid } : null); if (sid) { setTab("inspect"); setPanelOpen(true); } }}
        onSelectNode={(nid) => { ws.select({ kind: "node", nid }); setTab("inspect"); setPanelOpen(true); }}
        onPick={onPick}
        onBasemapError={setBasemapError}
        onViewChange={(_, z) => setZoom(z)}
      />

      {/* left column */}
      <div className="pointer-events-none absolute left-3 top-3 z-20 flex max-h-[calc(100%-24px)] w-[min(340px,calc(100%-72px))] flex-col gap-2.5">
        <div className="pointer-events-auto"><SearchBox regionId={ws.region?.region_id ?? null} onPick={onSearch} /></div>
        <div className="pointer-events-auto min-h-0 space-y-2.5 overflow-y-auto pb-1">
          <RegionCard getView={() => mapRef.current?.getBounds() ?? null} onLoaded={(b) => mapRef.current?.fitBounds(b, { padding: 30 })} />
          <LayersCard basemapError={basemapError} />
        </div>
      </div>

      {/* map tools */}
      <div className={`absolute top-3 z-20 flex flex-col gap-2 transition-[right] duration-300 ${panelOpen ? "right-[392px] max-lg:right-3" : "right-3"}`}>
        <div className="glass flex flex-col p-1" role="toolbar" aria-label="Interaction mode">
          <ToolBtn active={mode === "select"} label="Select roads" onClick={() => setMode("select")}><MousePointer2 size={15} /></ToolBtn>
          <ToolBtn active={mode === "origin"} label="Set origin A" onClick={() => setMode(mode === "origin" ? "select" : "origin")}><Crosshair size={15} /><span className="absolute bottom-0.5 right-1 text-[8px] font-bold">A</span></ToolBtn>
          <ToolBtn active={mode === "destination"} label="Set destination B" onClick={() => setMode(mode === "destination" ? "select" : "destination")}><Navigation size={15} /><span className="absolute bottom-0.5 right-1 text-[8px] font-bold">B</span></ToolBtn>
        </div>
        <div className="glass flex flex-col p-1" role="toolbar" aria-label="Map view">
          <ToolBtn label="Zoom in" onClick={() => mapRef.current?.zoomBy(1)}><Plus size={15} /></ToolBtn>
          <ToolBtn label="Zoom out" onClick={() => mapRef.current?.zoomBy(-1)}><Minus size={15} /></ToolBtn>
          <ToolBtn label="Fit to loaded network" disabled={!ws.region} onClick={() => ws.region && mapRef.current?.fitBounds(ws.region.bbox, { padding: 30 })}><Expand size={15} /></ToolBtn>
          <ToolBtn label="Reset view (north-up, default area)" onClick={() => { mapRef.current?.resetNorth(); mapRef.current?.fitBounds(status?.default_region ?? FALLBACK_VIEW, { padding: 30 }); setMatches([]); }}><RotateCcw size={15} /></ToolBtn>
          <ToolBtn label="Export map image (PNG)" onClick={exportImage}><Camera size={15} /></ToolBtn>
        </div>
        <div className="glass px-1.5 py-1 text-center font-mono text-[10px] text-slate-400" title="Zoom level">z{zoom.toFixed(1)}</div>
      </div>

      {/* side panel */}
      <aside className={`absolute bottom-3 right-3 top-3 z-30 flex w-[372px] max-w-[calc(100%-24px)] flex-col transition-transform duration-300 max-lg:top-auto max-lg:h-[58%] ${panelOpen ? "translate-x-0" : "translate-x-[calc(100%+24px)]"}`}>
        <div className="glass flex min-h-0 flex-1 flex-col">
          <div className="flex items-center gap-1 border-b border-white/[0.06] px-2 pt-2">
            {(["inspect", "simulate", "critical"] as Tab[]).map((t) => (
              <button key={t} onClick={() => setTab(t)} aria-selected={tab === t} role="tab"
                className={`relative rounded-t-md px-3 pb-2 pt-1 text-xs font-medium capitalize transition-colors ${tab === t ? "text-white" : "text-slate-400 hover:text-slate-200"}`}>
                {t === "simulate" ? `Simulate${failedCount ? ` · ${failedCount}` : ""}` : t}
                {tab === t && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-cyan-400" />}
              </button>
            ))}
            <button className="icon-btn ml-auto h-7 w-7" aria-label="Hide panel" title="Hide panel" onClick={() => setPanelOpen(false)}><PanelRightClose size={15} /></button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4" role="tabpanel">
            {tab === "inspect" && <InspectTab onZoom={(p) => mapRef.current?.flyTo(p, 17)} />}
            {tab === "simulate" && <SimulateTab mode={mode} setMode={setMode} onZoomSegment={zoomToSegment} />}
            {tab === "critical" && <CriticalTab onZoom={(p) => mapRef.current?.flyTo(p, 16)} />}
          </div>
        </div>
      </aside>
      {!panelOpen && (
        <button className="glass absolute bottom-10 right-3 z-30 flex items-center gap-1.5 px-3 py-2 text-xs text-slate-200" onClick={() => setPanelOpen(true)}>
          <PanelRightOpen size={14} /> Panel
        </button>
      )}

      {/* status bar */}
      <div className={`pointer-events-none absolute bottom-3 left-1/2 z-20 -translate-x-1/2 transition-transform max-lg:hidden ${panelOpen ? "-ml-[190px]" : ""}`}>
        <div className="glass pointer-events-auto flex items-center gap-3 px-3.5 py-2 text-xs" role="status" aria-live="polite">
          {ws.loading ? <><Spinner /> <span className="text-slate-200">{ws.loading}…</span></> : !ws.region ? (
            <span className="text-slate-400">No road network loaded</span>
          ) : (
            <>
              <Activity size={14} className={failedCount ? "text-red-300" : "text-emerald-300"} />
              <span className="text-slate-200">{failedCount ? `${failedCount} road${failedCount > 1 ? "s" : ""} closed` : "Intact network"}</span>
              {ev && failedCount > 0 && <span className="text-slate-400">· {ev.network.cut_off_nodes} nodes cut off</span>}
              {route && (route.current.available
                ? <span className="text-slate-400">· route {route.current.length_m! >= 1000 ? `${(route.current.length_m! / 1000).toFixed(2)} km` : `${Math.round(route.current.length_m!)} m`}{route.detour_m && route.detour_m > 0.5 ? <span className="text-amber-300"> (+{route.detour_pct!.toFixed(1)}%)</span> : ""}</span>
                : <span className="text-red-300">· no route A→B</span>)}
              {ev?.sampled && failedCount > 0 && <span className="text-slate-400" title="Sampled estimate">· efficiency {(ev.sampled.efficiency_retention! * 100).toFixed(1)}%</span>}
              {mode !== "select" && <span className="rounded bg-cyan-400/15 px-1.5 py-0.5 text-cyan-100">click map to set {mode === "origin" ? "A" : "B"}</span>}
            </>
          )}
        </div>
      </div>

      {ws.error && ws.error.code !== "not_indexed" && ws.error.code !== "index_missing" && (
        <div className="absolute left-1/2 top-3 z-40 w-[min(460px,calc(100%-24px))] -translate-x-1/2" role="alert">
          <div className="glass flex items-start gap-2 border-red-400/30 px-3 py-2.5 text-xs">
            <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-red-400" />
            <div className="flex-1"><div className="font-medium text-red-100">{ws.error.code ?? "Error"}</div><div className="mt-0.5 text-red-100/80">{ws.error.message}</div></div>
            <button className="text-slate-400 hover:text-white" aria-label="Dismiss" onClick={ws.clearError}><X size={14} /></button>
          </div>
        </div>
      )}
      {(ws.error?.code === "not_indexed" || ws.error?.code === "index_missing") && (
        <div className="absolute left-1/2 top-3 z-40 w-[min(420px,calc(100%-24px))] -translate-x-1/2">
          <div className="glass border-amber-400/30 px-3 py-2.5 text-xs text-amber-50/90">{ws.error.message}</div>
        </div>
      )}
    </div>
  );
}

function ToolBtn({ children, label, onClick, active, disabled }: { children: React.ReactNode; label: string; onClick: () => void; active?: boolean; disabled?: boolean }) {
  return (
    <button className={`icon-btn relative ${active ? "bg-cyan-400/20 text-cyan-100" : ""}`} aria-label={label} title={label} aria-pressed={active} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}
