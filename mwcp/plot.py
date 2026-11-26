"""Solver performance report (wall time, peak memory): one self-contained HTML file (inline SVG, no dependencies).

Input rows have the shape of `mwcp batch` result rows (results.jsonl). `mwcp solve --plot`
builds the same rows from its results, so both commands share one report.

The report shows, for wall time and for peak memory (RSS) each:
  * the median per solver over every run (graph x seed), as horizontal bars;
  * with more than one graph, the same per graph (bars = median over seeds, whisker = min-max);
and a table of every run, so nothing is only in a tooltip. Time and memory are separate charts
(never two scales on one axis). An axis switches to log scale when its values span more than
two orders of magnitude.
"""
from __future__ import annotations

import html
import json
import math
import statistics
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .style import dark, page, solver_colors, solver_order

WIDTH = 760          # SVG viewBox width; the SVG scales to the page width
BAR = 16             # bar thickness (px)
BAR_GAP = 2          # surface gap between adjacent bars
GROUP_GAP = 16       # space between graphs in the per-graph chart
MIN_TIME = 1e-3      # log axis floor: times below 1 ms are drawn at 1 ms
MIN_MEM = 0.1        # log axis floor for memory (MiB)


# ---------------------------------------------------------------------------- data

def load_rows(path: Path) -> List[dict]:
    """Rows from a batch dir, a results.jsonl, or a `mwcp solve --json` file."""
    path = Path(path)
    if path.is_dir():
        path = path / "results.jsonl"
    text = path.read_text()
    stripped = text.lstrip()
    if stripped.startswith("{") and "\n{" not in stripped.strip():
        obj = json.loads(stripped)
        if "results" in obj:                      # mwcp solve --json
            return rows_from_solve(obj["graph"], obj["results"], obj.get("timeout"), obj.get("seed", 0),
                                   obj["best"]["weight"] if obj.get("best") else None,
                                   bool(obj.get("complement")))
        return [obj]
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def rows_from_solve(graph: str, results: Iterable[dict], timeout: Optional[float], seed: int,
                    best_weight: Optional[int], complement: bool = False) -> List[dict]:
    rows = []
    for r in results:
        ok = r["status"] == "ok"
        rows.append({
            "graph_name": Path(graph).stem, "graph": str(graph), "seed": seed, "timeout": timeout,
            "solver": r["solver"], "status": r["status"], "weight": r.get("weight"),
            "proved_optimal": r.get("proved_optimal", False),
            "is_best": ok and best_weight is not None and r.get("weight") == best_weight,
            "gap": (best_weight - r["weight"]) if ok and best_weight is not None else None,
            "solver_time": r.get("solver_time"), "wall_time": r.get("wall_time"),
            "peak_rss_mb": r.get("peak_rss_mb"), "message": r.get("message", ""),
            "clique": r.get("clique") if ok else None, "complement": complement,
        })
    return rows


def _solver_order(rows: Sequence[dict]) -> List[str]:
    return solver_order([r["solver"] for r in rows])


def _colors(solvers: Sequence[str]) -> Dict[str, Tuple[str, str]]:
    return solver_colors(solvers)


class Metric:
    def __init__(self, key: str, name: str, fmt, tick, floor: float):
        self.key, self.name, self.fmt, self.tick, self.floor = key, name, fmt, tick, floor


class Stat:
    """One measure (wall time or peak memory) of one solver over a set of runs, plus outcome counts."""

    def __init__(self, solver: str, rows: List[dict], metric: "Metric"):
        self.solver = solver
        self.rows = rows
        self.metric = metric
        self.times = [r[metric.key] for r in rows if r.get(metric.key) is not None]
        self.n = len(rows)
        self.count = {k: sum(1 for r in rows if r["status"] == k) for k in ("ok", "timeout", "error", "invalid")}
        self.optimal = sum(1 for r in rows if r.get("proved_optimal"))
        self.best = sum(1 for r in rows if r.get("is_best"))
        timeouts = {r.get("timeout") for r in rows}
        self.timeout = timeouts.pop() if len(timeouts) == 1 else None

    @property
    def has_time(self) -> bool:
        return bool(self.times)

    @property
    def median(self) -> float:
        return statistics.median(self.times)

    @property
    def ran_to_limit(self) -> bool:
        """Every run used (nearly) the whole time limit: its time measures the limit, not speed."""
        return self.metric.key == "wall_time" and bool(self.timeout) and bool(self.times) and min(self.times) >= 0.95 * self.timeout

    def failures(self) -> str:
        parts = [f"{self.count[k]} {k}" for k in ("timeout", "error", "invalid") if self.count[k]]
        return ", ".join(parts)


