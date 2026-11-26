// Shared METIS (KaMIS-style) graph reader for the solver drivers.
#pragma once
#include <string>
#include <vector>

struct MetisGraph {
    int n = 0;
    long long m = 0;                     // undirected edges after cleanup
    std::vector<int> weight;             // vertex weights (1 if unweighted)
    std::vector<std::vector<int>> adj;   // 0-based, sorted, deduplicated, no self loops
};

// Parses a METIS file: header "n m [fmt [ncon]]", '%' comment lines, then one line
// per vertex: [weight] neighbors (1-based) [edge weights are skipped].
// Throws std::runtime_error on malformed input. Warnings go to stderr.
MetisGraph read_metis(const std::string& path);

// The flat arrays the vendored WLMC/FastWClq library entry points expect.
struct SolverArrays {
    std::vector<int*> adj_ptr;
    std::vector<int> degree, weight, bound;  // bound = w(v) + sum of neighbor weights
    std::vector<std::vector<int>> storage;
};
SolverArrays to_solver_arrays(const MetisGraph& g);

// Prints the machine-readable block parsed by the Python wrapper.
void print_result(long long weight, const std::vector<int>& clique, double seconds, bool optimal);
