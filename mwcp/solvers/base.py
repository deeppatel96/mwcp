from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from .. import BIN_DIR
from ..instance import Instance, PrepError
from ..result import SolverResult, Status


def grace_seconds(timeout: float) -> float:
    """Extra time a solver gets past its own cutoff before the wrapper hard-kills it (losing
    its best clique). Generous because e.g. WLMC's cutoff excludes its preprocessing time."""
    return max(10.0, 0.5 * timeout)


LAUNCHER = "mwcp_exec"   # drivers/mwcp_exec.c: runs the solver and reports its peak RSS
_RSS_FILE = ".mwcp_rss"
_RSS_RE = re.compile(r"maxrss_kib=(\d+)")


def read_peak_rss_mb(path: Path) -> Optional[float]:
    """Peak RSS in MiB from the launcher's report file, or None if there is none."""
    try:
        m = _RSS_RE.search(path.read_text())
    except OSError:
        return None
    return round(int(m.group(1)) / 1024, 2) if m and int(m.group(1)) > 0 else None


@dataclass
class Run:
    out: str
    err: str
    returncode: Optional[int]
    wall_time: float
    peak_rss_mb: Optional[float]
    timed_out: bool


def run_measured(cmd: Sequence[str], hard_timeout: float, workdir: Path) -> Run:
    """Run `cmd` through bin/mwcp_exec, which records its peak RSS; kill it after `hard_timeout`.

    The command gets its own session, so a timeout kill takes down its whole process group.
    """
    rss_file = workdir / _RSS_FILE
    full = [str(BIN_DIR / LAUNCHER), str(rss_file)] + list(cmd)
    t0 = time.monotonic()
    proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=hard_timeout)
    except subprocess.TimeoutExpired:
        proc.send_signal(signal.SIGTERM)  # the launcher kills the program, reaps it, writes its RSS
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # anything left in the group
        except ProcessLookupError:
            pass
        out, err = proc.communicate()
        return Run(out, err, None, time.monotonic() - t0, read_peak_rss_mb(rss_file), True)
    return Run(out, err, proc.returncode, time.monotonic() - t0, read_peak_rss_mb(rss_file), False)


@dataclass
class RunContext:
    workdir: Path        # private temp dir for this solver run (e.g. output files)
    timeout: float
    wall_time: float


Parsed = Tuple[int, List[int], bool, Optional[float]]  # weight, clique (0-based), optimal, solver time


class Solver(ABC):
    name: str = ""
    binary: str = ""
    exact: bool = False                 # can it prove optimality?
    description: str = ""
    needs: Sequence[str] = ("mwc",)     # Instance inputs it uses: "mwc", "mis", "openpls"

    @property
    def binary_path(self) -> Path:
        return BIN_DIR / self.binary

    def available(self) -> bool:
        return self.binary_path.is_file() and os.access(self.binary_path, os.X_OK)

    @abstractmethod
    def command(self, inst: Instance, timeout: float, seed: int, workdir: Path) -> List[str]:
        ...

    @abstractmethod
    def parse(self, stdout: str, ctx: RunContext) -> Parsed:
        ...

    def run(self, inst: Instance, timeout: float, seed: int = 0) -> SolverResult:
        res = SolverResult(solver=self.name, status=Status.ERROR)
        if not self.available():
            res.status = Status.UNAVAILABLE
            res.message = f"{self.binary_path} not found; run `mwcp build`"
            return res

        with tempfile.TemporaryDirectory(prefix=f"mwcp-{self.name}-") as tmp:
            workdir = Path(tmp)
            try:
                cmd = self.command(inst, timeout, seed, workdir)
            except PrepError as e:
                res.message = str(e)
                return res
            run = run_measured(cmd, timeout + grace_seconds(timeout), workdir)
            res.wall_time, res.peak_rss_mb = run.wall_time, run.peak_rss_mb
            if run.timed_out:
                res.status = Status.TIMEOUT
                res.message = f"killed after {timeout + grace_seconds(timeout):.1f}s wall time"
                return res
            res.returncode = run.returncode
            out, err = run.out, run.err

            if run.returncode != 0:
                tail = (err or out).strip().splitlines()[-3:]
                res.message = f"exit code {run.returncode}: " + " | ".join(tail)
                return res
            try:
                weight, clique, optimal, stime = self.parse(out, RunContext(workdir, timeout, res.wall_time))
            except Exception as e:  # noqa: BLE001 - any parse failure is a solver error
                res.message = f"could not parse solver output: {e}"
                return res

        g = inst.graph
        res.weight, res.clique, res.proved_optimal, res.solver_time = weight, sorted(clique), optimal, stime
        why = g.clique_violation(res.clique)
        if why is None and g.weight_of(res.clique) != weight:
            why = f"reported weight {weight} != clique weight {g.weight_of(res.clique)}"
        if why:
            res.status = Status.INVALID
            res.message = why
            res.proved_optimal = False
        else:
            res.status = Status.OK
        return res


_RESULT_RE = re.compile(r"^RESULT weight=(-?\d+) size=(\d+) time=(\S+) optimal=([01])\s*$", re.M)
_CLIQUE_RE = re.compile(r"^CLIQUE(.*)$", re.M)


def parse_driver_block(stdout: str, ctx: Optional[RunContext] = None) -> Parsed:
    """Parse the RESULT/CLIQUE block printed by drivers/common/metis_io.cpp."""
    m = _RESULT_RE.search(stdout)
    c = _CLIQUE_RE.search(stdout, m.end()) if m else None
    if not m or not c:
        raise ValueError("RESULT/CLIQUE block not found")
    clique = [int(x) for x in c.group(1).split()]
    if len(clique) != int(m.group(2)):
        raise ValueError("clique size mismatch in RESULT block")
    return int(m.group(1)), clique, m.group(4) == "1", float(m.group(3))