# ---------------------------------------------------------------------------- scales

def _fmt_s(v: float) -> str:
    if v >= 100:
        return f"{v:,.0f} s"
    if v >= 10:
        return f"{v:.1f} s"
    if v >= 1:
        return f"{v:.2f} s"
    if v >= 0.001:
        return f"{v * 1000:.0f} ms" if v >= 0.01 else f"{v * 1000:.1f} ms"
    return "<1 ms"


def _fmt_mb(v: float) -> str:
    if v >= 1024:
        return f"{v / 1024:.2f} GiB" if v < 10240 else f"{v / 1024:.1f} GiB"
    if v >= 100:
        return f"{v:.0f} MiB"
    if v >= 10:
        return f"{v:.1f} MiB"
    return f"{v:.2f} MiB"


def _tick_mb(v: float) -> str:
    return f"{v:,g} MiB"


def _tick_label(v: float) -> str:
    if v < 1:
        return f"{v * 1000:g} ms"
    if v >= 1000:
        return f"{v / 1000:g}K s"
    return f"{v:g} s"


class Scale:
    def __init__(self, values: Sequence[float], x0: float, x1: float, extra: Sequence[float] = (),
                 floor: float = MIN_TIME):
        vals = [v for v in list(values) + list(extra) if v is not None]
        hi = max(vals) if vals else 1.0
        positive = [v for v in vals if v > 0]
        lo = min(positive) if positive else floor
        self.log = hi / max(lo, floor) > 100
        self.x0, self.x1 = x0, x1
        if self.log:
            self.lo = 10 ** math.floor(math.log10(max(lo, floor)))
            if max(lo, floor) < 2 * self.lo and self.lo > floor:
                self.lo /= 10   # keep the shortest bar visibly longer than zero
            top = max(hi, self.lo * 10)
            k = math.floor(math.log10(top))
            self.hi = next(m * 10 ** k for m in (1, 2, 5, 10) if m * 10 ** k >= top * (1 - 1e-9))
            k0, k1 = round(math.log10(self.lo)), math.floor(math.log10(self.hi) + 1e-9)
            self.ticks = [10.0 ** k for k in range(k0, k1 + 1)]
        else:
            step = _nice_step(hi / 5 if hi > 0 else 0.2)
            self.lo = 0.0
            self.hi = step * math.ceil(hi / step) if hi > 0 else step * 5
            self.ticks = [round(i * step, 10) for i in range(int(round(self.hi / step)) + 1)]

    def __call__(self, v: float) -> float:
        if self.log:
            v = min(max(v, self.lo), self.hi)
            t = (math.log10(v) - math.log10(self.lo)) / (math.log10(self.hi) - math.log10(self.lo))
        else:
            t = min(max(v, 0.0), self.hi) / self.hi
        return self.x0 + t * (self.x1 - self.x0)


def _nice_step(raw: float) -> float:
    k = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * k:
            return m * k
    return 10 * k


# ---------------------------------------------------------------------------- svg

def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _bar_path(x0: float, x1: float, y: float, h: float, r: float = 4.0) -> str:
    """Bar from the baseline x0 to x1: square at the baseline, 4px rounded data end."""
    w = max(x1 - x0, 1.0)
    r = min(r, w, h / 2)
    x1 = x0 + w
    return (f"M{x0:.1f},{y:.1f}H{x1 - r:.1f}Q{x1:.1f},{y:.1f} {x1:.1f},{y + r:.1f}"
            f"V{y + h - r:.1f}Q{x1:.1f},{y + h:.1f} {x1 - r:.1f},{y + h:.1f}H{x0:.1f}Z")


