"""Clique view: draw the MWC graph with each solver's clique highlighted.

Writes a self-contained interactive HTML page (inline SVG, layout computed in the page, no
dependencies) and a Graphviz DOT file of the same view; when Graphviz is installed the DOT is
also rendered to SVG.

Graphs that are too big to draw legibly get a reduced view: every clique vertex, plus the other
vertices adjacent to the most best-clique vertices (the "almost in the clique" ones), up to
`max_vertices`, and edges up to `max_edges`, edges at the cliques first. The page says what
was left out. Edges are those of the graph the cliques live in, i.e. the complement of the
file with --complement.
"""
from __future__ import annotations

import html
import json
import math
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .graph import Graph
from .style import dark, page, solver_colors, solver_order

MAX_VERTICES = 300
MAX_EDGES = 4000


@dataclass
class View:
    n_total: int
    m_total: int
    complemented: bool
    vertices: List[int]                      # graph vertex ids, in drawing order
    weights: List[int]
    edges: List[Tuple[int, int]]             # pairs of indices into `vertices`
    cliques: Dict[str, List[int]]            # solver -> indices into `vertices`
    full: bool
    hidden_edges: int = 0                    # edges between drawn vertices left out (edge budget)
    edges_among_drawn: int = 0               # all edges between drawn vertices
    best: Optional[str] = None
    info: Dict[str, dict] = field(default_factory=dict)  # solver -> weight/size/optimal
    hits: List[int] = field(default_factory=list)        # per vertex: best-clique vertices adjacent
    pos: List[Tuple[float, float]] = field(default_factory=list)  # layout, px
    width: float = 760.0
    height: float = 560.0

    @property
    def hidden_vertices(self) -> int:
        return self.n_total - len(self.vertices)


def best_solver(results: Sequence[dict]) -> Optional[str]:
    """Highest weight wins; on ties prefer one that proved optimality (as in runner.solve_graph)."""
    ok = [r for r in results if r.get("status") == "ok" and r.get("clique")]
    if not ok:
        return None
    return max(ok, key=lambda r: (r["weight"], bool(r.get("proved_optimal")))).get("solver")


def build_view(graph: Graph, results: Sequence[dict], max_vertices: int = MAX_VERTICES,
               max_edges: int = MAX_EDGES) -> View:
    """`results`: dicts with solver, status, weight, clique (0-based), proved_optimal."""
    ok = [r for r in results if r.get("status") == "ok" and r.get("clique")]
    if not ok:
        raise ValueError("no solver returned a clique to draw")
    order = solver_order([r["solver"] for r in ok])
    by_solver = {r["solver"]: r for r in ok}
    best = best_solver(ok)
    cliques = {s: sorted(set(by_solver[s]["clique"])) for s in order}
    members = sorted({v for c in cliques.values() for v in c})
    member_set = set(members)

    best_set = cliques[best]
    k = len(best_set)
    hits = [0] * graph.n                     # best-clique vertices adjacent in the *file*
    for u in best_set:
        for v in graph.adj[u]:
            hits[v] += 1
    if graph.complemented:                   # adjacent in H = not adjacent in the file
        in_best = set(best_set)
        hits = [k - h - (1 if v in in_best else 0) for v, h in enumerate(hits)]

    full = graph.n <= max_vertices and graph.m <= max_edges
    if full:
        verts = members + [v for v in range(graph.n) if v not in member_set]
    else:
        others = sorted((v for v in range(graph.n) if v not in member_set),
                        key=lambda v: (-hits[v], -graph.weights[v], v))
        verts = members + others[:max(0, max_vertices - len(members))]
    index = {v: i for i, v in enumerate(verts)}

    edges: List[Tuple[int, int, int]] = []    # (tier, i, j): 0 both in cliques, 1 one, 2 none
    vset = set(verts)
    if graph.complemented:
        for a in range(len(verts)):
            u = verts[a]
            for b in range(a + 1, len(verts)):
                if verts[b] not in graph.adj[u]:
                    edges.append((0, a, b))
    else:
        for u in verts:
            for v in graph.adj[u]:
                if v in vset and u < v:
                    edges.append((0, index[u], index[v]))
    tiered = []
    for _, a, b in edges:
        t = (verts[a] not in member_set) + (verts[b] not in member_set)
        tiered.append((t, a, b))
    tiered.sort()
    keep = [e for e in tiered if e[0] == 0]                       # clique-area edges always kept
    keep += [e for e in tiered if e[0] > 0][:max(0, max_edges - len(keep))]
    info = {s: {"weight": by_solver[s]["weight"], "size": len(cliques[s]),
                "proved_optimal": bool(by_solver[s].get("proved_optimal"))} for s in order}
    view = View(n_total=graph.n, m_total=graph.m, complemented=graph.complemented, vertices=verts,
                weights=[graph.weights[v] for v in verts], edges=[(a, b) for _, a, b in keep],
                cliques={s: [index[v] for v in c] for s, c in cliques.items()}, full=full,
                hidden_edges=len(tiered) - len(keep), edges_among_drawn=len(tiered), best=best, info=info,
                hits=[hits[v] for v in verts])
    radial_layout(view)
    return view


