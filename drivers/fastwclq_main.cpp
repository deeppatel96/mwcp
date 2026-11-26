// fastwclq_cli <graph.metis> [cutoff_seconds] [seed]
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <vector>

#include "common/metis_io.h"
#include "fastwclq.h"

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: " << argv[0] << " <graph.metis> [cutoff_seconds=1000] [seed=0]\n";
        return 2;
    }
    const double cutoff = argc > 2 ? std::atof(argv[2]) : 1000.0;
    const unsigned seed = argc > 3 ? (unsigned)std::strtoul(argv[3], nullptr, 10) : 0u;
    try {
        MetisGraph g = read_metis(argv[1]);
        if (g.n == 0) { print_result(0, {}, 0.0, true); return 0; }
        SolverArrays a = to_solver_arrays(g);
        std::srand(seed);  // fastwclq() draws its internal seed from rand()
        auto t0 = std::chrono::steady_clock::now();
        int w = fastwclq(g.n, (int)g.m, cutoff, a.adj_ptr.data(), a.degree.data(), a.weight.data(), a.bound.data());
        double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        std::vector<int> clique(fastwclq_clique_size());
        fastwclq_get_clique(clique.data());
        print_result(w, clique, secs, fastwclq_proved_optimal() != 0);
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
