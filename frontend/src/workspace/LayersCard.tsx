import { ChevronDown, Layers as LayersIcon } from "lucide-react";
import { useState } from "react";
import { Segmented, Toggle } from "../components/ui";
import { BASEMAPS, COLORS } from "../map/style";
import { type Basemap, useWorkspace } from "../state/workspace";

const Line = ({ color, dashed, width = 3 }: { color: string; dashed?: boolean; width?: number }) => (
  <svg width="22" height="8" aria-hidden className="shrink-0">
    <line x1="1" y1="4" x2="21" y2="4" stroke={color} strokeWidth={width} strokeLinecap="round" strokeDasharray={dashed ? "3 3" : undefined} />
  </svg>
);
const Dot = ({ color, ring }: { color: string; ring?: boolean }) => (
  <svg width="22" height="10" aria-hidden className="shrink-0"><circle cx="11" cy="5" r="4" fill={color} stroke={ring ? "#fff7ed" : "#05080f"} strokeWidth={ring ? 1.5 : 1} /></svg>
);

export function LayersCard({ basemapError }: { basemapError: string | null }) {
  const ws = useWorkspace();
  const [open, setOpen] = useState(() => typeof window === "undefined" || window.innerWidth >= 1024);
  const analysed = ws.analysis?.state === "done";
  const L = ws.layers;
  return (
    <div className="glass overflow-hidden">
      <button className="flex w-full items-center gap-2 px-3 py-2.5 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <LayersIcon size={14} className="text-cyan-300" />
        <span className="flex-1 text-[12.5px] font-semibold text-slate-100">Layers & legend</span>
        <ChevronDown size={14} className={`text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="space-y-3 border-t border-white/[0.06] px-3 py-3">
          <div>
            <div className="section-title mb-1.5">Basemap</div>
            <Segmented ariaLabel="Basemap" size="xs" value={ws.basemap} onChange={(v) => ws.setBasemap(v as Basemap)}
              options={(Object.keys(BASEMAPS) as Basemap[]).map((k) => ({ value: k, label: BASEMAPS[k].label }))} />
            {basemapError && ws.basemap !== "none" && <p className="mt-1.5 text-[10.5px] text-amber-300/90">{basemapError}</p>}
          </div>
          <div>
            <div className="section-title mb-1">Network</div>
            <Toggle checked={L.roads} onChange={(v) => ws.setLayer("roads", v)} label="Road segments" swatch={<Line color={COLORS.byClass.primary.color} />}
              hint="Drivable OSM ways split at intersections. Width and brightness follow the OSM road class. Arrows mark one-way streets at high zoom." />
            <Toggle checked={L.intersections} onChange={(v) => ws.setLayer("intersections", v)} label="Intersections (zoom ≥ 15)" swatch={<Dot color="#cbd5e1" />} />
            <Toggle checked={L.extents} onChange={(v) => ws.setLayer("extents", v)} label="Loaded area & index extent" swatch={<Line color="#22d3ee" dashed width={1.5} />} />
          </div>
          <div>
            <div className="section-title mb-1">Analysis</div>
            <Toggle checked={L.criticality} disabled={!analysed} onChange={(v) => ws.setLayer("criticality", v)} label="Road criticality"
              swatch={<svg width="22" height="8" aria-hidden><defs><linearGradient id="cg"><stop offset="0" stopColor={COLORS.critLow} /><stop offset=".5" stopColor={COLORS.critMid} /><stop offset="1" stopColor={COLORS.critHigh} /></linearGradient></defs><rect x="1" y="2" width="20" height="4" rx="2" fill="url(#cg)" /></svg>}
              hint="Sampled betweenness: how many sampled shortest paths use the segment. Run the analysis in the Critical tab first." />
            <Toggle checked={L.criticalNodes} disabled={!analysed} onChange={(v) => ws.setLayer("criticalNodes", v)} label="Critical intersections" swatch={<Dot color={COLORS.criticalNode} />}
              hint="Top-25 intersections by sampled betweenness. A white ring marks an articulation point (removing it splits the undirected graph)." />
            <Toggle checked={L.affected} onChange={(v) => ws.setLayer("affected", v)} label="Cut-off / unreachable roads" swatch={<Line color={COLORS.affected} />}
              hint="Roads that lose two-way connectivity to the main network, or that can no longer be reached from origin A." />
          </div>
          <div>
            <div className="section-title mb-1">Simulation</div>
            <ul className="space-y-1 text-xs text-slate-300">
              <li className="flex items-center gap-2"><Line color={COLORS.selected} /> Selected road</li>
              <li className="flex items-center gap-2"><Line color={COLORS.failed} width={4} /> Closed (failed) road</li>
              <li className="flex items-center gap-2"><Line color={COLORS.routeBase} dashed /> Baseline route (intact network)</li>
              <li className="flex items-center gap-2"><Line color={COLORS.route} width={4} /> Current / alternate route</li>
              <li className="flex items-center gap-2"><Line color={COLORS.regained} /> Connectivity regained after restore</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