def _tip(stat: Stat, graph: Optional[str]) -> str:
    m = stat.metric
    lines = [stat.solver + (f" on {graph}" if graph else "")]
    if stat.has_time:
        lines.append(f"median {m.name} {m.fmt(stat.median)} over {len(stat.times)} run(s)")
        if len(stat.times) > 1:
            lines.append(f"min {m.fmt(min(stat.times))}, max {m.fmt(max(stat.times))}, "
                         f"mean {m.fmt(statistics.mean(stat.times))}")
    lines.append(f"found the best clique in {stat.best}/{stat.n}; proved optimal in {stat.optimal}/{stat.n}")
    weights = sorted({r["weight"] for r in stat.rows if r.get("weight") is not None})
    if weights:
        lines.append("weight " + (str(weights[0]) if len(weights) == 1 else f"{weights[0]} to {weights[-1]}"))
    if stat.failures():
        lines.append(stat.failures())
    if stat.ran_to_limit:
        lines.append("ran to the time limit: its time is the limit, not its speed")
    return "\n".join(lines)


def _axis(scale: Scale, top: float, bottom: float, tick) -> List[str]:
    out = []
    for t in scale.ticks:
        x = scale(t)
        out.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="{top:.1f}" y2="{bottom:.1f}"/>')
        out.append(f'<text class="tick" x="{x:.1f}" y="{bottom + 16:.1f}" text-anchor="middle">'
                   f'{_e(tick(t))}</text>')
    return out


def _timeout_line(scale: Scale, timeout: Optional[float], top: float, bottom: float) -> List[str]:
    if not timeout or timeout > scale.hi:
        return []
    x = scale(timeout)
    return [f'<line class="limit" x1="{x:.1f}" x2="{x:.1f}" y1="{top - 4:.1f}" y2="{bottom:.1f}"/>',
            f'<text class="tick" x="{x - 4:.1f}" y="{top - 8:.1f}" text-anchor="end">'
            f'time limit {_e(_fmt_s(timeout))}</text>']


def _limit(metric: Metric, timeout: Optional[float]) -> Optional[float]:
    return timeout if metric.key == "wall_time" else None


def chart_overall(stats: List[Stat], colors, timeout: Optional[float]) -> Tuple[str, bool]:
    stats = [s for s in stats if s.has_time]
    m = stats[0].metric
    limit = _limit(m, timeout)
    label_w = max(70, 8 * max(len(s.solver) for s in stats) + 16)

    def label(s: Stat) -> Tuple[str, str]:
        notes = [s.failures()] if s.failures() else []
        if s.ran_to_limit:
            notes.append("ran to limit")
        return m.fmt(s.median), ", ".join(notes)

    longest = max(len(v) + (len(n) + 3 if n else 0) for v, n in map(label, stats))
    x0, x1 = label_w, WIDTH - max(80, int(6.6 * longest) + 16)
    scale = Scale([s.median for s in stats], x0, x1, [limit] if limit else [], floor=m.floor)
    top, row = 24, BAR + 14
    bottom = top + row * len(stats)
    out = _axis(scale, top - 4, bottom, m.tick) + _timeout_line(scale, limit, top, bottom)
    for i, s in enumerate(stats):
        y = top + i * row + (row - BAR) / 2
        light, dark = colors[s.solver]
        value, note = label(s)
        out.append(
            f'<g class="mark" tabindex="0" data-tip="{_e(_tip(s, None))}" '
            f'aria-label="{_e(s.solver)}: median {_e(value)}">'
            f'<rect class="hit" x="0" y="{top + i * row:.1f}" width="{WIDTH}" height="{row}"/>'
            f'<text class="label" x="{x0 - 10}" y="{y + BAR / 2 + 4:.1f}" text-anchor="end">{_e(s.solver)}</text>'
            f'<path d="{_bar_path(x0, scale(s.median), y, BAR)}" style="--c:{light};--cd:{dark}"/>'
            f'<text class="value" x="{scale(s.median) + 8:.1f}" y="{y + BAR / 2 + 4:.1f}">{_e(value)}'
            + (f'<tspan class="note"> · {_e(note)}</tspan>' if note else "") + "</text></g>")
    height = bottom + 28
    return (f'<svg viewBox="0 0 {WIDTH} {height}" role="img" aria-label="Median {_e(m.name)} per solver">'
            + "".join(out) + "</svg>"), scale.log


