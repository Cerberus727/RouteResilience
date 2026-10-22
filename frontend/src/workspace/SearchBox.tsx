import { MapPin, Route, Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { SearchHit } from "../api/types";
import { Spinner } from "../components/ui";

export function SearchBox({ regionId, onPick }: { regionId: string | null; onPick: (h: SearchHit) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const seq = useRef(0);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setHits(null); setErr(null); return; }
    const id = ++seq.current;
    const t = setTimeout(() => {
      setBusy(true);
      api.search(term, regionId).then((h) => { if (id === seq.current) { setHits(h); setErr(null); setActive(0); } })
        .catch((e) => { if (id === seq.current) { setHits(null); setErr(e.message); } })
        .finally(() => { if (id === seq.current) setBusy(false); });
    }, 220);
    return () => clearTimeout(t);
  }, [q, regionId]);

  const choose = (h: SearchHit) => { onPick(h); setHits(null); setQ(h.name); };

  return (
    <div className="relative w-full">
      <div className="glass flex items-center gap-2 px-3 py-2">
        <Search size={15} className="shrink-0 text-slate-400" />
        <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search places and roads"
          placeholder="Search a road or neighbourhood…" className="w-full bg-transparent text-[13px] text-slate-100 placeholder:text-slate-500 focus:outline-none"
          onKeyDown={(e) => {
            if (!hits?.length) return;
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(hits.length - 1, a + 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
            if (e.key === "Enter") choose(hits[active]);
            if (e.key === "Escape") setHits(null);
          }} />
        {busy ? <Spinner /> : q && <button className="text-slate-500 hover:text-slate-200" aria-label="Clear search" onClick={() => { setQ(""); setHits(null); }}><X size={14} /></button>}
      </div>
      {(hits || err) && (
        <div className="glass absolute left-0 right-0 top-full z-30 mt-1.5 max-h-80 overflow-auto p-1" role="listbox">
          {err && <div className="px-2 py-2 text-xs text-red-300">{err}</div>}
          {hits && hits.length === 0 && <div className="px-2 py-2 text-xs text-slate-400">No matching roads in the loaded region or places in the index.</div>}
          {hits?.map((h, i) => (
            <button key={`${h.source}-${h.name}-${i}`} role="option" aria-selected={i === active} onMouseEnter={() => setActive(i)} onClick={() => choose(h)}
              className={`flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left ${i === active ? "bg-white/[0.07]" : ""}`}>
              {h.segment_ids ? <Route size={14} className="shrink-0 text-cyan-300" /> : <MapPin size={14} className="shrink-0 text-amber-300" />}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs text-slate-100">{h.name}</span>
                <span className="block truncate text-[10.5px] text-slate-500">{h.kind}{h.segment_ids ? ` · ${h.segment_ids.length} segment(s)` : ""} · {h.source}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
