import subprocess

import pytest

from mwcp import BIN_DIR
from mwcp.graph import read_metis

from .conftest import random_graph, write_metis

TOOL = BIN_DIR / "metis_tool"
pytestmark = pytest.mark.skipif(not TOOL.is_file(), reason="metis_tool not built")


def run(*args):
    subprocess.run([str(TOOL), *map(str, args)], check=True, capture_output=True)


@pytest.mark.parametrize("n,p", [(1, 0.0), (15, 0.3), (30, 0.9)])
def test_complement_roundtrip(tmp_path, n, p):
    w, e = random_graph(n, p, seed=7)
    src = write_metis(tmp_path / "g.graph", w, e)
    run("complement", src, tmp_path / "c.graph")
    run("complement", tmp_path / "c.graph", tmp_path / "cc.graph")
    g, c, cc = (read_metis(tmp_path / f) for f in ("g.graph", "c.graph", "cc.graph"))
    assert c.weights == g.weights and c.m == n * (n - 1) // 2 - g.m
    assert all(c.adj[v] == set(range(n)) - g.adj[v] - {v} for v in range(n))
    assert cc.adj == g.adj and cc.weights == g.weights
    # KaMIS needs sorted adjacency lists.
    for line in (tmp_path / "c.graph").read_text().splitlines()[1:]:
        nbrs = list(map(int, line.split()[1:]))
        assert nbrs == sorted(nbrs)


@pytest.mark.parametrize("complement", [False, True])
def test_openpls_format(tmp_path, complement):
    w, e = random_graph(12, 0.4, seed=3)
    src = write_metis(tmp_path / "g.graph", w, e)
    out = tmp_path / "o.graph"
    run("openpls", src, out, *(["--complement"] if complement else []))
    lines = out.read_text().split("\n")
    assert all(not l.endswith(" ") for l in lines)               # OpenPLS's reader is strict
    want = read_metis(src, complement=complement)
    got = read_metis(out)                                         # unweighted METIS
    assert all(got.adj[v] == {u for u in range(12) if want.has_edge(v, u)} for v in range(12))
    pairs = [l.split() for l in (tmp_path / "o.graph.weights").read_text().splitlines()]
    assert [int(b) for _, b in pairs] == w and [int(a) for a, _ in pairs] == list(range(12))