SPACING = 18.0   # px between neighboring vertices on a ring
WIDTH = 760.0


def radial_layout(view: View) -> None:
    """Clique vertices on a center ring; every other vertex on an outer ring, closer the more
    best-clique vertices it is adjacent to, and turned toward the ring vertices it connects to.
    Deterministic, and readable even for dense graphs where force layouts give a hairball."""
    n = len(view.vertices)
    best = view.cliques[view.best]
    ring = list(dict.fromkeys(best + [v for c in view.cliques.values() for v in c]))
    in_ring = set(ring)
    r_in = max(40.0, len(ring) * SPACING * 1.4 / (2 * math.pi))
    pos: List[Tuple[float, float]] = [(0.0, 0.0)] * n
    angle = {}
    for i, v in enumerate(ring):
        a = 2 * math.pi * i / len(ring) - math.pi / 2
        angle[v] = a
        pos[v] = (r_in * math.cos(a), r_in * math.sin(a))

    nbr_angles: Dict[int, List[float]] = {}
    for a, b in view.edges:
        if a in in_ring and b not in in_ring:
            nbr_angles.setdefault(b, []).append(angle[a])
        elif b in in_ring and a not in in_ring:
            nbr_angles.setdefault(a, []).append(angle[b])

    def preferred(v: int) -> float:
        angs = nbr_angles.get(v)
        if not angs:
            return (view.vertices[v] * 2.399963) % (2 * math.pi)     # golden angle spread
        return math.atan2(sum(math.sin(t) for t in angs), sum(math.cos(t) for t in angs)) % (2 * math.pi)

    others = sorted((v for v in range(n) if v not in in_ring),
                    key=lambda v: (-view.hits[v], -view.weights[v], view.vertices[v]))
    r = r_in
    i = 0
    while i < len(others):
        r += SPACING * 1.15
        cap = max(1, int(2 * math.pi * r / SPACING))
        chunk = sorted(others[i:i + cap], key=preferred)
        offset = preferred(chunk[0])
        for j, v in enumerate(chunk):
            a = offset + 2 * math.pi * j / len(chunk)
            pos[v] = (r * math.cos(a), r * math.sin(a))
        i += cap
    r_max = r + 36                                  # room for labels
    scale = min(1.6, (WIDTH / 2) / r_max)
    view.width = WIDTH
    view.height = round(2 * r_max * scale, 1)
    cx, cy = WIDTH / 2, view.height / 2
    view.pos = [(round(cx + x * scale, 1), round(cy + y * scale, 1)) for x, y in pos]


# ---------------------------------------------------------------------------- HTML