def chart_per_graph(graphs: "OrderedDict[str, List[Stat]]", colors, timeout: Optional[float]) -> Tuple[str, bool]:
    m = next(s.metric for stats in graphs.values() for s in stats)
    limit = _limit(m, timeout)
    label_w = max(90, 7 * max(len(g) for g in graphs) + 20)
    x0, x1 = label_w, WIDTH - 90
    all_vals = [t for stats in graphs.values() for s in stats for t in s.times]
    scale = Scale(all_vals, x0, x1, [limit] if limit else [], floor=m.floor)
    top = 24
    out: List[str] = []
    y = top
    for g, stats in graphs.items():
        stats = [s for s in stats if s.has_time]
        if not stats:
            continue
        gh = len(stats) * BAR + (len(stats) - 1) * BAR_GAP
        out.append(f'<text class="label" x="{x0 - 10}" y="{y + gh / 2 + 4:.1f}" text-anchor="end">{_e(g)}</text>')
        for s in stats:
            light, dark = colors[s.solver]
            xm = scale(s.median)
            parts = [f'<rect class="hit" x="{x0}" y="{y - BAR_GAP / 2:.1f}" width="{WIDTH - x0}" '
                     f'height="{BAR + BAR_GAP}"/>',
                     f'<path d="{_bar_path(x0, xm, y, BAR)}" style="--c:{light};--cd:{dark}"/>']
            if len(s.times) > 1:
                a, b = scale(min(s.times)), scale(max(s.times))
                cy = y + BAR / 2
                parts.append(f'<path class="whisker" d="M{a:.1f},{cy - 4:.1f}V{cy + 4:.1f}M{a:.1f},{cy:.1f}'
                             f'H{b:.1f}M{b:.1f},{cy - 4:.1f}V{cy + 4:.1f}"/>')
            if s.failures():
                xr = max(xm, scale(max(s.times)))
                parts.append(f'<text class="note" x="{xr + 6:.1f}" y="{y + BAR / 2 + 4:.1f}">'
                             f'{_e(s.failures())}</text>')
            out.append(f'<g class="mark" tabindex="0" data-tip="{_e(_tip(s, g))}" '
                       f'aria-label="{_e(s.solver)} on {_e(g)}: median {_e(m.fmt(s.median))}">'
                       + "".join(parts) + "</g>")
            y += BAR + BAR_GAP
        y += GROUP_GAP - BAR_GAP
    bottom = y - GROUP_GAP + 8
    out = _axis(scale, top - 4, bottom, m.tick) + _timeout_line(scale, limit, top, bottom) + out
    return (f'<svg viewBox="0 0 {WIDTH} {bottom + 28:.0f}" role="img" '
            f'aria-label="{_e(m.name)} per solver for each graph">' + "".join(out) + "</svg>"), scale.log


def _legend(solvers: Sequence[str], colors) -> str:
    items = "".join(f'<span class="key"><i style="--c:{colors[s][0]};--cd:{colors[s][1]}"></i>{_e(s)}</span>'
                    for s in solvers)
    return f'<div class="legend">{items}</div>'


