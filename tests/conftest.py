import random
from pathlib import Path

import pytest

from mwcp.graph import Graph, read_metis
from mwcp.instance import Instance

DATA = Path(__file__).parent / "data"


def write_metis(path: Path, weights, edges, comment=None):
    n = len(weights)
    adj = [set() for _ in range(n)]
    for u, v in edges:
        adj[u].add(v)
        adj[v].add(u)
    m = sum(len(a) for a in adj) // 2
    with open(path, "w") as fh:
        if comment:
            fh.write(f"% {comment}\n")
        fh.write(f"{n} {m} 10\n")
        for v in range(n):
            fh.write(" ".join([str(weights[v])] + [str(u + 1) for u in sorted(adj[v])]) + "\n")
    return path


def brute_force_mwc(g: Graph) -> int:
    """Simple exact B&B, fine for n <= ~25."""
    best = 0
    order = sorted(range(g.n), key=lambda v: -g.weights[v])

    def expand(cand, weight):
        nonlocal best
        if weight > best:
            best = weight
        if weight + sum(g.weights[v] for v in cand) <= best:
            return
        for i, v in enumerate(cand):
            rest = [u for u in cand[i + 1:] if u in g.adj[v]]
            expand(rest, weight + g.weights[v])

    expand(order, 0)
    return best


def random_graph(n, p, seed, wmax=200):
    rng = random.Random(seed)
    weights = [rng.randint(1, wmax) for _ in range(n)]
    edges = [(u, v) for u in range(n) for v in range(u + 1, n) if rng.random() < p]
    return weights, edges


def complement_edges(n, edges):
    present = {(min(u, v), max(u, v)) for u, v in edges}
    return [(u, v) for u in range(n) for v in range(u + 1, n) if (u, v) not in present]


def make_instance(path: Path, workdir: Path, complement: bool = False) -> Instance:
    workdir.mkdir(parents=True, exist_ok=True)
    return Instance(path, read_metis(path, complement=complement), workdir)


@pytest.fixture
def data_dir():
    return DATA