CSS = """
.picks{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 6px}
.pick{font:inherit;font-size:13px;display:inline-flex;align-items:center;gap:7px;padding:5px 11px;
  border:1px solid var(--grid);border-radius:999px;background:var(--surface);color:var(--text);cursor:pointer}
.pick[aria-pressed="true"]{border-color:var(--text);box-shadow:inset 0 0 0 1px var(--text)}
.pick i{width:11px;height:11px;border-radius:50%;background:var(--c);display:inline-block}
.pick small{color:var(--text2);font-size:12px}
.tag{font-size:11px;color:var(--text2);border:1px solid var(--grid);border-radius:4px;padding:0 4px}
#g{--sel:var(--sl)}
#g line{stroke:var(--text2);stroke-width:.6;stroke-opacity:var(--eo)}
#g line.in{stroke:var(--sel);stroke-width:2.2;stroke-opacity:1}
#g circle{fill:var(--node);stroke:var(--surface);stroke-width:1.5}
#g circle.in{fill:var(--sel)}
#g circle.best{stroke:var(--text);stroke-width:2;stroke-dasharray:3 2}
#g .mark{cursor:default}#g .mark:focus{outline:none}#g .mark:focus circle,#g .mark:hover circle{stroke:var(--text)}
#g text{font-size:11px;fill:var(--text);paint-order:stroke;stroke:var(--surface);stroke-width:3px;pointer-events:none}
.note{color:var(--text2);font-size:13px;margin:4px 0}
td.ids{font-family:ui-monospace,Menlo,monospace;font-size:11px;word-break:break-word}
""" + dark([(".pick i", "background:var(--cd)"), ("#g", "--sel:var(--sd)")])

