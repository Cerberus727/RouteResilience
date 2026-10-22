import { Map as MapIcon, Microscope, ScrollText } from "lucide-react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import { useApi } from "./api/useApi";
import { Lab } from "./pages/Lab";
import { MapWorkspace } from "./pages/MapWorkspace";
import { Reports } from "./pages/Reports";
import { useWorkspace, WorkspaceProvider } from "./state/workspace";

const NAV = [
  { to: "/", label: "Map", icon: MapIcon },
  { to: "/lab", label: "Segmentation Lab", icon: Microscope },
  { to: "/reports", label: "Reports", icon: ScrollText },
];

function Shell() {
  const health = useApi(() => api.health(), []);
  const ws = useWorkspace();
  return (
    <div className="flex h-full flex-col">
      <header className="z-40 flex h-12 shrink-0 items-center gap-4 border-b border-white/[0.06] bg-ink-950 px-4">
        <div className="flex items-center gap-2">
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
            <path d="M4 25 L12 13 L19 19 L28 6" stroke="#22d3ee" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M12 13 L16 6" stroke="#22c55e" strokeWidth="2.2" strokeLinecap="round" strokeDasharray="2 3" />
            <circle cx="19" cy="19" r="3.2" fill="#ef4444" /><circle cx="12" cy="13" r="2.4" fill="#f59e0b" />
          </svg>
          <span className="text-[14px] font-semibold tracking-tight text-slate-50">RouteResilience</span>
        </div>
        <nav className="flex h-full items-stretch gap-1" aria-label="Main">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"}
              className={({ isActive }) => `relative flex items-center gap-1.5 px-3 text-xs font-medium transition-colors ${isActive ? "text-white" : "text-slate-400 hover:text-slate-200"}`}>
              {({ isActive }) => (<><Icon size={14} /> <span className="max-sm:hidden">{label}</span>{isActive && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-cyan-400" />}</>)}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-[11px] text-slate-400">
          {ws.region && (
            <span className="hidden items-center gap-1.5 rounded-md border border-white/[0.07] px-2 py-1 md:flex" title={ws.region.bbox.join(", ")}>
              <span className="h-1.5 w-1.5 rounded-full bg-cyan-400" />
              {ws.region.places[0]?.name ?? "Region"} · {ws.region.summary.segments.toLocaleString()} roads
            </span>
          )}
          <span className="flex items-center gap-1.5" title={health.error?.message ?? "Backend API"}>
            <span className={`h-2 w-2 rounded-full ${health.error ? "bg-red-500" : health.data ? "bg-emerald-400" : "bg-slate-500"}`} />
            {health.error ? "API offline" : "API"}
          </span>
        </div>
      </header>
      <main className="relative min-h-0 flex-1">
        <Routes>
          <Route index element={<MapWorkspace />} />
          <Route path="lab" element={<Lab />} />
          <Route path="reports" element={<Reports />} />
          <Route path="*" element={<div className="p-6 text-sm text-slate-400">Page not found. <NavLink className="text-cyan-300" to="/">Open the map</NavLink></div>} />
        </Routes>
      </main>
    </div>
  );
}

export function App() {
  return (
    <WorkspaceProvider>
      <Shell />
    </WorkspaceProvider>
  );
}
