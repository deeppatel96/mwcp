from .base import Solver, parse_driver_block


class WLMC(Solver):
    name = "wlmc"
    binary = "wlmc_cli"
    exact = True
    description = "Exact branch-and-bound with MaxSAT reasoning (Jiang, Li & Manyà, AAAI 2017)"

    def command(self, inst, timeout, seed, workdir):
        return [str(self.binary_path), str(inst.mwc_file()), str(timeout)]

    def parse(self, stdout, ctx):
        return parse_driver_block(stdout)
