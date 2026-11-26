"""mwcp: run several Maximum Weight Clique solvers on one METIS graph."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

from . import BIN_DIR, REPO_ROOT, __version__
from .graph import GraphFormatError, read_metis, write_kamis_solution
from .instance import Instance, PrepError
from .result import SolverResult, Status
from .solvers import REGISTRY, get_solvers


def _cmd_build(args) -> int:
    cmake = shutil.which("cmake") or str(Path(sys.executable).parent / "cmake")
    build_dir = REPO_ROOT / "build"
    steps = [
        [cmake, "-S", str(REPO_ROOT), "-B", str(build_dir), "-DCMAKE_BUILD_TYPE=Release"],
        [cmake, "--build", str(build_dir), "-j"],
    ]
    for cmd in steps:
        print("+", " ".join(cmd), flush=True)
        if subprocess.call(cmd) != 0:
            return 1
    missing = [s.binary for s in REGISTRY.values() if not s.available()]
    if not (BIN_DIR / "metis_tool").is_file():
        missing.append("metis_tool")
    if missing:
        print(f"error: missing binaries in {BIN_DIR}: {', '.join(missing)}", file=sys.stderr)
        return 1
    print(f"built: {', '.join(s.binary for s in REGISTRY.values())} -> {BIN_DIR}")
    return 0


def _cmd_list(args) -> int:
    for s in REGISTRY.values():
        mark = "built" if s.available() else "NOT BUILT"
        print(f"{s.name:<10} {'exact' if s.exact else 'heuristic':<10} {mark:<10} {s.description}")
    return 0


def _fmt_table(results: List[SolverResult]) -> str:
    rows = [("solver", "status", "weight", "|C|", "solver_s", "wall_s", "optimal", "note")]
    for r in results:
        rows.append((
            r.solver, r.status,
            "" if r.weight is None else str(r.weight),
            str(len(r.clique)) if r.status in (Status.OK, Status.INVALID) else "",
            "" if r.solver_time is None else f"{r.solver_time:.3f}",
            "" if r.wall_time is None else f"{r.wall_time:.3f}",
            "yes" if r.proved_optimal else "",
            r.message,
        ))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]) - 1)]
    lines = []
    for row in rows:
        lines.append("  ".join(c.ljust(w) for c, w in zip(row, widths)) + ("  " + row[-1] if row[-1] else ""))
        if len(lines) == 1:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def _cmd_solve(args) -> int:
    graph_path = Path(args.graph)
    try:
        solvers = get_solvers(args.solvers)
    except KeyError as e:
        print(f"error: {e.args[0]}", file=sys.stderr)
        return 2
    log = (lambda *a: None) if args.quiet else (lambda msg: print(msg, file=sys.stderr, flush=True))

    t0 = time.monotonic()
    try:
        graph = read_metis(graph_path, complement=args.complement)
    except (OSError, GraphFormatError, ValueError) as e:
        print(f"error: cannot read {graph_path}: {e}", file=sys.stderr)
        return 2
    what = "complement of input" if args.complement else "input as given"
    log(f"graph {graph_path.name}: n={graph.n}, file m={graph.file_edges}; solving MWC on {what} "
        f"(m={graph.m}); parsed in {time.monotonic() - t0:.2f}s")

    with tempfile.TemporaryDirectory(prefix="mwcp-") as tmp:
        inst = Instance(graph_path, graph, Path(tmp), options={"kamis_reductions": args.kamis_reductions})
        # Build every derived input file once, up front, so parallel runs don't race on them.
        needs = sorted({n for s in solvers if s.available() for n in s.needs})
        try:
            inst.prepare(needs)
        except PrepError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        for k, secs in inst.prep_seconds.items():
            if inst._cache[k] != graph_path:
                log(f"  built {k} input in {secs:.2f}s")
        log(f"solvers: {', '.join(s.name for s in solvers)}; timeout {args.timeout}s")

        def run(s):
            r = s.run(inst, args.timeout, args.seed)
            log(f"  {s.name}: {r.status} weight={r.weight}")
            return r

        if args.parallel and len(solvers) > 1:
            with ThreadPoolExecutor(max_workers=len(solvers)) as ex:
                results = list(ex.map(run, solvers))
        else:
            results = [run(s) for s in solvers]

    valid = [r for r in results if r.status == Status.OK]
    # Highest weight wins; on ties prefer a solver that proved optimality.
    best = max(valid, key=lambda r: (r.weight, r.proved_optimal)) if valid else None
    # A proven optimum below another solver's verified clique would mean a solver bug.
    for r in valid:
        if r.proved_optimal and best and r.weight < best.weight:
            r.message = (r.message + "; " if r.message else "") + \
                f"claimed optimal but {best.solver} found {best.weight}"

    print(_fmt_table(results))
    if best:
        provers = [r.solver for r in valid if r.proved_optimal and r.weight == best.weight]
        print(f"\nbest: {best.solver} weight={best.weight} size={len(best.clique)}"
              f"{' (proven optimal by ' + ', '.join(provers) + ')' if provers else ''}")

    if args.solution_out:
        out = Path(args.solution_out)
        out.mkdir(parents=True, exist_ok=True)
        for r in valid:
            write_kamis_solution(graph.n, r.clique, out / f"{graph_path.stem}.{r.solver}.sol")
        if best:
            write_kamis_solution(graph.n, best.clique, out / f"{graph_path.stem}.best.sol")

    if args.json:
        payload = {
            "graph": str(graph_path), "n": graph.n, "file_edges": graph.file_edges,
            "complement": args.complement, "m": graph.m,
            "timeout": args.timeout, "seed": args.seed,
            "best": None if best is None else {"solver": best.solver, "weight": best.weight, "clique": best.clique},
            "results": [r.to_dict() for r in results],
        }
        text = json.dumps(payload, indent=2)
        if args.json == "-":
            print(text)
        else:
            Path(args.json).write_text(text + "\n")

    return 0 if best else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mwcp", description=__doc__)
    p.add_argument("--version", action="version", version=f"mwcp {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("solve", help="solve MWC on a METIS graph with one or more solvers")
    s.add_argument("graph", help="METIS graph (KaMIS format; header fmt 10 = vertex weights)")
    s.add_argument("-s", "--solvers", default="all",
                   help=f"comma list or 'all' (default). Available: {', '.join(REGISTRY)}")
    s.add_argument("-t", "--timeout", type=float, default=60.0, help="per-solver time limit in seconds (default 60)")
    s.add_argument("-c", "--complement", action="store_true",
                   help="the input is the complement: solve MWC on the complement of the input file")
    s.add_argument("--seed", type=int, default=0, help="random seed for heuristic solvers")
    s.add_argument("--kamis-reductions", choices=["auto", "normal", "dense"], default="auto",
                   help="KaMIS --reduction_style; auto picks 'dense' when KaMIS's input "
                        "(complement of the MWC graph) has density >= 0.5 (default auto)")
    s.add_argument("-p", "--parallel", action="store_true", help="run solvers concurrently")
    s.add_argument("--json", metavar="PATH", help="write full results as JSON ('-' for stdout)")
    s.add_argument("--solution-out", metavar="DIR",
                   help="write KaMIS-style 0/1 solution files (<graph>.<solver>.sol and <graph>.best.sol)")
    s.add_argument("-q", "--quiet", action="store_true", help="no progress output on stderr")
    s.set_defaults(func=_cmd_solve)

    b = sub.add_parser("build", help="configure and build all solver binaries with CMake")
    b.set_defaults(func=_cmd_build)

    l = sub.add_parser("list", help="list solvers and whether they are built")
    l.set_defaults(func=_cmd_list)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
