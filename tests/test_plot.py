import json

import pytest

from mwcp.cli import main
from mwcp.plot import Scale, load_rows, render_report
from mwcp.solvers import REGISTRY

from .conftest import random_graph, write_metis


def _row(graph, seed, solver, wall, status="ok", timeout=10.0, mem=None):
    ok = status == "ok"
    return {"graph_name": graph, "graph": f"/g/{graph}.graph", "seed": seed, "timeout": timeout,
            "solver": solver, "status": status, "weight": 7 if ok else None, "proved_optimal": False,
            "is_best": ok, "gap": 0 if ok else None, "wall_time": wall, "solver_time": wall,
            "peak_rss_mb": mem, "message": ""}


def test_report_single_graph_has_one_chart():
    rows = [_row("g", 0, "wlmc", 0.5), _row("g", 0, "fastwclq", 0.02)]
    page = render_report(rows, title="T")
    assert page.startswith("<!doctype html>") and "<title>T</title>" in page
    assert page.count("<svg") == 1                       # no per-graph chart, no memory data
    assert "No memory measurements" in page
    assert "wlmc" in page and "fastwclq" in page and "500 ms" in page and "20 ms" in page
    assert "Table: all 2 results" in page


def test_report_batch_flags_timeouts_and_limit_runners():
    rows = []
    for g in ("a", "b"):
        for seed in (0, 1):
            rows += [_row(g, seed, "wlmc", 0.1 * (seed + 1)), _row(g, seed, "openpls", 10.0)]
    rows.append(_row("b", 2, "wlmc", 15.0, status="timeout"))
    rows.append(_row("b", 2, "kamis_br", None, status="unavailable"))   # dropped
    page = render_report(rows)
    assert page.count("<svg") == 2
    assert "1 timeout" in page
    assert "openpls ran until the time limit" in page
    assert "kamis_br" not in page
    assert "whisker" in page                              # several seeds -> min-max whiskers


def test_report_memory_charts():
    rows = [_row(g, 0, s, 0.1, mem=m) for g, s, m in
            [("a", "wlmc", 5.0), ("a", "kamis_br", 300.0), ("b", "wlmc", 8.0), ("b", "kamis_br", 2048.0)]]
    page = render_report(rows)
    assert page.count("<svg") == 4                       # time + memory, overall + per graph
    assert "Median peak memory per solver" in page and "Peak memory per graph" in page
    assert "2.00 GiB" in page and "5.00 MiB" in page     # table / tooltips
    assert "No memory measurements" not in page


def test_report_empty_raises():
    with pytest.raises(ValueError):
        render_report([_row("g", 0, "wlmc", None, status="unavailable")])


def test_scale_switches_to_log_for_wide_spread():
    assert not Scale([1, 5, 9], 0, 100).log
    s = Scale([0.003, 50], 0, 100)
    assert s.log and s.ticks[0] <= 0.003 and s.hi >= 50 and s.ticks[-1] <= s.hi
    assert s(s.lo) == 0 and s(s.hi) == 100


def test_plot_command_reads_jsonl_and_solve_json(tmp_path):
    rows = [_row("a", 0, "wlmc", 0.4), _row("a", 0, "fastwclq", 0.1), _row("b", 0, "wlmc", 2.0)]
    (tmp_path / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert main(["plot", str(tmp_path)]) == 0
    assert "Wall time per graph" in (tmp_path / "report.html").read_text()
    assert main(["plot", str(tmp_path / "results.jsonl"), "--graphs", "b", "-o", str(tmp_path / "b.html")]) == 0
    assert "fastwclq" not in (tmp_path / "b.html").read_text().split("<h2>")[1]

    solve = {"graph": "/g/x.graph", "timeout": 5.0, "seed": 0, "best": {"weight": 3},
             "results": [{"solver": "wlmc", "status": "ok", "weight": 3, "wall_time": 0.2,
                          "solver_time": 0.1, "proved_optimal": True}]}
    (tmp_path / "solve.json").write_text(json.dumps(solve, indent=2))
    assert load_rows(tmp_path / "solve.json")[0]["is_best"]
    assert main(["plot", str(tmp_path / "solve.json"), "-o", str(tmp_path / "s.html")]) == 0
    assert main(["plot", str(tmp_path / "missing.jsonl")]) == 2


@pytest.mark.skipif(not REGISTRY["wlmc"].available(), reason="wlmc not built")
def test_solve_and_batch_write_reports(tmp_path, data_dir):
    g = data_dir / "k4_heavy_triangle.graph"
    assert main(["solve", str(g), "-s", "wlmc,fastwclq", "-t", "1", "-q",
                 "--plot", str(tmp_path / "solve.html"), "--json", str(tmp_path / "s.json")]) == 0
    results = json.loads((tmp_path / "s.json").read_text())["results"]
    assert all(0 < r["peak_rss_mb"] < 1024 for r in results)
    assert "Solver performance: k4_heavy_triangle.graph" in (tmp_path / "solve.html").read_text()

    w, e = random_graph(15, 0.5, seed=2)
    write_metis(tmp_path / "r15.graph", w, e)
    out = tmp_path / "out"
    assert main(["batch", str(g), str(tmp_path / "r15.graph"), "-s", "wlmc,fastwclq", "-t", "1",
                 "--seeds", "0,1", "-o", str(out), "--plot", "-q"]) == 0
    page = (out / "report.html").read_text()
    assert "2 graphs × 2 seeds" in page and "Table: all 8 results" in page
    assert "Peak memory per graph" in page
    rows = [json.loads(l) for l in (out / "results.jsonl").read_text().splitlines()]
    assert all(r["peak_rss_mb"] and r["peak_rss_mb"] > 0 for r in rows)