JS = r"""
const D=JSON.parse(document.getElementById('data').textContent);
const N=D.w.length, svg=document.getElementById('g');
svg.setAttribute('viewBox',`0 0 ${D.W} ${D.H}`);
svg.style.setProperty('--eo',Math.min(0.7,Math.max(0.08,400/Math.max(D.e.length,1))).toFixed(2));
D.cs={};for(const s in D.c)D.cs[s]=new Set(D.c[s]);
const adj=D.e, px=v=>D.p[v][0], py=v=>D.p[v][1];
const wmax=Math.max(...D.w,1), rad=v=>3+6*Math.sqrt(Math.max(D.w[v],0)/wmax);
const NS='http://www.w3.org/2000/svg', mk=(t,a)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e;};
const gE=mk('g',{}), gN=mk('g',{}), gL=mk('g',{}); svg.append(gE,gN,gL);
const lines=adj.map(([a,b])=>{const l=mk('line',{x1:px(a).toFixed(1),y1:py(a).toFixed(1),x2:px(b).toFixed(1),y2:py(b).toFixed(1)});gE.append(l);return l;});
const circles=[];
for(let v=0;v<N;v++){
  const g=mk('g',{class:'mark',tabindex:'0'});
  const inC=Object.keys(D.c).filter(s=>D.cs[s].has(v));
  g.dataset.tip=`vertex ${D.id[v]} (METIS line ${D.id[v]+1})\nweight ${D.w[v]}\n`+
    (inC.length?`in the clique of: ${inC.join(', ')}`:
      `adjacent to ${D.h[v]} of the ${D.k} best-clique vertices`);
  g.setAttribute('aria-label',`vertex ${D.id[v]}, weight ${D.w[v]}`);
  const c=mk('circle',{cx:px(v).toFixed(1),cy:py(v).toFixed(1),r:rad(v).toFixed(1)});
  g.append(c);gN.append(g);circles.push(c);}
bindTips(svg);
function pick(sol){
  const C=D.cs[sol], B=D.cs[D.best], col=D.col[sol];
  svg.style.setProperty('--sl',col[0]);svg.style.setProperty('--sd',col[1]);
  circles.forEach((c,v)=>{c.classList.toggle('in',C.has(v));c.classList.toggle('best',sol!==D.best&&B.has(v)&&!C.has(v));});
  lines.forEach((l,i)=>{const [a,b]=adj[i];l.classList.toggle('in',C.has(a)&&C.has(b));});
  gE.append(...lines.filter(l=>l.classList.contains('in')));       // clique edges on top
  gL.textContent='';
  if(C.size<=40) C.forEach(v=>{gL.append(Object.assign(mk('text',{x:(px(v)+rad(v)+3).toFixed(1),y:(py(v)+4).toFixed(1)}),{textContent:D.w[v]}));});
  document.querySelectorAll('.pick').forEach(b=>b.setAttribute('aria-pressed',b.dataset.s===sol));
  document.getElementById('bestnote').style.display=sol===D.best?'none':'';}
document.querySelectorAll('.pick').forEach(b=>b.addEventListener('click',()=>pick(b.dataset.s)));
pick(D.best);
"""


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def render_html(view: View, title: str, subtitle: str = "") -> str:
    solvers = list(view.cliques)
    colors = solver_colors(solvers)
    data = {"w": view.weights, "id": view.vertices, "e": view.edges, "c": view.cliques,
            "col": colors, "best": view.best, "p": view.pos, "W": view.width, "H": view.height,
            "h": view.hits, "k": len(view.cliques[view.best])}
    what = "complement of the input file" if view.complemented else "input graph"
    head = [f"<h1>{_e(title)}</h1>",
            f'<p class="sub">{_e(subtitle + " · " if subtitle else "")}MWC graph: {_e(what)}, '
            f"{view.n_total:,} vertices, {view.m_total:,} edges. Cliques sit on the center ring; other "
            f"vertices sit closer the more best-clique vertices they are adjacent to. Vertex size follows "
            f"weight; hover a vertex for details.</p>"]
    if view.full:
        head.append('<p class="note">Whole graph shown.</p>')
    else:
        parts = [f"Showing {len(view.vertices):,} of {view.n_total:,} vertices: every clique vertex, then the "
                 f"vertices adjacent to the most vertices of the best clique"]
        if view.hidden_edges:
            parts.append(f"{view.hidden_edges:,} of the {view.edges_among_drawn:,} edges between the shown "
                         f"vertices are hidden, keeping those at the cliques first")
        head.append(f'<p class="note">{_e("; ".join(parts))}.</p>')
    buttons = []
    for s in solvers:
        i = view.info[s]
        tags = ("<span class=\"tag\">best</span>" if s == view.best else "") + \
               ("<span class=\"tag\">proved optimal</span>" if i["proved_optimal"] else "")
        buttons.append(f'<button class="pick" data-s="{_e(s)}" aria-pressed="false" '
                       f'style="--c:{colors[s][0]};--cd:{colors[s][1]}"><i></i>{_e(s)} '
                       f'<small>weight {i["weight"]:,} · {i["size"]} vertices</small>{tags}</button>')
    head.append(f'<div class="picks" role="group" aria-label="Show the clique of">{"".join(buttons)}</div>')
    head.append(f'<p class="note" id="bestnote">Dashed outline: vertices of the best clique '
                f'({_e(view.best)}) that this clique misses.</p>')
    rows = "".join(
        f"<tr><td>{_e(s)}</td><td>{view.info[s]['weight']:,}</td><td>{view.info[s]['size']}</td>"
        f"<td>{'yes' if view.info[s]['proved_optimal'] else ''}</td>"
        f"<td class=\"ids\">{_e(', '.join(str(view.vertices[v]) for v in sorted(view.cliques[s], key=lambda v: view.vertices[v])))}</td></tr>"
        for s in solvers)
    table = ("<details><summary>Table: each solver's clique (0-based vertex ids)</summary><table><thead><tr>"
             "<th>solver</th><th>weight</th><th>size</th><th>optimal</th><th>vertices</th></tr></thead>"
             f"<tbody>{rows}</tbody></table></details>")
    body = ("".join(head) + '<svg id="g" role="img" aria-label="Graph with the selected clique highlighted"></svg>'
            + table + f'<script type="application/json" id="data">{json.dumps(data, separators=(",", ":"))}</script>')
    return page(title, CSS, body, JS)


# ---------------------------------------------------------------------------- DOT

