import pytest

from mwcp.graph import read_metis
from mwcp.result import Status
from mwcp.solvers import REGISTRY

from .conftest import brute_force_mwc, complement_edges, make_instance, random_graph, write_metis

SOLVERS = list(REGISTRY.values())
ids = [s.name for s in SOLVERS]


def _require(solver):
    if not solver.available():
        pytest.skip(f"{solver.binary} not built (run `mwcp build`)")


@pytest.mark.parametrize("solver", SOLVERS, ids=ids)
def test_known_instance(solver, data_dir, tmp_path):
    _require(solver)
    inst = make_instance(data_dir / "k4_heavy_triangle.graph", tmp_path)
    r = solver.run(inst, timeout=2)
    assert r.status == Status.OK, r.message
    assert r.weight == 30 and r.clique == [4, 5, 6]


@pytest.mark.parametrize("solver", SOLVERS, ids=ids)
def test_isolated_vertex_wins(solver, tmp_path):
    _require(solver)
    path = write_metis(tmp_path / "iso.graph", [3, 3, 3, 100], [(0, 1), (1, 2), (0, 2)])
    r = solver.run(make_instance(path, tmp_path / "w"), timeout=2)
    assert r.status == Status.OK, r.message
    assert r.weight == 100 and r.clique == [3]


def _check(solver, r, opt):
    assert r.status == Status.OK, r.message      # also verified as a real clique with the right weight
    if solver.exact:
        assert r.proved_optimal and r.weight == opt
    else:
        assert r.weight <= opt
        if r.proved_optimal:
            assert r.weight == opt


# Sparse and dense graphs; each is solved directly and via --complement on its complement file.
CASES = [(n, p, seed) for n, p in [(12, 0.2), (18, 0.5), (22, 0.8), (25, 0.95)] for seed in range(3)]


@pytest.mark.parametrize("solver", SOLVERS, ids=ids)
@pytest.mark.parametrize("n,p,seed", CASES)
@pytest.mark.parametrize("complement", [False, True], ids=["direct", "complement"])
def test_random_against_brute_force(solver, tmp_path, n, p, seed, complement):
    _require(solver)
    weights, edges = random_graph(n, p, seed)
    opt = brute_force_mwc(read_metis(write_metis(tmp_path / "g.graph", weights, edges)))
    if complement:
        path = write_metis(tmp_path / "gc.graph", weights, complement_edges(n, edges))
    else:
        path = tmp_path / "g.graph"
    r = solver.run(make_instance(path, tmp_path / "w", complement=complement), timeout=1)
    _check(solver, r, opt)
