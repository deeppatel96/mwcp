"""The MWC instance being solved, plus the solver input files derived from it.

The graph to solve is H: the input file itself, or its complement with --complement.
Solvers need H in different shapes:

  mwc_file()      H as KaMIS-style METIS (WLMC, FastWClq)
  mis_file()      complement of H as METIS: an MWIS of it is an MWC of H (KaMIS)
  openpls_file()  H as unweighted METIS + .weights file (OpenPLS)

Each is built on first use, once, by bin/metis_tool (C++, so dense graphs are cheap), or is
just the input file when no conversion is needed.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from . import BIN_DIR
from .graph import Graph

TOOL = BIN_DIR / "metis_tool"


class PrepError(RuntimeError):
    pass


class Instance:
    def __init__(self, path: Path, graph: Graph, workdir: Path, options: Optional[dict] = None):
        self.path = Path(path)
        self.options = dict(options or {})  # solver-specific knobs, e.g. kamis_reductions
        self.graph = graph            # view of H (graph.complemented tells which way)
        self.workdir = Path(workdir)
        self._cache: Dict[str, Path] = {}
        self.prep_seconds: Dict[str, float] = {}

    @property
    def complemented(self) -> bool:
        return self.graph.complemented

    def mis_density(self) -> float:
        """Edge density of the complement of H (what the MWIS solvers get)."""
        g = self.graph
        pairs = g.n * (g.n - 1) // 2
        return (pairs - g.m) / pairs if pairs else 0.0

    def _tool(self, *args: str) -> None:
        if not TOOL.is_file():
            raise PrepError(f"{TOOL} not found; run `mwcp build`")
        p = subprocess.run([str(TOOL), *args], capture_output=True, text=True)
        if p.returncode != 0:
            raise PrepError(f"metis_tool {args[0]} failed: {p.stderr.strip()}")

    def _cached(self, key: str, build: Callable[[], Path]) -> Path:
        if key not in self._cache:
            t0 = time.monotonic()
            self._cache[key] = build()
            self.prep_seconds[key] = time.monotonic() - t0
        return self._cache[key]

    def mwc_file(self) -> Path:
        def build():
            if not self.complemented:
                return self.path
            out = self.workdir / "mwc.graph"
            self._tool("complement", str(self.path), str(out))
            return out
        return self._cached("mwc", build)

    def mis_file(self) -> Path:
        def build():
            if self.complemented:
                return self.path  # complement of H is the input itself
            out = self.workdir / "mis.graph"
            self._tool("complement", str(self.path), str(out))
            return out
        return self._cached("mis", build)

    def openpls_file(self) -> Path:
        def build():
            # OpenPLS can't read METIS vertex weights, and only uses its METIS reader when
            # the path contains ".graph".
            out = self.workdir / "openpls.graph"
            args = ["openpls", str(self.path), str(out)]
            if self.complemented:
                args.append("--complement")
            self._tool(*args)
            return out
        return self._cached("openpls", build)

    def prepare(self, needs) -> None:
        """Build the given inputs up front (call before running solvers in parallel)."""
        for need in needs:
            getattr(self, f"{need}_file")()
