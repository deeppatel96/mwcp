import pytest

from mwcp.graph import read_metis
from mwcp.result import Status
from mwcp.solvers import REGISTRY

from .conftest import brute_force_mwc, random_graph, write_metis

SOLVERS = list(REGISTRY.values())
ids = [s.name for s in SOLVERS]


def _require(solver):
    if not solver.available():
        pytest.skip(f"{solver.binary} not built (run `mwcp build`)")


@pytest.mark.parametrize("solver", SOLVERS, ids=ids)
def test_known_instance(solver, data_dir):
    _require(solver)
    path = data_dir / "k4_heavy_triangle.graph"
    r = solver.run(path, read_metis(path), timeout=2)
    assert r.status == Status.OK, r.message
    assert r.weight == 30 and r.clique == [4, 5, 6]


@pytest.mark.parametrize("solver", SOLVERS, ids=ids)
def test_isolated_vertex_wins(solver, tmp_path):
    _require(solver)
    path = write_metis(tmp_path / "iso.graph", [3, 3, 3, 100], [(0, 1), (1, 2), (0, 2)])
    r = solver.run(path, read_metis(path), timeout=2)
    assert r.status == Status.OK, r.message
    assert r.weight == 100 and r.clique == [3]


# Mix of sparse and dense graphs (the wrapper is fed complement graphs, which are often dense).
CASES = [(n, p, seed) for n, p in [(12, 0.2), (18, 0.5), (22, 0.8), (25, 0.95)] for seed in range(4)]


@pytest.mark.parametrize("solver", SOLVERS, ids=ids)
@pytest.mark.parametrize("n,p,seed", CASES)
def test_random_against_brute_force(solver, tmp_path, n, p, seed):
    _require(solver)
    weights, edges = random_graph(n, p, seed)
    path = write_metis(tmp_path / f"r{n}_{seed}.graph", weights, edges)
    g = read_metis(path)
    opt = brute_force_mwc(g)
    r = solver.run(path, g, timeout=1)
    assert r.status == Status.OK, r.message      # also checks it's a real clique with the right weight
    if solver.exact:
        assert r.proved_optimal and r.weight == opt
    else:
        assert r.weight <= opt
        if r.proved_optimal:
            assert r.weight == opt
