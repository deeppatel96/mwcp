import re

from ..graph import write_openpls_input
from .base import Solver

_WEIGHT_RE = re.compile(r"^mwc\s*:\s*(\S+)\s*$", re.M)
_SOL_RE = re.compile(r"^best-solution\s*:(.*)$", re.M)
_TIME_RE = re.compile(r"^time\(s\)\s*:\s*(\S+)\s*$", re.M)


class OpenPLS(Solver):
    name = "openpls"
    binary = "pls"
    exact = False
    description = "Phased local search, sparse-graph implementation (Pullan 2006; Strash)"

    def command(self, graph_path, graph, timeout, seed, workdir):
        # OpenPLS can't read vertex weights from METIS and only uses its METIS reader when
        # the path contains ".graph", so convert to <tmp>/input.graph + input.graph.weights.
        converted = workdir / "input.graph"
        write_openpls_input(graph, converted)
        return [str(self.binary_path), "--algorithm=clique", "--weighted", "--use-weight-file",
                f"--input-file={converted}", f"--timeout={timeout}", f"--random-seed={seed}"]

    def parse(self, stdout):
        w, s = _WEIGHT_RE.search(stdout), _SOL_RE.search(stdout)
        if not w or not s:
            raise ValueError("mwc/best-solution lines not found")
        weight = float(w.group(1))
        if weight != int(weight):
            raise ValueError(f"non-integer weight {weight}")
        t = _TIME_RE.search(stdout)
        return int(weight), [int(x) for x in s.group(1).split()], False, float(t.group(1).rstrip("s")) if t else None
