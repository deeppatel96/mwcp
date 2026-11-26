from .base import Solver, parse_driver_block


class FastWClq(Solver):
    name = "fastwclq"
    binary = "fastwclq_cli"
    exact = False  # semi-exact: proves optimality when its reductions empty the graph
    description = "Construct-and-reduce heuristic for large sparse graphs (Cai & Lin, IJCAI 2016)"

    def command(self, graph_path, graph, timeout, seed, workdir):
        return [str(self.binary_path), str(graph_path), str(timeout), str(seed)]

    parse = staticmethod(parse_driver_block)
