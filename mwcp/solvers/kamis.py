"""KaMIS weighted MIS solvers, run on the complement of H (an MWIS there is an MWC of H)."""
import re

from .base import RunContext, Solver

_WEIGHT_RE = re.compile(r"^MIS_weight(?:_check)?\s+(-?\d+)\s*$", re.M)
_TIME_RE = re.compile(r"^time\s+(\S+)\s*$", re.M)
# branch_and_reduce_algorithm prints "%timeout" exactly when the search did not complete, so
# its absence means the result is proven optimal. Local search never claims optimality.
_TIMEOUT_RE = re.compile(r"^%timeout\s*$", re.M)

# Density of KaMIS's input (the complement of H) above which its "dense" reduction style is
# used under --kamis-reductions auto. On a 3000-vertex graph at 99% density, "dense" took the
# reductions from 40 s down to 3 s, and they ignore the time limit while running.
DENSE_THRESHOLD = 0.5


def reduction_style(inst) -> str:
    style = inst.options.get("kamis_reductions", "auto")
    if style != "auto":
        return style
    return "dense" if inst.mis_density() >= DENSE_THRESHOLD else "normal"


class _KaMIS(Solver):
    needs = ("mis",)
    exact = False

    def command(self, inst, timeout, seed, workdir):
        return [str(self.binary_path), str(inst.mis_file()), f"--output={workdir / 'is.sol'}",
                f"--time_limit={timeout}", f"--seed={seed}", f"--reduction_style={reduction_style(inst)}"]

    def parse(self, stdout, ctx: RunContext):
        weights = _WEIGHT_RE.findall(stdout)
        if not weights:
            raise ValueError("MIS_weight line not found")
        sol = ctx.workdir / "is.sol"
        if not sol.is_file():
            raise ValueError("KaMIS wrote no solution file")
        clique = [i for i, line in enumerate(sol.read_text().split()) if line == "1"]
        t = _TIME_RE.search(stdout)
        optimal = self.exact and not _TIMEOUT_RE.search(stdout)
        return int(weights[-1]), clique, optimal, float(t.group(1)) if t else None


class KaMISBranchReduce(_KaMIS):
    name = "kamis_br"
    binary = "kamis_branch_reduce"
    exact = True
    description = "KaMIS weighted branch-and-reduce MWIS on the complement (Lamm et al., ALENEX 2019)"


class KaMISLocalSearch(_KaMIS):
    name = "kamis_ls"
    binary = "kamis_weighted_ls"
    exact = False
    description = "KaMIS reductions + weighted iterated local search MWIS on the complement"
