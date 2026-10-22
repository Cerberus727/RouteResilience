"""CSV / JSON exports and downloadable reports."""

from __future__ import annotations

import csv
import html
import io
from datetime import datetime, timezone

from .. import __version__
from ..definitions import DEFINITIONS
from ..graph_io import Variant
from . import experiments
from . import graphs as graph_service
from . import reviews
from .graphs import LoadedGraph
from .views import graph_detail, node_rows

METRIC_FIELDS = [
    "nodes", "edges", "components", "isolated_nodes", "lcc_size", "lcc_fraction", "reachable_pairs", "total_pairs",
    "reachable_pair_fraction", "avg_path_length", "efficiency", "density", "avg_degree", "total_length",
]


def _csv(rows: list[dict], fields: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})
    return buf.getvalue()


def nodes_csv(lg: LoadedGraph, variant: Variant) -> str:
    return _csv(node_rows(lg, variant), ["id", "x", "y", "degree", "component", "betweenness", "rank"])


def edges_csv(lg: LoadedGraph, variant: Variant) -> str:
    review_map = reviews.get_reviews(lg.graph_id)
    rows = [
        {"id": e.id, "source": e.source, "target": e.target, "length": e.length, "length_source": e.length_source,
         "healed": "" if e.healed is None else str(e.healed).lower(),
         "review": (review_map.get(e.id) or {}).get("decision", "")}
        for e in lg.doc.edges if not (variant == "original" and e.healed)
    ]
    return _csv(rows, ["id", "source", "target", "length", "length_source", "healed", "review"])


def metrics_csv(lg: LoadedGraph, variant: Variant) -> str:
    m = graph_service.baseline_metrics(lg, variant).to_dict()
    return _csv([{"graph_id": lg.graph_id, "variant": variant, **m}], ["graph_id", "variant", *METRIC_FIELDS])


def graph_json(lg: LoadedGraph, variant: Variant) -> dict:
    detail = graph_detail(lg, variant, include_coords=False)
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "app_version": __version__,
        "provenance_note": "metrics/betweenness/components recomputed by the app; file_stats are as stored in the artifact",
        **{k: detail[k] for k in ("graph_id", "set_id", "image_id", "variant", "metrics", "component_sizes",
                                  "degree_histogram", "file_stats", "provenance", "healing_provenance", "warnings")},
        "nodes": detail["nodes"],
        "edges": detail["edges"],
        "definitions": DEFINITIONS,
    }


def simulation_csv(result: dict) -> str:
    base = {"step": 0, "kind": "baseline", "removed": "", **result["baseline"], "efficiency_retention": 1.0 if result["baseline"]["efficiency"] else None,
            "pair_connectivity_retention": 1.0 if result["baseline"]["reachable_pair_fraction"] else None}
    rows = [base] + [
        {"step": s["step"], "kind": s["kind"], "removed": s["removed"], **s["metrics"],
         "efficiency_retention": s["efficiency_retention"], "pair_connectivity_retention": s["pair_connectivity_retention"]}
        for s in result["steps"]
    ]
    return _csv(rows, ["step", "kind", "removed", *METRIC_FIELDS, "efficiency_retention", "pair_connectivity_retention"])


# ---------------------------------------------------------------- report
def _fmt(v, digits=4) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{digits}g}" if abs(v) < 1e-3 and v != 0 else f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return str(v)


