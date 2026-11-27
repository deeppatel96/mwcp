"""`mwcp cover`: the heaviest hypotheses (cliques) up to a probability coverage.

Model: vertex weights are natural-log scores (e.g. log-likelihood ratios against a false-alarm
baseline). Every clique, including the empty one, is a hypothesis, and P(C) is proportional to
exp(w(C)). The work is done by bin/mwcp_cover (drivers/cover_main.cpp):

  pool  (default)  randomized search for heavy hypotheses; fast, no coverage guarantee.
  exact            pool seed + best-first branch and bound with coloring bounds; the coverage
                   it reports is proven, whenever it stops.
"""
from __future__ import annotations

import math
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from . import BIN_DIR
from .graph import Graph, read_metis
from .solvers.base import grace_seconds, run_measured

BINARY = "mwcp_cover"
# Stop reasons after which the reported coverage is the requested one, proven.
PROVEN_STOPS = {"coverage", "exhausted", "topk"}


class CoverError(RuntimeError):
    pass


@dataclass
class Hypothesis:
    rank: int
    weight: float
    vertices: List[int]
    p_low: float          # exp(w) / upper bound on the total mass: a proven lower bound on P
    p_high: float         # exp(w) / mass found: an upper bound on P (an estimate in pool mode)


@dataclass
class CoverResult:
    mode: str
    stop: str
    coverage_target: Optional[float]
    k: int
    coverage_proved: float     # proven lower bound on the returned set's probability
    coverage_estimate: float   # its share of all mass found (an overestimate)
    log_z_found: float
    log_z_upper: float
    found: int
    nodes: int
    rounds: int
    seconds: float
    topk_proven: bool
    max_hypotheses: int
    wall_time: float
    peak_rss_mb: Optional[float]
    hypotheses: List[Hypothesis] = field(default_factory=list)

    @property
    def guaranteed(self) -> bool:
        """True when the result meets the request with proof (coverage reached, or top-K proven)."""
        if self.mode != "exact":
            return False
        if self.k:
            return self.topk_proven
        return self.stop in PROVEN_STOPS and self.coverage_proved >= (self.coverage_target or 0) - 1e-12

    def to_dict(self) -> dict:
        d = asdict(self)
        d["guaranteed"] = self.guaranteed
        return d


def _parse(out: str) -> dict:
    head = next((l for l in out.splitlines() if l.startswith("COVER ")), None)
    if head is None:
        raise CoverError("COVER line not found in mwcp_cover output")
    info = dict(kv.split("=", 1) for kv in head.split()[1:])
    hyps = []
    for line in out.splitlines():
        if line.startswith("HYP"):
            toks = line.split()
            hyps.append((float(toks[1]), [int(x) for x in toks[2:]]))
    return {"info": info, "hyps": hyps}


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6 * (1 + abs(a) + abs(b))


