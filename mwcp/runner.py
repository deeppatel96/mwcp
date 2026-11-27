"""Solve one graph with several solvers: the core shared by `mwcp solve` and `mwcp batch`."""
from __future__ import annotations

import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from .graph import Graph, GraphFormatError, read_metis
from .instance import Instance
from .result import SolverResult, Status
from .solvers import Solver


@dataclass
class Outcome:
    graph_path: Path
    graph: Graph
    results: List[SolverResult]
    best: Optional[SolverResult]
    parse_seconds: float
    prep_seconds: dict

    @property
    def provers(self) -> List[str]:
        if not self.best:
            return []
        return [r.solver for r in self.results
                if r.status == Status.OK and r.proved_optimal and r.weight == self.best.weight]


def solve_graph(graph_path: Path, solvers: Sequence[Solver], *, timeout: float, seed: int = 0,
                complement: bool = False, parallel: bool = False, kamis_reductions: str = "auto",
                graph: Optional[Graph] = None, log: Callable[[str], None] = lambda msg: None) -> Outcome:
    """Run `solvers` on the MWC instance given by `graph_path` (or its complement).

    Raises GraphFormatError/OSError for unreadable input and PrepError if derived inputs
    can't be built. Solver failures don't raise; they are reported in the results.
    Pass `graph` to reuse an already parsed graph (e.g. when looping over seeds).
    """
    graph_path = Path(graph_path)
    t0 = time.monotonic()
    if graph is None:
        graph = read_metis(graph_path, complement=complement)
    parse_s = time.monotonic() - t0
    if not graph.solver_weights_ok:
        raise GraphFormatError("the solvers need non-negative integer weights; real-valued or negative "
                               "(e.g. log-likelihood) weights are supported by `mwcp cover`")
    what = "complement of input" if complement else "input as given"
    log(f"graph {graph_path.name}: n={graph.n}, file m={graph.file_edges}; solving MWC on {what} "
        f"(m={graph.m}); parsed in {parse_s:.2f}s")

    with tempfile.TemporaryDirectory(prefix="mwcp-") as tmp:
        inst = Instance(graph_path, graph, Path(tmp), options={"kamis_reductions": kamis_reductions})
        # Build every derived input file once, up front, so parallel runs don't race on them.
        inst.prepare(sorted({n for s in solvers if s.available() for n in s.needs}))
        for key, secs in inst.prep_seconds.items():
            if inst._cache[key] != graph_path:
                log(f"  built {key} input in {secs:.2f}s")
        log(f"solvers: {', '.join(s.name for s in solvers)}; timeout {timeout}s; seed {seed}")

        def run(s: Solver) -> SolverResult:
            r = s.run(inst, timeout, seed)
            log(f"  {s.name}: {r.status} weight={r.weight}")
            return r

        if parallel and len(solvers) > 1:
            with ThreadPoolExecutor(max_workers=len(solvers)) as ex:
                results = list(ex.map(run, solvers))
        else:
            results = [run(s) for s in solvers]
        prep = dict(inst.prep_seconds)

    valid = [r for r in results if r.status == Status.OK]
    # Highest weight wins; on ties prefer a solver that proved optimality.
    best = max(valid, key=lambda r: (r.weight, r.proved_optimal)) if valid else None
    # A proven optimum below another solver's verified clique would mean a solver bug.
    for r in valid:
        if r.proved_optimal and best and r.weight < best.weight:
            r.message = (r.message + "; " if r.message else "") + \
                f"claimed optimal but {best.solver} found {best.weight}"
    return Outcome(graph_path, graph, results, best, parse_s, prep)
