import json
import re

import pytest

from mwcp.cli import main
from mwcp.graph import read_metis
from mwcp.solvers import REGISTRY
from mwcp.viz import build_view, render_dot, render_html, write_clique_view

from .conftest import random_graph, write_metis


def _greedy(g, start):
    c = [start]
    for v in sorted(range(g.n), key=lambda v: -g.weights[v]):
        if v not in c and all(g.has_edge(v, u) for u in c):
            c.append(v)
    return sorted(c)


def _results(g, best, other):
    return [{"solver": "wlmc", "status": "ok", "weight": g.weight_of(best), "clique": best,
             "proved_optimal": True},
            {"solver": "openpls", "status": "ok", "weight": g.weight_of(other), "clique": other},
            {"solver": "kamis_br", "status": "timeout", "weight": None, "clique": []},
            {"solver": "kamis_ls", "status": "unavailable", "weight": None, "clique": []}]


def test_small_graph_drawn_whole(data_dir):
    g = read_metis(data_dir / "k4_heavy_triangle.graph")
    view = build_view(g, _results(g, [4, 5, 6], [0, 1]))
    assert view.full and sorted(view.vertices) == list(range(g.n)) and len(view.edges) == g.m
    assert view.best == "wlmc" and set(view.cliques) == {"wlmc", "openpls"}
    tri = {view.vertices[i] for i in view.cliques["wlmc"]}
    assert tri == {4, 5, 6}
    assert len(view.pos) == g.n and all(0 <= x <= view.width and 0 <= y <= view.height for x, y in view.pos)


def test_large_graph_reduced_view(tmp_path):
    w, e = random_graph(1500, 0.3, seed=4)
    g = read_metis(write_metis(tmp_path / "big.graph", w, e))
    best, other = _greedy(g, 0), _greedy(g, 7)
    view = build_view(g, _results(g, best, other), max_vertices=200, max_edges=1500)
    assert not view.full and len(view.vertices) == 200
    shown = set(view.vertices)
    assert set(best) <= shown and set(other) <= shown
    assert len(view.edges) <= 1500 and view.hidden_edges == view.edges_among_drawn - len(view.edges) > 0
    # Every edge inside a clique survives the edge budget.
    inside = {(a, b) for a, b in view.edges}
    idx = view.cliques["wlmc"]
    assert all((a, b) in inside or (b, a) in inside for i, a in enumerate(idx) for b in idx[i + 1:])
    # The vertices left out are no closer to the best clique than the ones drawn.
    members = set(best) | set(other)
    drawn_hits = [h for v, h in zip(view.vertices, view.hits) if v not in members]
    left_out = [sum(g.has_edge(u, v) for u in best) for v in range(g.n) if v not in shown]
    assert min(drawn_hits) >= max(left_out)
    # Edges are real edges of the graph.
    assert all(g.has_edge(view.vertices[a], view.vertices[b]) for a, b in view.edges)


def test_complement_draws_h_not_the_file(tmp_path):
    w, e = random_graph(30, 0.7, seed=5)
    path = write_metis(tmp_path / "c.graph", w, e)
    h = read_metis(path, complement=True)
    clique = _greedy(h, 0)
    view = build_view(h, _results(h, clique, _greedy(h, 3)))
    assert view.complemented and view.full and len(view.edges) == h.m
    file_g = read_metis(path)
    assert all(not file_g.has_edge(view.vertices[a], view.vertices[b]) for a, b in view.edges)


def test_dot_and_html(data_dir):
    g = read_metis(data_dir / "k4_heavy_triangle.graph")
    view = build_view(g, _results(g, [4, 5, 6], [0, 1]))
    dot = render_dot(view)
    assert dot.count("{") == dot.count("}") == 1 and "graph mwc {" in dot
    assert len(re.findall(r'fillcolor="#257de0"', dot)) == 3      # the 3 best-clique vertices
    assert dot.count("penwidth=2.2") == 3                           # triangle edges
    assert all(f"v{v} [" in dot for v in range(g.n)) and dot.count("pos=") == g.n
    page = render_html(view, "T")
    assert 'data-s="wlmc"' in page and 'data-s="openpls"' in page
    assert 'data-s="kamis_br"' not in page and 'data-s="kamis_ls"' not in page
    data = json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', page).group(1))
    assert data["best"] == "wlmc" and len(data["p"]) == g.n


def test_no_clique_raises(data_dir):
    g = read_metis(data_dir / "k4_heavy_triangle.graph")
    with pytest.raises(ValueError):
        build_view(g, [{"solver": "wlmc", "status": "error", "clique": []}])


def test_write_clique_view_files(tmp_path, data_dir):
    g = read_metis(data_dir / "k4_heavy_triangle.graph")
    files = write_clique_view(g, _results(g, [4, 5, 6], [0, 1]), tmp_path / "v", title="T")
    assert {f.name for f in files} == {"v.html", "v.dot", "v.svg"}      # Graphviz is in the image
    assert "<svg" in (tmp_path / "v.svg").read_text()


def test_draw_command_from_saved_results(tmp_path, data_dir):
    rows = [{"graph_name": "k4", "graph": "/elsewhere/k4.graph", "seed": s, "complement": False,
             "solver": "wlmc", "status": "ok", "weight": 30, "clique": [4, 5, 6], "proved_optimal": True}
            for s in (0, 1)]
    (tmp_path / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    g = str(data_dir / "k4_heavy_triangle.graph")
    assert main(["draw", str(tmp_path), "--graph", g, "--seed", "1"]) == 0
    assert (tmp_path / "k4.s1.html").is_file() and (tmp_path / "k4.s1.dot").is_file()
    assert main(["draw", str(tmp_path), "--graph", g]) == 0                     # both seeds
    assert (tmp_path / "cliques" / "k4.s0.html").is_file() and (tmp_path / "cliques" / "k4.s1.html").is_file()
    assert main(["draw", str(tmp_path)]) == 1                                   # recorded path missing
    assert main(["draw", str(tmp_path), "--seed", "9"]) == 2


@pytest.mark.skipif(not REGISTRY["wlmc"].available(), reason="wlmc not built")
def test_solve_and_batch_draw(tmp_path, data_dir):
    g = data_dir / "k4_heavy_triangle.graph"
    assert main(["solve", str(g), "-s", "wlmc,fastwclq", "-t", "1", "-q", "--draw", str(tmp_path / "v.html")]) == 0
    assert "Cliques: k4_heavy_triangle.graph" in (tmp_path / "v.html").read_text()
    out = tmp_path / "out"
    assert main(["batch", str(g), "-s", "wlmc", "-t", "1", "--seeds", "0,1", "-o", str(out), "--draw", "-q"]) == 0
    assert sorted(p.name for p in (out / "cliques").glob("*.html")) == \
        ["k4_heavy_triangle.s0.html", "k4_heavy_triangle.s1.html"]
