"""Improvement traces (quality over time) and checkpoints."""
import csv
import json

import pytest

from mwcp.cli import main
from mwcp.graph import read_metis
from mwcp.instance import Instance
from mwcp.plot import render_report
from mwcp.quality import checkpoint_rows, default_checkpoints, weight_at
from mwcp.solvers import REGISTRY

from .conftest import random_graph, write_metis

TRACED = ["wlmc", "fastwclq"]
needs_bins = pytest.mark.skipif(not all(REGISTRY[s].available() for s in TRACED), reason="solvers not built")


def _run(solver, path, timeout, tmp_path, seed=0):
    g = read_metis(path)
    inst = Instance(path, g, tmp_path, options={})
    return REGISTRY[solver].run(inst, timeout, seed)


@needs_bins
@pytest.mark.parametrize("solver", TRACED)
def test_trace_increases_and_ends_at_the_result(solver, tmp_path):
    w, e = random_graph(150, 0.8, seed=3)
    path = write_metis(tmp_path / "g.graph", w, e)
    r = _run(solver, path, 1.0, tmp_path)
    assert r.status == "ok" and r.trace
    times = [t for t, _ in r.trace]
    weights = [x for _, x in r.trace]
    assert times == sorted(times) and all(a < b for a, b in zip(weights, weights[1:]))
    assert weights[-1] == r.weight
    assert times[-1] <= r.wall_time + 0.05


@needs_bins
@pytest.mark.parametrize("solver", TRACED)
def test_short_run_follows_the_same_path(solver, tmp_path):
    # The shortcut "read a long run's trace at time t instead of running with limit t" needs the
    # search to be the same regardless of the limit: a short run's improvements must be the start
    # of a long run's improvements.
    w, e = random_graph(400, 0.9, seed=5)
    path = write_metis(tmp_path / "g.graph", w, e)
    short = [x for _, x in _run(solver, path, 0.3, tmp_path, seed=1).trace]
    long_ = [x for _, x in _run(solver, path, 2.0, tmp_path, seed=1).trace]
    assert short and long_[:len(short)] == short


def test_weight_at_and_checkpoints():
    traced = {"graph_name": "g", "seed": 0, "solver": "fastwclq", "status": "ok", "weight": 30,
              "wall_time": 10.0, "trace": [[0.5, 10], [2.0, 25], [6.0, 30]], "proved_optimal": False}
    finished = {"graph_name": "g", "seed": 0, "solver": "kamis_br", "status": "ok", "weight": 30,
                "wall_time": 3.0, "trace": [], "proved_optimal": True}
    running = {"graph_name": "g", "seed": 0, "solver": "openpls", "status": "ok", "weight": 28,
               "wall_time": 10.0, "trace": []}
    assert weight_at(traced, 0.1) is None and weight_at(traced, 1) == 10 and weight_at(traced, 5) == 25
    assert weight_at(traced, 10) == 30
    assert weight_at(finished, 2) is None and weight_at(finished, 3) == 30
    assert weight_at(running, 5) is None and weight_at(running, 10) == 28
    late = dict(running, timeout=10.0, wall_time=10.4)       # stopped at its own cutoff, just after
    assert weight_at(late, 9.9) is None and weight_at(late, 10) == 28
    rows = checkpoint_rows([traced, finished, running], [1, 5, 10])
    by = {(r["solver"], r["t"]): r for r in rows}
    assert by[("fastwclq", 5)]["gap"] == 5 and by[("fastwclq", 5)]["rel_gap"] == pytest.approx(5 / 30)
    assert by[("kamis_br", 5)]["proved_optimal"] and not by[("kamis_br", 1)]["proved_optimal"]
    assert by[("openpls", 5)]["weight"] is None and by[("openpls", 5)]["source"] == "unknown"
    assert default_checkpoints(60) == [1, 2, 5, 10, 20, 30, 60.0]


def test_report_quality_section():
    base = {"graph_name": "g", "seed": 0, "timeout": 10.0, "status": "ok", "weight": 30, "wall_time": 10.0,
            "proved_optimal": False, "is_best": True, "gap": 0}
    rows = [dict(base, solver="fastwclq", trace=[[0.5, 10], [2.0, 30]]),
            dict(base, solver="openpls", trace=[])]
    page = render_report(rows)
    assert "Quality over time" in page and 'id="qchart"' in page
    assert "openpls report no improvements" in page
    assert "Quality over time" not in render_report([dict(r, trace=[]) for r in rows])


@needs_bins
def test_batch_checkpoints(tmp_path):
    w, e = random_graph(120, 0.7, seed=2)
    path = write_metis(tmp_path / "g.graph", w, e)
    out = tmp_path / "out"
    assert main(["batch", str(path), "-s", "wlmc,fastwclq", "-t", "1", "-o", str(out),
                 "--checkpoints", "0.5,1", "--plot", "-q"]) == 0
    rows = [json.loads(l) for l in (out / "results.jsonl").read_text().splitlines()]
    assert all(r["trace"] for r in rows)
    with open(out / "checkpoints.csv") as fh:
        cps = list(csv.DictReader(fh))
    assert len(cps) == 2 * 2 and {c["t"] for c in cps} == {"0.5", "1.0"}
    assert "Quality over time" in (out / "report.html").read_text()
    assert main(["batch", str(path), "-o", str(out), "--checkpoints", "0,5", "-q"]) == 2