def render_dot(view: View, solver: Optional[str] = None) -> str:
    """The same view as DOT, with `solver`'s clique (default: the best) filled in its color."""
    solver = solver or view.best
    color = solver_colors(list(view.cliques))[solver][0]
    clique = set(view.cliques[solver])
    wmax = max(view.weights) or 1
    small = len(view.vertices) <= 60
    # Same sizes as the HTML: positions are px = points, widths are inches (72 points).
    alpha = min(0.7, max(0.08, 400 / max(len(view.edges), 1)))
    out = [f"// {solver} clique: weight {view.info[solver]['weight']}, {len(clique)} vertices; "
           f"{len(view.vertices)} of {view.n_total} vertices, {len(view.edges)} edges shown",
           "graph mwc {",
           '  // Positions are pinned (pos); render with: neato -n2 -Tsvg file.dot -o file.svg',
           '  graph [outputorder=edgesfirst, splines=false, bgcolor="white", pad=0.2];',
           '  node [shape=circle, style=filled, fillcolor="#b8b8b8", color="#ffffff", penwidth=1, '
           'fontname="Helvetica", fontsize=9, fontcolor="#191919", fixedsize=true];',
           f'  edge [color="#666666{int(alpha * 255):02x}", penwidth=0.6];']
    for i, (v, w) in enumerate(zip(view.vertices, view.weights)):
        diameter = 2 * (3 + 6 * (max(w, 0) / wmax) ** 0.5)
        if small:
            diameter = max(diameter, 20)          # room for the id inside
        x, y = view.pos[i]
        attrs = [f"width={diameter / 72:.3f}", f'pos="{x:.1f},{view.height - y:.1f}"',
                 f'tooltip="vertex {v}, weight {w}"', f'label="{v}"' if small else 'label=""']
        if i in clique:
            attrs += [f'fillcolor="{color}"', f'xlabel="{w}"']
        out.append(f"  v{v} [{', '.join(attrs)}];")
    inside = [(a, b) for a, b in view.edges if a in clique and b in clique]
    for a, b in view.edges:
        if not (a in clique and b in clique):
            out.append(f"  v{view.vertices[a]} -- v{view.vertices[b]};")
    for a, b in inside:                           # last, so they draw on top
        out.append(f'  v{view.vertices[a]} -- v{view.vertices[b]} [color="{color}", penwidth=2.2];')
    out.append("}")
    return "\n".join(out) + "\n"


def render_svg(dot_path: Path, svg_path: Path, n_vertices: int,
               log: Callable[[str], None] = lambda m: None) -> bool:
    """Render with Graphviz if installed, keeping the DOT's positions (neato -n2). Never raises."""
    tool = shutil.which("neato")
    if not tool:
        log("note: Graphviz (neato) not found, so no SVG; the .html and .dot were written")
        return False
    try:
        p = subprocess.run([tool, "-n2", "-Tsvg", str(dot_path), "-o", str(svg_path)],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"warning: Graphviz failed on {dot_path.name}: {e}")
        return False
    if p.returncode != 0:
        log(f"warning: Graphviz failed on {dot_path.name}: {p.stderr.strip()[:200]}")
        return False
    return True


def write_clique_view(graph: Graph, results: Sequence[dict], path: Path, title: str, subtitle: str = "",
                      max_vertices: int = MAX_VERTICES, max_edges: int = MAX_EDGES,
                      log: Callable[[str], None] = lambda m: None) -> List[Path]:
    """Write PATH (.html), PATH.dot and, with Graphviz, PATH.svg. Returns the files written."""
    view = build_view(graph, results, max_vertices, max_edges)
    path = Path(path)
    if path.suffix.lower() != ".html":
        path = path.with_suffix(".html")
    path.parent.mkdir(parents=True, exist_ok=True)
    dot, svg = path.with_suffix(".dot"), path.with_suffix(".svg")
    path.write_text(render_html(view, title, subtitle))
    dot.write_text(render_dot(view))
    written = [path, dot]
    if render_svg(dot, svg, len(view.vertices), log):
        written.append(svg)
    return written
