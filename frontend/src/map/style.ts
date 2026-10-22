// Map palette and keyless basemap providers.

export const COLORS = {
  selected: "#22d3ee",
  failed: "#ef4444",
  route: "#22c55e",
  routeBase: "#e2e8f0",
  affected: "#c084fc",
  regained: "#2dd4bf",
  match: "#67e8f9",
  criticalNode: "#f59e0b",
  critLow: "#fde68a",
  critMid: "#fb923c",
  critHigh: "#dc2626",
  byClass: {
    motorway: { color: "#cbd5e1", width: 1.9 },
    trunk: { color: "#cbd5e1", width: 1.8 },
    primary: { color: "#b6c2d3", width: 1.6 },
    secondary: { color: "#9aa8bb", width: 1.35 },
    tertiary: { color: "#7f8da1", width: 1.15 },
    motorway_link: { color: "#9aa8bb", width: 1.1 },
    trunk_link: { color: "#9aa8bb", width: 1.1 },
    primary_link: { color: "#8b98ab", width: 1.0 },
    secondary_link: { color: "#7f8da1", width: 0.95 },
    tertiary_link: { color: "#6b7a8f", width: 0.9 },
    residential: { color: "#5b6a80", width: 0.8 },
    living_street: { color: "#55637a", width: 0.7 },
    unclassified: { color: "#5b6a80", width: 0.8 },
    service: { color: "#475569", width: 0.6 },
    road: { color: "#5b6a80", width: 0.8 },
    default: { color: "#5b6a80", width: 0.8 },
  } as Record<string, { color: string; width: number }>,
};

export interface BasemapDef { label: string; layers: { tiles: string[]; maxzoom: number }[]; attribution: string }

// All providers below are keyless. CARTO basemaps were evaluated and rejected: they now return
// an "API KEY REQUIRED" placeholder tile. Esri Canvas tiles exist up to z16 and are over-zoomed beyond.
const esri = (svc: string) => [`https://server.arcgisonline.com/ArcGIS/rest/services/${svc}/MapServer/tile/{z}/{y}/{x}`];
export const BASEMAPS: Record<"dark" | "streets" | "satellite" | "none", BasemapDef> = {
  dark: {
    label: "Dark",
    layers: [{ tiles: esri("Canvas/World_Dark_Gray_Base"), maxzoom: 16 }, { tiles: esri("Canvas/World_Dark_Gray_Reference"), maxzoom: 16 }],
    attribution: "Basemap © Esri, HERE, Garmin, © OpenStreetMap contributors",
  },
  streets: {
    label: "Streets",
    layers: [{ tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], maxzoom: 19 }],
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  },
  satellite: {
    label: "Imagery",
    layers: [{ tiles: esri("World_Imagery"), maxzoom: 19 }],
    attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
  },
  none: { label: "None", layers: [], attribution: "" },
};
