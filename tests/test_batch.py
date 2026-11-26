import csv
import json

import pytest

from mwcp.cli import main
from mwcp.solvers import REGISTRY

from .conftest import random_graph, write_metis

pytestmark = pytest.mark.skipif(not REGISTRY["wlmc"].available(), reason="wlmc not built")


def test_batch_and_resume(tmp_path, data_dir):
    graphs = tmp_path / "graphs"
    graphs.mkdir()
    (graphs / "k4.graph").write_text((data_dir / "k4_heavy_triangle.graph").read_text())
    w, e = random_graph(15, 0.5, seed=1)
    write_metis(graphs / "r15.metis", w, e)
    (graphs / "notes.txt").write_text("ignored")
    out = tmp_path / "out"

    assert main(["batch", str(graphs), "-s", "wlmc,fastwclq", "-t", "1", "--seeds", "0,1",
                 "-o", str(out), "--solutions", "-q"]) == 0
    rows = [json.loads(l) for l in (out / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 2 * 2 * 2                                   # graphs x seeds x solvers
    k4 = [r for r in rows if r["graph_name"] == "k4"]
    assert all(r["status"] == "ok" and r["weight"] == 30 and r["is_best"] and r["gap"] == 0 for r in k4)
    assert all(r["clique"] == [4, 5, 6] for r in k4)
    with open(out / "summary.csv") as fh:
        assert len(list(csv.DictReader(fh))) == 8
    assert (out / "solutions" / "k4.s1.wlmc.sol").read_text().split() == list("00001110")
    assert len((out / "runs.jsonl").read_text().splitlines()) == 1

    # Resume adds only the new seed.
    assert main(["batch", str(graphs), "-s", "wlmc,fastwclq", "-t", "1", "--seeds", "0,1,2",
                 "-o", str(out), "--resume", "-q"]) == 0
    rows = [json.loads(l) for l in (out / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 12 and sorted({r["seed"] for r in rows}) == [0, 1, 2]


def test_batch_missing_input(tmp_path):
    assert main(["batch", str(tmp_path / "nope.graph"), "-o", str(tmp_path / "o"), "-q"]) == 2
