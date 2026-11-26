"""Solver registry. To add a solver: write a Solver subclass and list it here."""
from typing import Dict, List

from .base import Solver
from .fastwclq import FastWClq
from .openpls import OpenPLS
from .wlmc import WLMC

REGISTRY: Dict[str, Solver] = {s.name: s for s in (WLMC(), FastWClq(), OpenPLS())}


def get_solvers(spec: str) -> List[Solver]:
    if spec.strip().lower() == "all":
        return list(REGISTRY.values())
    names = [x.strip().lower() for x in spec.split(",") if x.strip()]
    unknown = [x for x in names if x not in REGISTRY]
    if unknown:
        raise KeyError(f"unknown solver(s): {', '.join(unknown)}; choose from {', '.join(REGISTRY)}")
    return [REGISTRY[x] for x in names]
