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
from .graph import GraphFormatError, read_metis, write_kamis_solution
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
    for tool in ("metis_tool", "mwcp_exec", "mwcp_cover"):
        if not (BIN_DIR / tool).is_file():
            missing.append(tool)
    if missing:
        print(f"error: missing binaries in {BIN_DIR}: {', '.join(missing)}", file=sys.stderr)
        return 1
    print(f"built: {', '.join(s.binary for s in REGISTRY.values())}, metis_tool, mwcp_exec, mwcp_cover -> {BIN_DIR}")
    return 0


def _cmd_list(args) -> int:
    for s in REGISTRY.values():
        mark = "built" if s.available() else "NOT BUILT"
        print(f"{s.name:<10} {'exact' if s.exact else 'heuristic':<10} {mark:<10} {s.description}")
    return 0


def _fmt_table(results: List[SolverResult]) -> str:
    rows = [("solver", "status", "weight", "|C|", "solver_s", "wall_s", "mem_MiB", "optimal", "note")]
    for r in results:
        rows.append((
            r.solver, r.status,
            "" if r.weight is None else str(r.weight),
            str(len(r.clique)) if r.status in (Status.OK, Status.INVALID) else "",
            "" if r.solver_time is None else f"{r.solver_time:.3f}",
            "" if r.wall_time is None else f"{r.wall_time:.3f}",
            "" if r.peak_rss_mb is None else f"{r.peak_rss_mb:.1f}",
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

    if args.plot:
        from .plot import rows_from_solve, write_report
        rows = rows_from_solve(str(graph_path), [r.to_dict() for r in results], args.timeout, args.seed,
                               best.weight if best else None)
        try:
            path = write_report(rows, Path(args.plot), title=f"Solver performance: {graph_path.name}")
            print(f"performance report: {path}", file=sys.stderr)
        except (OSError, ValueError) as e:
            print(f"error: cannot write performance report: {e}", file=sys.stderr)

    if args.draw and best:
        from .viz import write_clique_view
        files = write_clique_view(graph, [r.to_dict() for r in results], Path(args.draw),
                                  title=f"Cliques: {graph_path.name}",
                                  max_vertices=args.max_vertices, max_edges=args.max_edges,
                                  log=_logger(False))
        print(f"clique view: {', '.join(str(f) for f in files)}", file=sys.stderr)

    return 0 if best else 1


def _cmd_batch(args) -> int:
    from .batch import run_batch
    return run_batch(args, log=_logger(args.quiet))


def _cmd_plot(args) -> int:
    from .plot import load_rows, write_report
    src = Path(args.results)
    try:
        rows = load_rows(src)
    except (OSError, ValueError, KeyError) as e:
        print(f"error: cannot read results from {src}: {e}", file=sys.stderr)
        return 2
    if args.graphs:
        keep = {g.strip() for g in args.graphs.split(",") if g.strip()}
        rows = [r for r in rows if str(r.get("graph_name")) in keep]
    out = Path(args.out) if args.out else (src if src.is_dir() else src.parent) / "report.html"
    try:
        write_report(rows, out, title=args.title)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"performance report: {out}")
    return 0


def _cmd_draw(args) -> int:
    from .graph import read_metis
    from .plot import load_rows
    from .viz import write_clique_view
    src = Path(args.results)
    try:
        rows = load_rows(src)
    except (OSError, ValueError, KeyError) as e:
        print(f"error: cannot read results from {src}: {e}", file=sys.stderr)
        return 2
    if args.graph_name:
        rows = [r for r in rows if str(r.get("graph_name")) == args.graph_name]
    if args.seed is not None:
        rows = [r for r in rows if r.get("seed") == args.seed]
    groups = {}
    for r in rows:
        groups.setdefault((str(r.get("graph")), r.get("seed"), bool(r.get("complement"))), []).append(r)
    if not groups:
        print("error: no results match", file=sys.stderr)
        return 2
    if args.graph and len({k[0] for k in groups}) > 1:
        print("error: --graph given but the results cover several graphs; pick one with --graph-name",
              file=sys.stderr)
        return 2
    base = src if src.is_dir() else src.parent
    single = len(groups) == 1
    status = 0
    for (gpath, seed, complement), g_rows in groups.items():
        path = Path(args.graph or gpath)
        stem = Path(gpath).stem
        name = f"{stem}.s{seed}.html"
        if single:
            out = Path(args.out) if args.out else base / name
        else:
            out = (Path(args.out) if args.out else base / "cliques") / name
        try:
            graph = read_metis(path, complement=complement)
            files = write_clique_view(graph, g_rows, out, title=f"Cliques: {path.name}",
                                      subtitle=f"seed {seed}", max_vertices=args.max_vertices,
                                      max_edges=args.max_edges, log=_logger(False))
        except (OSError, GraphFormatError, ValueError) as e:
            print(f"error: {stem} seed {seed}: {e}", file=sys.stderr)
            status = 1
            continue
        print(f"clique view: {', '.join(str(f) for f in files)}")
    return status


def _cmd_cover(args) -> int:
    from .cover import CoverError, format_table, run_cover
    graph_path = Path(args.graph)
    try:
        graph = read_metis(graph_path, complement=args.complement)
    except (OSError, GraphFormatError, ValueError) as e:
        print(f"error: cannot read {graph_path}: {e}", file=sys.stderr)
        return 2
    try:
        res = run_cover(graph_path, mode="exact" if args.exact else "pool", coverage=args.coverage, k=args.k,
                        time_limit=args.timeout, seed_time=args.seed_time, max_hypotheses=args.max_hypotheses,
                        seed=args.seed, complement=args.complement, max_memory_mb=args.max_memory_mb, graph=graph)
    except CoverError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(format_table(res))
    if args.json:
        payload = {"graph": str(graph_path), "n": graph.n, "m": graph.m, "complement": args.complement,
                   **res.to_dict()}
        text = json.dumps(payload, indent=2)
        if args.json == "-":
            print(text)
        else:
            Path(args.json).write_text(text + "\n")
    if args.draw:
        from .viz import write_clique_view
        top = [{"solver": f"#{h.rank}", "status": "ok", "weight": h.weight, "clique": h.vertices}
               for h in res.hypotheses[:args.draw_top] if h.vertices]
        if top:
            files = write_clique_view(graph, top, Path(args.draw), title=f"Hypotheses: {graph_path.name}",
                                      subtitle=f"top {len(top)} of {len(res.hypotheses)}",
                                      max_vertices=args.max_vertices, max_edges=args.max_edges,
                                      log=_logger(False), hypotheses=True)
            print(f"hypothesis view: {', '.join(str(f) for f in files)}", file=sys.stderr)
    if args.exact and not res.guaranteed:
        return 3   # ran, but the requested coverage / top-K was not proven
    return 0


def _add_draw_limits(s: argparse.ArgumentParser) -> None:
    s.add_argument("--max-vertices", type=int, default=300, metavar="N",
                   help="clique view: draw the whole graph up to N vertices, else a reduced view (default 300)")
    s.add_argument("--max-edges", type=int, default=4000, metavar="N",
                   help="clique view: at most N edges, those at the cliques first (default 4000)")


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
    s.add_argument("--draw", metavar="PATH",
                   help="write a clique view: PATH.html (interactive), PATH.dot and, with Graphviz, PATH.svg")
    _add_draw_limits(s)
    s.add_argument("--plot", metavar="PATH",
                   help="write an HTML report comparing the solvers' wall time and peak memory (e.g. report.html)")
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
    x.add_argument("--draw", action="store_true",
                   help="also write a clique view per graph and seed to OUT/cliques/ (.html, .dot, .svg)")
    _add_draw_limits(x)
    x.add_argument("--plot", action="store_true",
                   help="also write OUT/report.html, comparing the solvers' wall time and peak memory")
    x.set_defaults(func=_cmd_batch)

    pl = sub.add_parser("plot", help="write an HTML performance report (time, memory) from saved results")
    pl.add_argument("results", help="batch output dir, its results.jsonl, or a `mwcp solve --json` file")
    pl.add_argument("-o", "--out", metavar="PATH", help="report path (default: report.html next to the results)")
    pl.add_argument("--graphs", metavar="NAMES", help="comma list of graph names to include (default: all)")
    pl.add_argument("--title", default="Solver performance", help="report title")
    pl.set_defaults(func=_cmd_plot)

    c = sub.add_parser("cover", help="the heaviest hypotheses (cliques) up to a probability coverage; "
                                     "weights are natural-log scores, P(clique) ~ exp(weight)")
    c.add_argument("graph", help="METIS graph; vertex weights may be real numbers (e.g. log-likelihood ratios)")
    c.add_argument("--exact", action="store_true",
                   help="prove the coverage (branch and bound); default: fast pool search, no guarantee")
    grp = c.add_mutually_exclusive_group()
    grp.add_argument("--coverage", type=float, default=0.99,
                     help="return hypotheses until they hold this share of the probability (default 0.99)")
    grp.add_argument("-k", type=int, default=0, metavar="K", help="return the K heaviest hypotheses instead")
    c.add_argument("-t", "--timeout", type=float, default=10.0, help="time budget in seconds (default 10)")
    c.add_argument("--seed-time", type=float, metavar="S",
                   help="exact mode: seconds of pool search before branch and bound (default 10%% of -t)")
    c.add_argument("--max-hypotheses", type=int, default=10000, metavar="N",
                   help="return at most N hypotheses (default 10000)")
    c.add_argument("--max-memory-mb", type=float, default=2048, metavar="MB",
                   help="exact mode: stop when the search frontier needs more memory (default 2048)")
    c.add_argument("--seed", type=int, default=0, help="random seed for the pool search")
    c.add_argument("-c", "--complement", action="store_true",
                   help="the input is the complement: hypotheses are cliques of its complement")
    c.add_argument("--json", metavar="PATH", help="write the result as JSON ('-' for stdout)")
    c.add_argument("--draw", metavar="PATH", help="write a hypothesis view (.html/.dot/.svg) of the top hypotheses")
    c.add_argument("--draw-top", type=int, default=20, metavar="N", help="hypotheses in the view (default 20)")
    _add_draw_limits(c)
    c.set_defaults(func=_cmd_cover)

    d = sub.add_parser("draw", help="draw the graph with each solver's clique highlighted, from saved results")
    d.add_argument("results", help="batch output dir, its results.jsonl, or a `mwcp solve --json` file")
    d.add_argument("--graph", metavar="PATH", help="graph file to use instead of the path in the results "
                                                    "(e.g. results copied from another machine)")
    d.add_argument("--graph-name", metavar="NAME", help="only this graph (file name without extension)")
    d.add_argument("--seed", type=int, help="only this seed")
    d.add_argument("-o", "--out", metavar="PATH",
                   help="output .html for one graph and seed, or a directory for several "
                        "(default: next to the results, or its cliques/ dir)")
    _add_draw_limits(d)
    d.set_defaults(func=_cmd_draw)

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
