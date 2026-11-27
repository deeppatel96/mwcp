"""mwcp cover, checked against brute-force enumeration of every clique on small graphs."""
import json
import math
import random
import subprocess

import pytest

from mwcp import BIN_DIR
from mwcp.cli import main
from mwcp.cover import run_cover
from mwcp.graph import read_metis

from .conftest import write_metis

pytestmark = pytest.mark.skipif(not (BIN_DIR / "mwcp_cover").is_file(), reason="mwcp_cover not built")


def real_graph(tmp_path, n, p, seed, mean=1.0, sd=2.0, name="g.graph"):
    rng = random.Random(seed)
    weights = [round(rng.gauss(mean, sd), 6) for _ in range(n)]
    edges = [(u, v) for u in range(n) for v in range(u + 1, n) if rng.random() < p]
    return write_metis(tmp_path / name, weights, edges)


def all_cliques(g):
    """Every clique (empty one included) with its weight, by brute force."""
    out = []

    def rec(clique, cands):
        out.append((g.weight_of(clique), clique))
        for i, v in enumerate(cands):
            rec(clique + [v], [u for u in cands[i + 1:] if g.has_edge(u, v)])

    rec([], list(range(g.n)))
    return out


def log_sum(ws):
    m = max(ws)
    return m + math.log(sum(math.exp(w - m) for w in ws))


def true_coverage(res, log_z):
    return sum(math.exp(h.weight - log_z) for h in res.hypotheses)


CASES = [(12, 0.5, 1), (14, 0.35, 2), (16, 0.6, 3), (15, 0.25, 4), (13, 0.8, 5)]


@pytest.mark.parametrize("n,p,seed", CASES)
@pytest.mark.parametrize("tau", [0.9, 0.99])
def test_exact_coverage_is_proven_and_sound(tmp_path, n, p, seed, tau):
    path = real_graph(tmp_path, n, p, seed)
    g = read_metis(path)
    cl = all_cliques(g)
    log_z = log_sum([w for w, _ in cl])
    res = run_cover(path, mode="exact", coverage=tau, time_limit=20)
    assert res.guaranteed, res.stop
    cov = true_coverage(res, log_z)
    assert cov >= tau - 1e-9                              # the guarantee holds
    assert res.coverage_proved <= cov + 1e-9              # the proof never overstates
    assert res.log_z_upper >= log_z - 1e-9                # the mass bound is a real upper bound
    assert res.log_z_found <= log_z + 1e-9
    # Heaviest first, and the same weights as the true top of the list.
    top = sorted((w for w, _ in cl), reverse=True)[:len(res.hypotheses)]
    assert [round(h.weight, 6) for h in res.hypotheses] == [round(w, 6) for w in top]
    # Minimal with respect to the proven bound: without the last one the target isn't proven.
    assert sum(h.p_low for h in res.hypotheses[:-1]) < tau


@pytest.mark.parametrize("n,p,seed", CASES)
def test_exact_top_k(tmp_path, n, p, seed):
    path = real_graph(tmp_path, n, p, seed)
    g = read_metis(path)
    best = sorted((w for w, _ in all_cliques(g)), reverse=True)[:5]
    res = run_cover(path, mode="exact", k=5, time_limit=20)
    assert res.topk_proven and res.guaranteed
    assert [round(h.weight, 6) for h in res.hypotheses] == [round(w, 6) for w in best]


@pytest.mark.parametrize("n,p,seed", CASES)
def test_pool(tmp_path, n, p, seed):
    path = real_graph(tmp_path, n, p, seed)
    g = read_metis(path)
    cl = all_cliques(g)
    log_z = log_sum([w for w, _ in cl])
    res = run_cover(path, coverage=0.99, time_limit=5)
    assert res.mode == "pool" and not res.guaranteed
    assert math.isclose(res.hypotheses[0].weight, max(w for w, _ in cl), abs_tol=1e-6)
    cov = true_coverage(res, log_z)
    assert res.coverage_estimate >= cov - 1e-9            # relative to the mass found: overestimates
    assert res.coverage_proved <= cov + 1e-9              # the free floor is a real lower bound


def test_complement(tmp_path):
    path = real_graph(tmp_path, 14, 0.7, 9)
    h = read_metis(path, complement=True)
    best = sorted((w for w, _ in all_cliques(h)), reverse=True)[:4]
    res = run_cover(path, mode="exact", k=4, complement=True, time_limit=20)
    assert [round(x.weight, 6) for x in res.hypotheses] == [round(w, 6) for w in best]


def test_budget_stop_reports_partial_proof(tmp_path):
    # Many tracks near 0: an enormous number of comparable hypotheses, not provable in 1 s.
    path = real_graph(tmp_path, 300, 0.3, 11, mean=0.0, sd=0.5)
    res = run_cover(path, mode="exact", coverage=0.99, time_limit=1, max_memory_mb=256)
    assert res.stop in ("time", "memory") and not res.guaranteed
    assert 0 <= res.coverage_proved < 0.99
    assert main(["cover", str(path), "--exact", "-t", "1", "--max-memory-mb", "256"]) == 3


def test_decimal_weights_parse_and_solvers_refuse_them(tmp_path):
    path = real_graph(tmp_path, 8, 0.5, 1)
    g = read_metis(path)
    assert any(isinstance(w, float) for w in g.weights) and not g.solver_weights_ok
    assert main(["solve", str(path), "-s", "wlmc", "-t", "1", "-q"]) == 2
    p = subprocess.run([str(BIN_DIR / "wlmc_cli"), str(path), "1"], capture_output=True, text=True)
    assert p.returncode == 1 and "mwcp cover" in p.stderr


def test_cli_json_and_draw(tmp_path):
    path = real_graph(tmp_path, 14, 0.4, 7)
    out = tmp_path / "c.json"
    assert main(["cover", str(path), "--exact", "--json", str(out), "--draw", str(tmp_path / "h.html")]) == 0
    d = json.loads(out.read_text())
    assert d["guaranteed"] and d["mode"] == "exact" and d["hypotheses"][0]["rank"] == 1
    assert {"weight", "vertices", "p_low", "p_high"} <= set(d["hypotheses"][0])
    page = (tmp_path / "h.html").read_text()
    assert 'data-s="#1"' in page and "Hypotheses:" in page
