"""`mwcp batch`: run the solvers over many graphs and seeds, recording every result.

Output directory layout:
  results.jsonl   one JSON object per (graph, seed, solver), appended as each graph finishes
  summary.csv     the same rows without cliques, rewritten at the end of every batch
  runs.jsonl      one line per batch invocation: settings, versions, host
  solutions/      KaMIS-style 0/1 files, with --solutions
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Set, Tuple

from . import REPO_ROOT, __version__
from .graph import GraphFormatError, read_metis, write_kamis_solution
from .instance import PrepError
from .result import Status
from .runner import solve_graph
from .solvers import get_solvers

GRAPH_SUFFIXES = (".graph", ".metis")
CSV_FIELDS = ["graph_name", "graph", "n", "file_edges", "m", "complement", "seed", "timeout", "solver",
              "status", "weight", "size", "proved_optimal", "best_weight", "is_best", "gap",
              "solver_time", "wall_time", "parse_time", "message"]


def collect_graphs(inputs: Iterable[str]) -> List[Path]:
    graphs: List[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            graphs.extend(sorted(f for f in p.iterdir() if f.is_file() and f.suffix in GRAPH_SUFFIXES))
        elif p.is_file():
            graphs.append(p)
        else:
            raise FileNotFoundError(f"no such graph file or directory: {item}")
    return graphs


def _git_commit() -> str:
    env = os.environ.get("MWCP_GIT_COMMIT")  # baked into the Docker image at build time
    if env:
        return env
    try:
        return subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _settings_key(graph: str, seed: int, args) -> Tuple:
    return (graph, seed, bool(args.complement), float(args.timeout), args.kamis_reductions)


def _done_keys(results_path: Path) -> Set[Tuple]:
    done: Set[Tuple] = set()
    if not results_path.is_file():
        return done
    with open(results_path) as fh:
        for line in fh:
            try:
                r = json.loads(line)
                done.add((r["graph"], r["seed"], r["complement"], float(r["timeout"]),
                          r.get("kamis_reductions", "auto")))
            except (ValueError, KeyError):
                continue
    return done


def write_summary(results_path: Path, csv_path: Path) -> int:
    rows = []
    with open(results_path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def run_batch(args, log: Callable[[str], None]) -> int:
    try:
        solvers = get_solvers(args.solvers)
        seeds = [int(x) for x in str(args.seeds).split(",") if x.strip()]
        graphs = collect_graphs(args.inputs)
    except (KeyError, ValueError, FileNotFoundError) as e:
        print(f"error: {e.args[0] if e.args else e}", file=sys.stderr)
        return 2
    if not graphs:
        print("error: no graph files found", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results_path, csv_path = out / "results.jsonl", out / "summary.csv"
    done = _done_keys(results_path) if args.resume else set()
    if not args.resume and results_path.exists() and results_path.stat().st_size:
        log(f"note: appending to existing {results_path} (use a new --out dir for a clean run)")

    run_info = {
        "started": _dt.datetime.now().isoformat(timespec="seconds"),
        "argv": sys.argv, "mwcp_version": __version__, "git_commit": _git_commit(),
        "solvers": [s.name for s in solvers], "seeds": seeds, "timeout": args.timeout,
        "complement": args.complement, "parallel": args.parallel,
        "kamis_reductions": args.kamis_reductions, "graphs": [str(g) for g in graphs],
        "host": {"platform": platform.platform(), "machine": platform.machine(),
                 "cpus": os.cpu_count(), "python": platform.python_version()},
    }
    with open(out / "runs.jsonl", "a") as fh:
        fh.write(json.dumps(run_info) + "\n")

    total = len(graphs) * len(seeds)
    log(f"batch: {len(graphs)} graph(s) x {len(seeds)} seed(s) x {len(solvers)} solver(s) -> {out}")
    failures = 0
    k = 0
    for gpath in graphs:
        todo = [sd for sd in seeds if _settings_key(str(gpath), sd, args) not in done]
        k += len(seeds) - len(todo)
        if not todo:
            log(f"[skip] {gpath.name}: all seeds already done")
            continue
        try:
            graph = read_metis(gpath, complement=args.complement)
        except (OSError, GraphFormatError, ValueError) as e:
            log(f"[error] {gpath.name}: cannot read: {e}")
            failures += 1
            k += len(todo)
            continue
        for seed in todo:
            k += 1
            log(f"[{k}/{total}] {gpath.name} seed={seed}")
            try:
                o = solve_graph(gpath, solvers, timeout=args.timeout, seed=seed,
                                complement=args.complement, parallel=args.parallel,
                                kamis_reductions=args.kamis_reductions, graph=graph, log=log)
            except PrepError as e:
                log(f"[error] {gpath.name}: {e}")
                failures += 1
                continue
            best_w = o.best.weight if o.best else None
            rows: List[Dict] = []
            for r in o.results:
                rows.append({
                    "graph_name": gpath.stem, "graph": str(gpath), "n": graph.n,
                    "file_edges": graph.file_edges, "m": graph.m, "complement": bool(args.complement),
                    "seed": seed, "timeout": float(args.timeout), "kamis_reductions": args.kamis_reductions,
                    "solver": r.solver, "status": r.status, "weight": r.weight,
                    "size": len(r.clique) if r.status == Status.OK else None,
                    "proved_optimal": r.proved_optimal, "best_weight": best_w,
                    "is_best": r.status == Status.OK and r.weight == best_w,
                    "gap": (best_w - r.weight) if (best_w is not None and r.status == Status.OK) else None,
                    "solver_time": r.solver_time, "wall_time": r.wall_time,
                    "parse_time": round(o.parse_seconds, 4), "message": r.message,
                    "clique": r.clique if r.status == Status.OK else None,
                })
                if args.solutions and r.status == Status.OK:
                    sol_dir = out / "solutions"
                    sol_dir.mkdir(exist_ok=True)
                    write_kamis_solution(graph.n, r.clique, sol_dir / f"{gpath.stem}.s{seed}.{r.solver}.sol")
            with open(results_path, "a") as fh:  # append per graph: a crash loses at most one graph
                for row in rows:
                    fh.write(json.dumps(row) + "\n")
            if not o.best:
                failures += 1

    n_rows = write_summary(results_path, csv_path) if results_path.exists() else 0
    log(f"done: {n_rows} result rows in {results_path} and {csv_path}")
    return 0 if failures == 0 else 1
