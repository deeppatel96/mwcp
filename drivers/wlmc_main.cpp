// wlmc_cli <graph.metis> [cutoff_seconds]
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <vector>

#include "common/metis_io.h"
extern "C" {
#include "wlmc.h"
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: " << argv[0] << " <graph.metis> [cutoff_seconds=1000]\n";
        return 2;
    }
    const double cutoff = argc > 2 ? std::atof(argv[2]) : 1000.0;
    try {
        MetisGraph g = read_metis(argv[1]);
        if (g.n > wlmc_max_nodes()) {
            std::cerr << "error: WLMC supports at most " << wlmc_max_nodes() << " vertices (graph has " << g.n << ")\n";
            return 3;
        }
        if (g.n == 0) { print_result(0, {}, 0.0, true); return 0; }
        SolverArrays a = to_solver_arrays(g);
        auto t0 = std::chrono::steady_clock::now();
        int w = wlmc(g.n, (int)g.m, cutoff, a.adj_ptr.data(), a.degree.data(), a.weight.data(), a.bound.data());
        double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        std::vector<int> clique(wlmc_clique_size());
        wlmc_get_clique(clique.data());
        print_result(w, clique, secs, !wlmc_timed_out());
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
