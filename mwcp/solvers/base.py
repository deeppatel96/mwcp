from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Tuple

from .. import BIN_DIR
from ..graph import Graph
from ..result import SolverResult, Status

# Extra time a solver gets past its own cutoff before the wrapper hard-kills it (losing its
# best clique). Generous because e.g. WLMC's cutoff excludes its preprocessing time.
def grace_seconds(timeout: float) -> float:
    return max(10.0, 0.5 * timeout)


class Solver(ABC):
    name: str = ""
    binary: str = ""
    exact: bool = False          # can it prove optimality?
    description: str = ""

    @property
    def binary_path(self) -> Path:
        return BIN_DIR / self.binary

    def available(self) -> bool:
        return self.binary_path.is_file() and os.access(self.binary_path, os.X_OK)

    @abstractmethod
    def command(self, graph_path: Path, graph: Graph, timeout: float, seed: int, workdir: Path) -> List[str]:
        """Build the command line. `workdir` is a private temp dir for converted inputs."""

    @abstractmethod
    def parse(self, stdout: str) -> Tuple[int, List[int], bool, Optional[float]]:
        """Return (weight, clique as 0-based ids, proved_optimal, solver_time)."""

    def run(self, graph_path: Path, graph: Graph, timeout: float, seed: int = 0) -> SolverResult:
        res = SolverResult(solver=self.name, status=Status.ERROR)
        if not self.available():
            res.status = Status.UNAVAILABLE
            res.message = f"{self.binary_path} not found; run `mwcp build`"
            return res

        with tempfile.TemporaryDirectory(prefix=f"mwcp-{self.name}-") as tmp:
            cmd = self.command(Path(graph_path), graph, timeout, seed, Path(tmp))
            t0 = time.monotonic()
            # New session so a timeout kill takes down the solver's whole process group.
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, start_new_session=True)
            try:
                out, err = proc.communicate(timeout=timeout + grace_seconds(timeout))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                out, err = proc.communicate()
                res.status = Status.TIMEOUT
                res.wall_time = time.monotonic() - t0
                res.message = f"killed after {timeout + grace_seconds(timeout):.1f}s wall time"
                return res
            res.wall_time = time.monotonic() - t0
            res.returncode = proc.returncode

        if proc.returncode != 0:
            tail = (err or out).strip().splitlines()[-3:]
            res.message = f"exit code {proc.returncode}: " + " | ".join(tail)
            return res
        try:
            weight, clique, optimal, stime = self.parse(out)
        except Exception as e:  # noqa: BLE001 - any parse failure is a solver error
            res.message = f"could not parse solver output: {e}"
            return res

        res.weight, res.clique, res.proved_optimal, res.solver_time = weight, sorted(clique), optimal, stime
        why = graph.clique_violation(res.clique)
        if why is None and graph.weight_of(res.clique) != weight:
            why = f"reported weight {weight} != clique weight {graph.weight_of(res.clique)}"
        if why:
            res.status = Status.INVALID
            res.message = why
            res.proved_optimal = False
        else:
            res.status = Status.OK
        return res


_RESULT_RE = re.compile(r"^RESULT weight=(-?\d+) size=(\d+) time=(\S+) optimal=([01])\s*$", re.M)
_CLIQUE_RE = re.compile(r"^CLIQUE(.*)$", re.M)


def parse_driver_block(stdout: str) -> Tuple[int, List[int], bool, Optional[float]]:
    """Parse the RESULT/CLIQUE block printed by drivers/common/metis_io.cpp."""
    m = _RESULT_RE.search(stdout)
    c = _CLIQUE_RE.search(stdout, m.end()) if m else None
    if not m or not c:
        raise ValueError("RESULT/CLIQUE block not found")
    clique = [int(x) for x in c.group(1).split()]
    if len(clique) != int(m.group(2)):
        raise ValueError("clique size mismatch in RESULT block")
    return int(m.group(1)), clique, m.group(4) == "1", float(m.group(3))