def _table(rows: List[dict], solvers: Sequence[str]) -> str:
    order = {s: i for i, s in enumerate(solvers)}
    rows = sorted(rows, key=lambda r: (str(r.get("graph_name")), r.get("seed") or 0, order.get(r["solver"], 99)))
    head = ["graph", "seed", "solver", "status", "weight", "gap", "optimal", "wall time", "solver time",
            "peak memory"]
    body = []
    for r in rows:
        cells = [r.get("graph_name", ""), r.get("seed", ""), r["solver"], r["status"],
                 "" if r.get("weight") is None else r["weight"], "" if r.get("gap") is None else r["gap"],
                 "yes" if r.get("proved_optimal") else "",
                 "" if r.get("wall_time") is None else _fmt_s(r["wall_time"]),
                 "" if r.get("solver_time") is None else _fmt_s(r["solver_time"]),
                 "" if r.get("peak_rss_mb") is None else _fmt_mb(r["peak_rss_mb"])]
        body.append("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in cells) + "</tr>")
    return ("<table><thead><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr></thead><tbody>"
            + "".join(body) + "</tbody></table>")


CSS = """
svg .tick,svg .note{fill:var(--text2)}svg .value{font-variant-numeric:tabular-nums}
path[style]{fill:var(--c)}.grid{stroke:var(--grid);stroke-width:1}
.limit{stroke:var(--limit);stroke-width:1;stroke-dasharray:4 3}
.whisker{stroke:var(--text);stroke-width:1.5;fill:none;opacity:.7}
.hit{fill:transparent}.mark:hover .hit,.mark:focus .hit{fill:var(--grid);opacity:.5}.mark:focus{outline:none}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:12px 0 0}
.key{display:inline-flex;align-items:center;gap:6px;font-size:13px}
.key i{width:12px;height:12px;border-radius:3px;background:var(--c);display:inline-block}
""" + dark([("path[style]", "fill:var(--cd)"), (".key i", "background:var(--cd)")])

JS = "bindTips(document);"


TIME = Metric("wall_time", "wall time", _fmt_s, _tick_label, MIN_TIME)
MEMORY = Metric("peak_rss_mb", "peak memory", _fmt_mb, _tick_mb, MIN_MEM)


def render_report(rows: List[dict], title: str = "Solver performance") -> str:
    rows = [r for r in rows if r.get("status") != "unavailable"]
    if not rows:
        raise ValueError("no solver results to plot")
    solvers = _solver_order(rows)
    colors = _colors(solvers)
    timeouts = {r.get("timeout") for r in rows}
    timeout = timeouts.pop() if len(timeouts) == 1 else None
    graph_names = list(OrderedDict.fromkeys(str(r.get("graph_name", "")) for r in rows))
    seeds = sorted({r.get("seed") for r in rows if r.get("seed") is not None})
    n_graphs = len(graph_names)
    n_runs = len({(r.get("graph_name"), r.get("seed")) for r in rows})

    def overall(metric):
        return [Stat(s, [r for r in rows if r["solver"] == s], metric) for s in solvers]

    def per_graph(metric):
        out: "OrderedDict[str, List[Stat]]" = OrderedDict()
        for g in graph_names:
            g_rows = [r for r in rows if str(r.get("graph_name", "")) == g]
            out[g] = [Stat(s, [r for r in g_rows if r["solver"] == s], metric) for s in solvers
                      if any(r["solver"] == s for r in g_rows)]
        return out

    sub = (f"{n_graphs} graph{'s' if n_graphs != 1 else ''} × {len(seeds) or 1} seed"
           f"{'s' if len(seeds) > 1 else ''}" + (f", time limit {_fmt_s(timeout)}" if timeout else "")
           + ". Wall time and peak memory (RSS) of each solver process, measured by mwcp."
           " Hover a bar for details.")
    runs_txt = f'Over {"all " if n_runs > 1 else ""}{n_runs} run{"s" if n_runs != 1 else ""} (graph × seed).'
    seeds_txt = (f'Bar: median over seeds{"; whisker: lowest to highest seed" if len(seeds) > 1 else ""}.')

    parts = [f"<h1>{_e(title)}</h1>", f'<p class="sub">{_e(sub)}</p>', _legend(solvers, colors)]
    for metric, heading in ((TIME, "wall time"), (MEMORY, "peak memory")):
        stats = overall(metric)
        if not any(s.has_time for s in stats):
            if metric is MEMORY:
                parts.append('<p class="foot" style="margin-top:20px">No memory measurements in these '
                             'results (recorded from mwcp 0.3 on).</p>')
            continue
        svg, log = chart_overall(stats, colors, timeout)
        parts += [f"<h2>Median {heading} per solver</h2>",
                  f'<p class="foot">{runs_txt}{" Log scale." if log else ""}</p>', svg]
        if metric is TIME:
            limited = [s.solver for s in stats if s.ran_to_limit]
            if limited:
                parts.append(f'<p class="foot">{_e(", ".join(limited))} ran until the time limit in every run, '
                             f'so {"its" if len(limited) == 1 else "their"} time shows the limit, not speed.</p>')
    if n_graphs > 1:
        for metric, heading in ((TIME, "Wall time"), (MEMORY, "Peak memory")):
            graphs = per_graph(metric)
            if not any(s.has_time for st in graphs.values() for s in st):
                continue
            svg, log = chart_per_graph(graphs, colors, timeout)
            parts += [f"<h2>{heading} per graph</h2>",
                      f'<p class="foot">{seeds_txt}{" Log scale." if log else ""}</p>', svg]
    if any(r["status"] in ("timeout", "error", "invalid") for r in rows):
        parts.append('<p class="foot" style="margin-top:16px">Timed-out and failed runs are included, '
                     'measured up to the moment they were stopped.</p>')
    parts.append(f"<details><summary>Table: all {len(rows)} results</summary>{_table(rows, solvers)}</details>")
    return page(title, CSS, "".join(parts), JS)


def write_report(rows: List[dict], path: Path, title: str = "Solver performance") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(rows, title))
    return path
