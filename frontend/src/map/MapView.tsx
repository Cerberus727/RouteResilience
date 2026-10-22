import maplibregl, { type GeoJSONSource, type Map as MLMap, type MapGeoJSONFeature } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { BBox, LngLat, RoadCollection } from "../api/types";
import type { Basemap, Layers } from "../state/workspace";
import { BASEMAPS, COLORS } from "./style";

export type MapMode = "select" | "origin" | "destination";

export interface MapHandle {
  fitBounds: (b: BBox, opts?: { padding?: number; animate?: boolean }) => void;
  flyTo: (p: LngLat, zoom?: number) => void;
  resetNorth: () => void;
  zoomBy: (d: number) => void;
  getBounds: () => BBox | null;
  exportPNG: () => string | null;
}

export interface MapState {
  roads: RoadCollection | null;
  regionBBox: BBox | null;
  extents: BBox[];
  intersections: GeoJSON.FeatureCollection | null;
  criticalNodes: { lonlat: LngLat; rank: number; is_articulation: boolean }[];
  selectedSid: string | null;
  selectedNid: number | null;
  failed: string[];
  affected: string[];
  regained: string[];
  matches: string[];
  critScores: Record<string, number> | null;
  baselineRoute: LngLat[] | null;
  currentRoute: LngLat[] | null;
  origin: LngLat | null;
  destination: LngLat | null;
  layers: Layers;
  basemap: Basemap;
}

interface Props extends MapState {
  mode: MapMode;
  initialBounds: BBox;
  onSelectSegment: (sid: string | null) => void;
  onSelectNode: (nid: number) => void;
  onPick: (mode: "origin" | "destination", p: LngLat) => void;
  onBasemapError: (msg: string | null) => void;
  onViewChange?: (b: BBox, zoom: number) => void;
}

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
const line = (coords: LngLat[] | null): GeoJSON.FeatureCollection =>
  coords && coords.length > 1 ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: coords } }] } : EMPTY;
const boxes = (bb: BBox[], kind: string): GeoJSON.Feature[] => bb.map((b) => ({
  type: "Feature", properties: { kind },
  geometry: { type: "Polygon", coordinates: [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]] },
}));

function arrowImage(): ImageData {
  const s = 24;
  const c = document.createElement("canvas");
  c.width = c.height = s;
  const g = c.getContext("2d")!;
  g.strokeStyle = "rgba(203,213,225,0.9)";
  g.lineWidth = 2.5;
  g.lineCap = "round";
  g.lineJoin = "round";
  g.beginPath();
  g.moveTo(8, 6); g.lineTo(15, 12); g.lineTo(8, 18);
  g.stroke();
  return g.getImageData(0, 0, s, s);
}

function markerEl(kind: "origin" | "destination"): HTMLElement {
  const el = document.createElement("div");
  el.className = `rr-marker rr-marker-${kind}`;
  el.textContent = kind === "origin" ? "A" : "B";
  el.setAttribute("aria-label", kind === "origin" ? "Route origin" : "Route destination");
  return el;
}

