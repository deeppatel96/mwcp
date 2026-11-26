from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional


class Status:
    OK = "ok"                # finished (or hit its own cutoff) and reported a clique
    TIMEOUT = "timeout"      # killed by the wrapper's hard wall-clock limit
    ERROR = "error"          # crashed / bad exit code / unparsable output
    INVALID = "invalid"      # reported vertices are not a clique, or weight mismatch
    UNAVAILABLE = "unavailable"  # binary not built


@dataclass
class SolverResult:
    solver: str
    status: str
    weight: Optional[int] = None
    clique: List[int] = field(default_factory=list)
    proved_optimal: bool = False
    solver_time: Optional[float] = None   # time reported by the solver itself
    wall_time: Optional[float] = None     # wall time measured by the wrapper
    peak_rss_mb: Optional[float] = None   # peak resident memory of the solver process (MiB)
    message: str = ""
    returncode: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)