def run_cover(graph_path: Path, *, mode: str = "pool", coverage: float = 0.99, k: int = 0,
              time_limit: float = 10.0, seed_time: Optional[float] = None, max_hypotheses: int = 10000,
              seed: int = 0, complement: bool = False, max_memory_mb: float = 2048,
              graph: Optional[Graph] = None) -> CoverResult:
    graph_path = Path(graph_path)
    exe = BIN_DIR / BINARY
    if not exe.is_file():
        raise CoverError(f"{exe} not found; run `mwcp build`")
    cmd = [str(exe), str(graph_path), "--mode", mode, "--coverage", repr(coverage), "--time", repr(time_limit),
           "--max-hypotheses", str(max_hypotheses), "--seed", str(seed), "--max-memory-mb", repr(max_memory_mb)]
    if k:
        cmd += ["--k", str(k)]
    if seed_time is not None:
        cmd += ["--seed-time", repr(seed_time)]
    if complement:
        cmd.append("--complement")
    with tempfile.TemporaryDirectory(prefix="mwcp-cover-") as tmp:
        run = run_measured(cmd, time_limit + grace_seconds(time_limit), Path(tmp))
    if run.timed_out:
        raise CoverError(f"mwcp_cover did not stop within {time_limit + grace_seconds(time_limit):.0f}s")
    if run.returncode != 0:
        tail = (run.err or run.out).strip().splitlines()[-3:]
        raise CoverError(f"mwcp_cover failed (exit {run.returncode}): " + " | ".join(tail))
    parsed = _parse(run.out)
    info = parsed["info"]

    # Verify every hypothesis against the graph: a clique, with the reported weight.
    g = graph if graph is not None else read_metis(graph_path, complement=complement)
    lz_found, lz_upper = float(info["log_z_found"]), float(info["log_z_upper"])
    hyps = []
    for rank, (w, verts) in enumerate(parsed["hyps"], 1):
        why = g.clique_violation(verts)
        if why is None and not _close(g.weight_of(verts), w):
            why = f"reported weight {w} != {g.weight_of(verts)}"
        if why:
            raise CoverError(f"hypothesis {rank} is invalid: {why}")
        hyps.append(Hypothesis(rank, w, verts, math.exp(w - lz_upper), math.exp(w - lz_found)))
    return CoverResult(
        mode=info["mode"], stop=info["stop"], coverage_target=None if k else coverage, k=k,
        coverage_proved=float(info["coverage_proved"]), coverage_estimate=float(info["coverage_estimate"]),
        log_z_found=lz_found, log_z_upper=lz_upper, found=int(info["found"]), nodes=int(info["nodes"]),
        rounds=int(info["rounds"]), seconds=float(info["time"]), topk_proven=info["topk_proven"] == "1",
        max_hypotheses=max_hypotheses,
        wall_time=run.wall_time, peak_rss_mb=run.peak_rss_mb, hypotheses=hyps)


def fmt_weight(w) -> str:
    return f"{w:,}" if isinstance(w, int) else f"{w:,.3f}"


def format_table(res: CoverResult, limit: int = 50) -> str:
    lines = []
    capped = res.k == 0 and len(res.hypotheses) >= res.max_hypotheses
    if res.mode == "exact":
        what = "proven" if res.guaranteed else "NOT reached; proven so far"
        lines.append(f"mode exact, stop: {res.stop}. Coverage of the returned set: {res.coverage_proved:.4%} "
                     f"({what}).")
        if not res.guaranteed and res.stop in PROVEN_STOPS and capped:
            lines.append(f"The target was proven for all {res.found:,} hypotheses found, but reaching it takes more "
                         f"than --max-hypotheses {res.max_hypotheses:,}. Raise it, or see the README on weak tracks.")
    else:
        lines.append(f"mode pool, stop: {res.stop}. Coverage estimate {res.coverage_estimate:.4%} of the "
                     f"mass found (no guarantee); proven floor {res.coverage_proved:.4%}.")
    lines.append(f"{len(res.hypotheses)} hypotheses returned of {res.found:,} found; "
                 f"{res.nodes:,} search nodes, {res.rounds:,} pool rounds, {res.seconds:.2f}s")
    rows = [("rank", "weight", "size", "P low", "P high", "cumul. high", "vertices")]
    cum = 0.0
    for h in res.hypotheses[:limit]:
        cum += h.p_high
        verts = " ".join(map(str, h.vertices[:12])) + (" ..." if len(h.vertices) > 12 else "")
        rows.append((str(h.rank), f"{h.weight:.4f}", str(len(h.vertices)), f"{h.p_low:.3e}",
                     f"{h.p_high:.3e}", f"{cum:.4%}", verts))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]) - 1)]
    for i, r in enumerate(rows):
        lines.append("  ".join(c.ljust(w) for c, w in zip(r, widths)) + "  " + r[-1])
        if i == 0:
            lines.append("  ".join("-" * w for w in widths))
    if len(res.hypotheses) > limit:
        lines.append(f"... {len(res.hypotheses) - limit} more (see --json)")
    return "\n".join(lines)