export const MapView = forwardRef<MapHandle, Props>(function MapView(props, ref) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const idOf = useRef<Map<string, number>>(new Map());
  const applied = useRef<Record<string, Set<number>>>({});
  const markers = useRef<{ origin?: maplibregl.Marker; destination?: maplibregl.Marker }>({});
  const propsRef = useRef(props);
  propsRef.current = props;
  const [hover, setHover] = useState<{ x: number; y: number; text: string; sub: string } | null>(null);

  useImperativeHandle(ref, () => ({
    fitBounds: (b, o) => mapRef.current?.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: o?.padding ?? 48, animate: o?.animate ?? true, duration: 700, maxZoom: 17 }),
    flyTo: (p, zoom) => mapRef.current?.flyTo({ center: p, zoom: zoom ?? Math.max(mapRef.current.getZoom(), 16), duration: 700 }),
    resetNorth: () => mapRef.current?.easeTo({ bearing: 0, pitch: 0, duration: 400 }),
    zoomBy: (d) => mapRef.current?.easeTo({ zoom: mapRef.current.getZoom() + d, duration: 250 }),
    getBounds: () => {
      const b = mapRef.current?.getBounds();
      return b ? [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()] : null;
    },
    exportPNG: () => {
      try {
        return mapRef.current?.getCanvas().toDataURL("image/png") ?? null;
      } catch {
        return null; // tainted canvas (basemap without CORS)
      }
    },
  }), []);

  // ---------------------------------------------------------------- init
  useEffect(() => {
    if (!container.current) return;
    const b = props.initialBounds;
    const map = new maplibregl.Map({
      container: container.current,
      bounds: [[b[0], b[1]], [b[2], b[3]]],
      fitBoundsOptions: { padding: 40 },
      maxPitch: 0,
      dragRotate: false,
      attributionControl: { compact: true },
      preserveDrawingBuffer: true,
      style: {
        version: 8,
        sources: Object.fromEntries(Object.entries(BASEMAPS).flatMap(([k, v]) => v.layers.map((l, i) => [
          `bm-${k}-${i}`, { type: "raster", tiles: l.tiles, tileSize: 256, maxzoom: l.maxzoom, ...(i === 0 && v.attribution ? { attribution: v.attribution } : {}) },
        ]))),
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#0b111c" } },
          ...Object.entries(BASEMAPS).flatMap(([k, v]) => v.layers.map((_, i) => ({
            id: `bm-${k}-${i}`, type: "raster" as const, source: `bm-${k}-${i}`,
            layout: { visibility: (k === props.basemap ? "visible" : "none") as "visible" | "none" },
            paint: { "raster-opacity": k === "satellite" ? 0.85 : i === 1 ? 0.75 : 1, "raster-fade-duration": 150 },
          }))),
        ],
      },
    } as maplibregl.MapOptions);
    mapRef.current = map;
    map.touchZoomRotate.disableRotation();
    // Surface style/layer errors (MapLibre reports them as events, not exceptions).
    map.on("error", (ev) => {
      const src = (ev as unknown as { sourceId?: string }).sourceId;
      if (!src?.startsWith("bm-")) console.error("[map]", ev.error?.message ?? ev);
    });

    // Set up on style.load (not load): roads and interaction must not wait for basemap tiles,
    // which can be slow or unavailable offline.
    map.once("style.load", () => {
      map.addImage("oneway", arrowImage(), { pixelRatio: 2 });
      map.addSource("extents", { type: "geojson", data: EMPTY });
      map.addSource("roads", { type: "geojson", data: EMPTY, attribution: 'Roads © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors (ODbL)' });
      map.addSource("nodes", { type: "geojson", data: EMPTY });
      map.addSource("crit-nodes", { type: "geojson", data: EMPTY });
      map.addSource("route-base", { type: "geojson", data: EMPTY });
      map.addSource("route-cur", { type: "geojson", data: EMPTY });

      map.addLayer({ id: "extents-fill", type: "fill", source: "extents", paint: { "fill-color": ["match", ["get", "kind"], "region", "#22d3ee", "#64748b"], "fill-opacity": ["match", ["get", "kind"], "region", 0.025, 0] } });
      map.addLayer({ id: "extents-line", type: "line", source: "extents", paint: {
        "line-color": ["match", ["get", "kind"], "region", "#22d3ee", "#64748b"], "line-width": 1.2, "line-dasharray": [3, 2],
        "line-opacity": ["match", ["get", "kind"], "region", 0.55, 0.6] } });

      const w = (minor: number, major: number) => ["interpolate", ["linear"], ["zoom"], 11, ["*", ["get", "__w"], minor], 17, ["*", ["get", "__w"], major]];
      map.addLayer({ id: "roads-casing", type: "line", source: "roads", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#05080f", "line-width": w(1.4, 9) as never, "line-opacity": 0.8 } });
      map.addLayer({ id: "roads-base", type: "line", source: "roads", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": ["get", "__c"], "line-width": w(0.8, 6) as never } });
      map.addLayer({ id: "roads-crit", type: "line", source: "roads", layout: { "line-cap": "round", "line-join": "round", visibility: "none" },
        paint: {
          "line-color": ["interpolate", ["linear"], ["coalesce", ["feature-state", "crit"], 0], 0, COLORS.critLow, 0.5, COLORS.critMid, 1, COLORS.critHigh],
          "line-width": ["interpolate", ["linear"], ["zoom"], 11, ["+", 1, ["*", 2.5, ["coalesce", ["feature-state", "crit"], 0]]], 17, ["+", 3, ["*", 7, ["coalesce", ["feature-state", "crit"], 0]]]],
          "line-opacity": ["case", [">", ["coalesce", ["feature-state", "crit"], 0], 0.02], 0.95, 0],
        } });
      const stateLayer = (id: string, key: string, color: string, widen: number) => map.addLayer({
        id, type: "line", source: "roads", layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": color,
          "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1.5 + widen / 3, 17, 5 + widen],
          "line-opacity": ["case", ["boolean", ["feature-state", key], false], 1, 0],
        },
      });
      stateLayer("roads-affected", "affected", COLORS.affected, 1);
      stateLayer("roads-regained", "regained", COLORS.regained, 2);
      stateLayer("roads-match", "match", COLORS.match, 2);

      map.addLayer({ id: "route-base", type: "line", source: "route-base", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": COLORS.routeBase, "line-width": ["interpolate", ["linear"], ["zoom"], 11, 2.5, 17, 7], "line-dasharray": [1.2, 1.4], "line-opacity": 0.9 } });
      map.addLayer({ id: "route-cur-casing", type: "line", source: "route-cur", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#052e16", "line-width": ["interpolate", ["linear"], ["zoom"], 11, 5, 17, 12] } });
      map.addLayer({ id: "route-cur", type: "line", source: "route-cur", layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": COLORS.route, "line-width": ["interpolate", ["linear"], ["zoom"], 11, 3, 17, 8] } });

      stateLayer("roads-failed", "failed", COLORS.failed, 4);
      stateLayer("roads-selected", "sel", COLORS.selected, 3);

      map.addLayer({ id: "oneway", type: "symbol", source: "roads", minzoom: 16, filter: ["!=", ["get", "ow"], 0],
        layout: { "symbol-placement": "line", "symbol-spacing": 90, "icon-image": "oneway", "icon-size": 0.7,
          "icon-rotate": ["case", ["==", ["get", "ow"], -1], 180, 0], "icon-rotation-alignment": "map", "icon-allow-overlap": true } });
      map.addLayer({ id: "nodes", type: "circle", source: "nodes", minzoom: 15,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 15, 2, 18, 4.5],
          "circle-color": ["case", ["boolean", ["feature-state", "sel"], false], COLORS.selected, "#cbd5e1"],
          "circle-stroke-color": "#05080f", "circle-stroke-width": 1, "circle-opacity": 0.85,
        } });
      map.addLayer({ id: "crit-nodes", type: "circle", source: "crit-nodes",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, ["case", ["<=", ["get", "rank"], 5], 5, 3.5], 17, ["case", ["<=", ["get", "rank"], 5], 10, 7]],
          "circle-color": COLORS.criticalNode, "circle-opacity": 0.92,
          "circle-stroke-color": ["case", ["get", "art"], "#fff7ed", "#1c1408"], "circle-stroke-width": ["case", ["get", "art"], 2, 1],
        } });
      map.addLayer({ id: "roads-hit", type: "line", source: "roads", paint: { "line-color": "#000", "line-width": 14, "line-opacity": 0 } });

      // ---------------- interaction
      map.on("click", (e) => {
        const p = propsRef.current;
        if (p.mode !== "select") {
          p.onPick(p.mode, [e.lngLat.lng, e.lngLat.lat]);
          return;
        }
        const pad = 6;
        const box: [maplibregl.PointLike, maplibregl.PointLike] = [[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]];
        const nodeHits = map.getLayer("nodes") && map.getZoom() >= 15 ? map.queryRenderedFeatures(box, { layers: ["nodes"] }) : [];
        if (nodeHits.length) {
          p.onSelectNode(Number(nodeHits[0].properties?.nid));
          return;
        }
        const hits = map.queryRenderedFeatures(box, { layers: ["roads-hit"] });
        p.onSelectSegment(hits.length ? String(hits[0].properties?.sid) : null);
      });
      map.on("mousemove", (e) => {
        const p = propsRef.current;
        const hits: MapGeoJSONFeature[] = map.queryRenderedFeatures([[e.point.x - 4, e.point.y - 4], [e.point.x + 4, e.point.y + 4]], { layers: ["roads-hit"] });
        map.getCanvas().style.cursor = p.mode !== "select" ? "crosshair" : hits.length ? "pointer" : "";
        if (hits.length && p.mode === "select") {
          const pr = hits[0].properties as Record<string, unknown>;
          const ow = Number(pr.ow);
          setHover({ x: e.point.x, y: e.point.y, text: String(pr.name || String(pr.hw).replace("_", " ")),
            sub: `${String(pr.hw).replace("_", " ")} · ${Math.round(Number(pr.len))} m${ow ? " · one-way" : ""}` });
        } else setHover(null);
      });
      map.on("mouseout", () => setHover(null));
      map.on("moveend", () => {
        const bb = map.getBounds();
        propsRef.current.onViewChange?.([bb.getWest(), bb.getSouth(), bb.getEast(), bb.getNorth()], map.getZoom());
      });
      map.on("error", (ev) => {
        const src = (ev as unknown as { sourceId?: string }).sourceId;
        if (src && src.startsWith("bm-")) propsRef.current.onBasemapError("Basemap tiles could not be loaded (offline or blocked). Road data is unaffected.");
      });
      map.on("sourcedata", (ev) => {
        if (ev.sourceId?.startsWith("bm-") && ev.isSourceLoaded) propsRef.current.onBasemapError(null);
      });
      setReady(true);
    });
    return () => {
      markers.current.origin?.remove();
      markers.current.destination?.remove();
      map.remove();
      mapRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------- data sync
  const { roads, intersections, criticalNodes, regionBBox, extents, basemap, layers } = props;

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const m = new Map<string, number>();
    const fc = roads ? {
      type: "FeatureCollection" as const,
      features: roads.features.map((f) => {
        m.set(f.properties.sid, f.id);
        const style = COLORS.byClass[f.properties.hw] ?? COLORS.byClass.default;
        return { ...f, properties: { ...f.properties, __c: style.color, __w: style.width } };
      }),
    } : EMPTY;
    idOf.current = m;
    applied.current = {};
    (map.getSource("roads") as GeoJSONSource).setData(fc as GeoJSON.FeatureCollection);
  }, [ready, roads]);

  useEffect(() => {
    if (!ready || !mapRef.current) return;
    (mapRef.current.getSource("nodes") as GeoJSONSource).setData(intersections ?? EMPTY);
  }, [ready, intersections]);

  useEffect(() => {
    if (!ready || !mapRef.current) return;
    (mapRef.current.getSource("crit-nodes") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: criticalNodes.map((c) => ({ type: "Feature", properties: { rank: c.rank, art: c.is_articulation }, geometry: { type: "Point", coordinates: c.lonlat } })),
    });
  }, [ready, criticalNodes]);

  useEffect(() => {
    if (!ready || !mapRef.current) return;
    (mapRef.current.getSource("extents") as GeoJSONSource).setData({
      type: "FeatureCollection", features: [...boxes(extents, "index"), ...boxes(regionBBox ? [regionBBox] : [], "region")],
    });
  }, [ready, extents, regionBBox]);

  // feature-state diffs
  const setFlag = (key: string, sids: string[] | null, value: (sid: string) => unknown = () => true) => {
    const map = mapRef.current;
    if (!map || !map.getSource("roads")) return;
    const prev = applied.current[key] ?? new Set<number>();
    const next = new Set<number>();
    for (const sid of sids ?? []) {
      const id = idOf.current.get(sid);
      if (id === undefined) continue;
      next.add(id);
      map.setFeatureState({ source: "roads", id }, { [key]: value(sid) });
    }
    prev.forEach((id) => { if (!next.has(id)) map.setFeatureState({ source: "roads", id }, { [key]: key === "crit" ? 0 : false }); });
    applied.current[key] = next;
  };

  useEffect(() => { if (ready) setFlag("failed", props.failed); }, [ready, props.failed, roads]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (ready) setFlag("affected", layers.affected ? props.affected : []); }, [ready, props.affected, layers.affected, roads]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (ready) setFlag("regained", props.regained); }, [ready, props.regained, roads]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (ready) setFlag("match", props.matches); }, [ready, props.matches, roads]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (ready) setFlag("sel", props.selectedSid ? [props.selectedSid] : []); }, [ready, props.selectedSid, roads]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!ready) return;
    const sc = props.critScores;
    const max = sc ? Math.max(1e-9, ...Object.values(sc)) : 1;
    setFlag("crit", sc ? Object.keys(sc) : [], (sid) => Math.sqrt((sc![sid] ?? 0) / max));
  }, [ready, props.critScores, roads]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const src = map.getSource("nodes") as GeoJSONSource | undefined;
    if (!src) return;
    (intersections?.features ?? []).forEach((f) => {
      if (f.id !== undefined) map.setFeatureState({ source: "nodes", id: f.id as number }, { sel: Number(f.properties?.nid) === props.selectedNid });
    });
  }, [ready, props.selectedNid, intersections]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource("route-base") as GeoJSONSource).setData(line(props.baselineRoute));
    (map.getSource("route-cur") as GeoJSONSource).setData(line(props.currentRoute));
  }, [ready, props.baselineRoute, props.currentRoute]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    for (const kind of ["origin", "destination"] as const) {
      const p = props[kind];
      const m = markers.current[kind];
      if (!p) { m?.remove(); markers.current[kind] = undefined; continue; }
      if (m) m.setLngLat(p);
      else markers.current[kind] = new maplibregl.Marker({ element: markerEl(kind), anchor: "center" }).setLngLat(p).addTo(map);
    }
  }, [ready, props.origin, props.destination]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    for (const [k, v] of Object.entries(BASEMAPS)) v.layers.forEach((_, i) => map.setLayoutProperty(`bm-${k}-${i}`, "visibility", k === basemap ? "visible" : "none"));
    const vis = (id: string, on: boolean) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    ["roads-casing", "roads-base", "oneway"].forEach((id) => vis(id, layers.roads));
    vis("nodes", layers.intersections);
    vis("roads-crit", layers.criticality);
    vis("crit-nodes", layers.criticalNodes);
    ["extents-fill", "extents-line"].forEach((id) => vis(id, layers.extents));
  }, [ready, basemap, layers]);

  return (
    <div className="absolute inset-0">
      <div ref={container} className="absolute inset-0" data-testid="map" data-ready={ready ? "true" : "false"} />
      {hover && (
        <div className="pointer-events-none absolute z-10 rounded-md border border-white/10 bg-ink-900/95 px-2 py-1 text-[11px] shadow-xl"
          style={{ left: hover.x + 14, top: hover.y + 12 }}>
          <div className="font-medium text-slate-100">{hover.text}</div>
          <div className="text-slate-400">{hover.sub}</div>
        </div>
      )}
    </div>
  );
});
