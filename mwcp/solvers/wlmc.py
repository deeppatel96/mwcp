from .base import Solver, parse_driver_block


class WLMC(Solver):
    name = "wlmc"
    binary = "wlmc_cli"
    exact = True
    description = "Exact branch-and-bound with MaxSAT reasoning (Jiang, Li & Manyà, AAAI 2017)"

    def command(self, graph_path, graph, timeout, seed, workdir):
        return [str(self.binary_path), str(graph_path), str(timeout)]

    parse = staticmethod(parse_driver_block)