def build_report(lg: LoadedGraph, variant: Variant, critical: dict, simulation: dict | None, healing: dict | None) -> str:
    d = graph_detail(lg, variant, include_coords=False)
    m = d["metrics"]
    lines = [
        f"# RouteResilience report — {lg.graph_id}",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} by RouteResilience {__version__}.",
        "",
        "## Provenance",
        "",
        f"* Graph file: `{d['provenance']['file']}` (schema `{d['schema_name']}`, model tag `{d['model_tag']}`)",
        f"* Source mask set: `{d['provenance']['source_mask_set']}` — {'verified from notebook log' if d['provenance']['source_verified'] else 'NOT verified'}",
    ]
    if d["provenance"]["note"]:
        lines.append(f"* Note: {d['provenance']['note']}")
    lines += [
        f"* Graph variant analysed: **{variant}**" + (" (healing bridges removed)" if variant == "original" else " (as stored, including healing bridges)"),
        f"* Healing provenance: {d['healing_provenance']}",
        "* Every metric below was **recomputed by the app** with NetworkX unless marked *historical*.",
        "",
        "## Baseline network metrics (recomputed)",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    lines += [f"| {k} | {_fmt(m[k])} |" for k in METRIC_FIELDS]
    if d["file_stats"]:
        lines += ["", "Stored Phase II stats (*historical*): " + ", ".join(f"{k}={v}" for k, v in d["file_stats"].items())]

    lines += ["", f"## Critical junctions (betweenness, scope `{critical['scope']}`)", "",
              "Betweenness is a structural indicator, not a probability of real-world failure.", "",
              "| Rank | Node | Betweenness | Degree | Component | Components after removal | Efficiency retention |",
              "|---|---|---|---|---|---|---|"]
    for n in critical["nodes"]:
        imp = n.get("impact") or {}
        lines.append(f"| {n['rank']} | {n['id']} | {_fmt(n['betweenness'])} | {n['degree']} | {n['component']} | "
                     f"{_fmt(imp.get('components_after'))} | {_fmt(imp.get('efficiency_retention'))} |")
    hist = critical.get("notebook")
    if hist and not hist.get("error"):
        lines += ["", f"*Historical* Phase III gatekeepers ({hist['source']}, largest component only): "
                  + ", ".join(f"{g['id']} ({g['betweenness']})" for g in hist["gatekeepers"])]

    if healing:
        lines += ["", "## Healing (recorded bridge edges)", "",
                  f"* Healed edges in file: {healing['counts']['healed_edges']} of {healing['counts']['edges']}",
                  f"* Reviewed: {healing['counts']['approved']} approved, {healing['counts']['rejected']} rejected",
                  f"* Components original → healed: {healing['metrics_original']['components']} → {healing['metrics_healed']['components']}",
                  f"* Reachable pair fraction original → healed: {_fmt(healing['metrics_original']['reachable_pair_fraction'])} → {_fmt(healing['metrics_healed']['reachable_pair_fraction'])}",
                  "* More connectivity after healing does not by itself mean higher accuracy; bridges can join roads that are not connected on the ground."]

    if simulation:
        cmp = simulation["comparison"]
        lines += ["", "## Failure simulation", "",
                  f"* Mode: {simulation['mode']}, strategy: {simulation['strategy']}",
                  f"* Removed nodes: {', '.join(simulation['removed_nodes']) or '—'}",
                  f"* Removed edges: {', '.join(simulation['removed_edges']) or '—'}",
                  f"* Efficiency retention ρ: {_fmt(cmp['efficiency_retention'])}  (degradation {_fmt(cmp['degradation'])})",
                  f"* Pair connectivity retention: {_fmt(cmp['pair_connectivity_retention'])}",
                  "", "| Metric | Baseline | After | Relative change |", "|---|---|---|---|"]
        for k, c in cmp["changes"].items():
            rel = f"{c['relative'] * 100:+.1f}%" if c["relative"] is not None else "n/a"
            lines.append(f"| {k} | {_fmt(c['baseline'])} | {_fmt(c['after'])} | {rel} |")
        if len(simulation["steps"]) > 1:
            lines += ["", "| Step | Removed | Components | LCC fraction | Efficiency retention |", "|---|---|---|---|---|"]
            for s in simulation["steps"]:
                lines.append(f"| {s['step']} | {s['removed']} | {s['metrics']['components']} | {_fmt(s['metrics']['lcc_fraction'])} | {_fmt(s['efficiency_retention'])} |")

    lines += ["", "## Metric definitions", ""]
    for df in DEFINITIONS:
        lines.append(f"* **{df['name']}** — `{df['formula']}`. {df['text']}")
    lines += ["", "## Model provenance", "",
              "Masks come from the Phase I segmentation notebook. See docs/ARTIFACT_AUDIT.md for checkpoint "
              "loadability and the metrics that are actually available."]
    return "\n".join(lines) + "\n"


def markdown_to_html(md: str, title: str) -> str:
    """Tiny renderer for the subset of Markdown the report uses (headings, lists, tables)."""
    out, in_list, in_table = [], False, False

    def inline(s: str) -> str:
        s = html.escape(s)
        import re

        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)
        return re.sub(r"`(.+?)`", r"<code>\1</code>", s)

    for line in md.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-") for c in cells):
                continue
            if not in_table:
                out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells) + "</tr>")
                in_table = True
            else:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if line.startswith("* "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    if in_table:
        out.append("</table>")
    if in_list:
        out.append("</ul>")
    style = ("body{font:14px/1.5 system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#1e293b}"
             "table{border-collapse:collapse;margin:.5rem 0}td,th{border:1px solid #cbd5e1;padding:3px 8px;text-align:left}"
             "th{background:#f1f5f9}code{background:#f1f5f9;padding:0 3px}h1{font-size:22px}h2{font-size:17px;margin-top:1.6rem}")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{style}</style></head><body>{''.join(out)}</body></html>"


def historical_analysis(lg: LoadedGraph) -> dict | None:
    return experiments.read_analysis(lg.set_id, lg.image_id)
