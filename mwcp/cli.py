"""mwcp: run several Maximum Weight Clique solvers on one METIS graph."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

from . import BIN_DIR, REPO_ROOT, __version__
from .graph import GraphFormatError, write_kamis_solution
from .instance import PrepError
from .runner import solve_graph
from .result import SolverResult, Status
from .solvers import REGISTRY, get_solvers


def _cmd_build(args) -> int:
    cmake = shutil.which("cmake") or str(Path(sys.executable).parent / "cmake")
    build_dir = REPO_ROOT / "build"
    configure = [cmake, "-S", str(REPO_ROOT), "-B", str(build_dir), "-DCMAKE_BUILD_TYPE=Release",
                 f"-DMWCP_PORTABLE={'ON' if args.portable else 'OFF'}"]
    build = [cmake, "--build", str(build_dir)] + (["-j", str(args.jobs)] if args.jobs else ["-j"])
    for cmd in (configure, build):
        print("+", " ".join(cmd), flush=True)
        if subprocess.call(cmd) != 0:
            return 1
    missing = [s.binary for s in REGISTRY.values() if not s.available()]
    if not (BIN_DIR / "metis_tool").is_file():
        missing.append("metis_tool")
    if missing:
        print(f"error: missing binaries in {BIN_DIR}: {', '.join(missing)}", file=sys.stderr)
        return 1
    print(f"built: {', '.join(s.binary for s in REGISTRY.values())}, metis_tool -> {BIN_DIR}")
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


def _logger(quiet: bool):
    return (lambda msg: None) if quiet else (lambda msg: print(msg, file=sys.stderr, flush=True))


def _cmd_solve(args) -> int:
    graph_path = Path(args.graph)
    try:
        solvers = get_solvers(args.solvers)
    except KeyError as e:
        print(f"error: {e.args[0]}", file=sys.stderr)
        return 2
    try:
        out = solve_graph(graph_path, solvers, timeout=args.timeout, seed=args.seed,
                          complement=args.complement, parallel=args.parallel,
                          kamis_reductions=args.kamis_reductions, log=_logger(args.quiet))
    except (OSError, GraphFormatError, ValueError) as e:
        print(f"error: cannot read {graph_path}: {e}", file=sys.stderr)
        return 2
    except PrepError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    graph, results, best = out.graph, out.results, out.best

    print(_fmt_table(results))
    if best:
        provers = out.provers
        print(f"\nbest: {best.solver} weight={best.weight} size={len(best.clique)}"
              f"{' (proven optimal by ' + ', '.join(provers) + ')' if provers else ''}")

    if args.solution_out:
        sol_dir = Path(args.solution_out)
        sol_dir.mkdir(parents=True, exist_ok=True)
        for r in results:
            if r.status == Status.OK:
                write_kamis_solution(graph.n, r.clique, sol_dir / f"{graph_path.stem}.{r.solver}.sol")
        if best:
            write_kamis_solution(graph.n, best.clique, sol_dir / f"{graph_path.stem}.best.sol")

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


def _cmd_batch(args) -> int:
    from .batch import run_batch
    return run_batch(args, log=_logger(args.quiet))


def _add_common_solve_args(s: argparse.ArgumentParser) -> None:
    s.add_argument("-s", "--solvers", default="all",
                   help=f"comma list or 'all' (default). Available: {', '.join(REGISTRY)}")
    s.add_argument("-t", "--timeout", type=float, default=60.0, help="per-solver time limit in seconds (default 60)")
    s.add_argument("-c", "--complement", action="store_true",
                   help="the input is the complement: solve MWC on the complement of the input file")
    s.add_argument("--kamis-reductions", choices=["auto", "normal", "dense"], default="auto",
                   help="KaMIS --reduction_style; auto picks 'dense' when KaMIS's input "
                        "(complement of the MWC graph) has density >= 0.5 (default auto)")
    s.add_argument("-p", "--parallel", action="store_true",
                   help="run a graph's solvers concurrently (CPU-time cutoffs then compete for cores)")
    s.add_argument("-q", "--quiet", action="store_true", help="no progress output on stderr")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mwcp", description=__doc__)
    p.add_argument("--version", action="version", version=f"mwcp {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("solve", help="solve MWC on a METIS graph with one or more solvers")
    s.add_argument("graph", help="METIS graph (KaMIS format; header fmt 10 = vertex weights)")
    _add_common_solve_args(s)
    s.add_argument("--seed", type=int, default=0, help="random seed for heuristic solvers")
    s.add_argument("--json", metavar="PATH", help="write full results as JSON ('-' for stdout)")
    s.add_argument("--solution-out", metavar="DIR",
                   help="write KaMIS-style 0/1 solution files (<graph>.<solver>.sol and <graph>.best.sol)")
    s.set_defaults(func=_cmd_solve)

    x = sub.add_parser("batch", help="run solvers over many graphs and seeds; write JSONL + CSV results")
    x.add_argument("inputs", nargs="+",
                   help="graph files and/or directories (directories: every *.graph / *.metis file in them)")
    _add_common_solve_args(x)
    x.add_argument("--seeds", default="0", help="comma list of seeds, each graph runs once per seed (default 0)")
    x.add_argument("-o", "--out", required=True, metavar="DIR",
                   help="results directory: results.jsonl, summary.csv, runs.jsonl (run configs)")
    x.add_argument("--solutions", action="store_true",
                   help="also write KaMIS-style solution files to OUT/solutions/")
    x.add_argument("--resume", action="store_true",
                   help="skip (graph, seed) pairs already in OUT/results.jsonl with the same settings")
    x.set_defaults(func=_cmd_batch)

    b = sub.add_parser("build", help="configure and build all solver binaries with CMake")
    b.add_argument("--portable", action="store_true",
                   help="don't tune for the build machine's CPU (KaMIS uses -march=native otherwise)")
    b.add_argument("-j", "--jobs", type=int, default=0, help="parallel build jobs (default: all cores)")
    b.set_defaults(func=_cmd_build)

    l = sub.add_parser("list", help="list solvers and whether they are built")
    l.set_defaults(func=_cmd_list)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
