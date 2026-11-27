"""METIS (KaMIS-style) graph parsing, clique verification and solution I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set


class GraphFormatError(ValueError):
    pass


@dataclass
class Graph:
    """A parsed METIS file, optionally viewed as its complement.

    `adj` always holds the file's own adjacency. With `complemented=True` the graph *meant*
    is the complement (same vertices and weights), but it's never built: edge queries invert.
    """
    n: int
    weights: List  # int, or float for real-valued (e.g. log-likelihood) weights
    adj: List[Set[int]] = field(repr=False)  # 0-based neighbor sets, as in the file
    complemented: bool = False

    @property
    def file_edges(self) -> int:
        return sum(len(a) for a in self.adj) // 2

    @property
    def m(self) -> int:
        """Edge count of the graph meant (the complement, if complemented)."""
        e = self.file_edges
        return self.n * (self.n - 1) // 2 - e if self.complemented else e

    def has_edge(self, u: int, v: int) -> bool:
        return u != v and ((v in self.adj[u]) != self.complemented)

    def clique_violation(self, clique: Sequence[int]) -> Optional[str]:
        """Return why `clique` is not a clique of this graph, or None if it is one."""
        seen = set()
        for v in clique:
            if not 0 <= v < self.n:
                return f"vertex {v} out of range [0, {self.n})"
            if v in seen:
                return f"vertex {v} repeated"
            seen.add(v)
        verts = list(seen)
        for i, u in enumerate(verts):
            for v in verts[i + 1:]:
                if not self.has_edge(u, v):
                    return f"vertices {u} and {v} are not adjacent"
        return None

    def weight_of(self, vertices: Iterable[int]):
        return sum(self.weights[v] for v in vertices)

    @property
    def solver_weights_ok(self) -> bool:
        """True if every weight is a non-negative int, which the solvers require."""
        return all(isinstance(w, int) and w >= 0 for w in self.weights)


def parse_weight(tok: str):
    """A vertex weight: int when the token is an integer, else float (e.g. a log-likelihood)."""
    try:
        return int(tok)
    except ValueError:
        w = float(tok)
        if w != w or w in (float("inf"), float("-inf")):
            raise ValueError(f"bad weight {tok}")
        return w


def _content_lines(path: Path):
    with open(path, "r") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if line.startswith("%"):
                continue
            yield line


def read_metis(path: str | Path, complement: bool = False) -> Graph:
    """Parse a METIS file. Mirrors drivers/common/metis_io.cpp (symmetrizes, drops loops).

    With complement=True the returned Graph stands for the file's complement.
    """
    lines = _content_lines(Path(path))
    header = None
    for line in lines:
        if line.strip():
            header = line.split()
            break
    if header is None or len(header) < 2:
        raise GraphFormatError("missing METIS header")
    try:
        n, _m = int(header[0]), int(header[1])
        fmt = int(header[2]) if len(header) > 2 else 0
        ncon = int(header[3]) if len(header) > 3 else 1
    except ValueError as e:
        raise GraphFormatError(f"bad METIS header: {' '.join(header)}") from e
    has_vsize = (fmt // 100) % 10 == 1
    has_vwgt = (fmt // 10) % 10 == 1
    has_ewgt = fmt % 10 == 1

    weights = [1] * n
    adj: List[Set[int]] = [set() for _ in range(n)]
    v = -1
    for v, line in zip(range(n), lines):
        toks = line.split()
        pos = 0
        if has_vsize:
            pos += 1
        if has_vwgt:
            if len(toks) < pos + ncon:
                raise GraphFormatError(f"missing weight on vertex line {v + 1}")
            try:
                weights[v] = parse_weight(toks[pos])
            except ValueError as e:
                raise GraphFormatError(f"bad weight '{toks[pos]}' on vertex line {v + 1}") from e
            pos += ncon
        step = 2 if has_ewgt else 1
        for t in toks[pos::step]:
            u = int(t) - 1
            if not 0 <= u < n:
                raise GraphFormatError(f"neighbor {u + 1} out of range on vertex line {v + 1}")
            if u != v:
                adj[v].add(u)
                adj[u].add(v)
    if v != n - 1:
        raise GraphFormatError(f"file ends after {v + 1} of {n} vertex lines")
    return Graph(n=n, weights=weights, adj=adj, complemented=complement)


def write_kamis_solution(n: int, clique: Iterable[int], path: str | Path) -> None:
    """KaMIS-style solution file: line i is 1 if vertex i is in the set, else 0.

    On the complement graph a clique is an independent set of the original graph,
    so this file drops in wherever KaMIS output is expected.
    """
    member = [0] * n
    for v in clique:
        member[v] = 1
    with open(path, "w") as fh:
        fh.write("\n".join(map(str, member)))
        if n:
            fh.write("\n")
