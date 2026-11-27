"""Solution quality over time, from the improvement traces of one run per solver.

A solver that reports improvements (WLMC, FastWClq) gives (seconds, weight) at every new best
clique, so a single run with a long time limit shows what it had found by any earlier time.
For solvers without a trace, a value is known only once the run has finished.

Times are seconds since the solver process started (graph reading included). A separate run
with a shorter limit stops on the solver's own clock, which excludes reading the graph, so it
can only be as good as or slightly better than the trace at that time; the search itself
follows the same path (tests/test_quality.py checks that).
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

CHECKPOINT_FIELDS = ["graph_name", "graph", "seed", "solver", "t", "weight", "best_weight", "gap",
                     "rel_gap", "proved_optimal", "source"]


def weight_at(row: dict, t: float) -> Optional[float]:
    """Best weight the run had found by `t` seconds, or None if unknown or nothing yet."""
    trace = row.get("trace") or []
    # Done by t: it finished by then, or t is the run's time limit (a solver stopping at its own
    # cutoff ends a little after the limit, and its answer is what that limit gives).
    done = (row.get("wall_time") is not None and row["wall_time"] <= t) or \
        (row.get("timeout") is not None and t >= float(row["timeout"]))
    finished = done and row.get("status") == "ok"
    if trace:
        w = None
        for ts, tw in trace:
            if ts <= t:
                w = tw
            else:
                break
        if finished and row.get("weight") is not None:
            w = row["weight"] if w is None else max(w, row["weight"])
        return w
    return row.get("weight") if finished else None


def default_checkpoints(timeout: float) -> List[float]:
    pts = [c for c in (1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1200, 1800, 3600) if c < timeout]
    return pts + [float(timeout)]


def best_by_graph(rows: Iterable[dict]) -> Dict[str, float]:
    best: Dict[str, float] = {}
    for r in rows:
        if r.get("status") == "ok" and r.get("weight") is not None:
            g = str(r.get("graph_name"))
            best[g] = max(best.get(g, r["weight"]), r["weight"])
    return best


def checkpoint_rows(rows: Sequence[dict], checkpoints: Sequence[float]) -> List[dict]:
    """One row per (graph, seed, solver, checkpoint): weight by then, gap to the best weight any
    solver found on that graph, and whether optimality had been proved by then."""
    best = best_by_graph(rows)
    out = []
    for r in rows:
        if r.get("status") == "unavailable":
            continue
        g = str(r.get("graph_name"))
        for t in checkpoints:
            w = weight_at(r, t)
            b = best.get(g)
            gap = (b - w) if (w is not None and b is not None) else None
            out.append({
                "graph_name": g, "graph": r.get("graph"), "seed": r.get("seed"), "solver": r["solver"],
                "t": t, "weight": w, "best_weight": b, "gap": gap,
                "rel_gap": (gap / b) if (gap is not None and b) else None,
                "proved_optimal": bool(r.get("proved_optimal")) and (
                    (r.get("wall_time") is not None and r["wall_time"] <= t)
                    or (r.get("timeout") is not None and t >= float(r["timeout"]))),
                "source": "trace" if r.get("trace") else ("finished" if w is not None else "unknown"),
            })
    return out
