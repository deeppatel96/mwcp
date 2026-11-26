from .base import Solver, parse_driver_block


class FastWClq(Solver):
    name = "fastwclq"
    binary = "fastwclq_cli"
    exact = False  # semi-exact: proves optimality when its reductions empty the graph
    description = "Construct-and-reduce heuristic for large sparse graphs (Cai & Lin, IJCAI 2016)"

    def command(self, inst, timeout, seed, workdir):
        return [str(self.binary_path), str(inst.mwc_file()), str(timeout), str(seed)]

    def parse(self, stdout, ctx):
        return parse_driver_block(stdout)
