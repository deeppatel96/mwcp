// Shared METIS (KaMIS-style) graph reader for the solver drivers.
#pragma once
#include <string>
#include <vector>

struct MetisGraph {
    int n = 0;
    long long m = 0;                     // undirected edges after cleanup
    std::vector<int> weight;             // vertex weights (1 if unweighted); integer reads only
    std::vector<double> weight_real;     // the same weights as read, any real value
    std::vector<std::vector<int>> adj;   // 0-based, sorted, deduplicated, no self loops
};

// Parses a METIS file: header "n m [fmt [ncon]]", '%' comment lines, then one line
// per vertex: [weight] neighbors (1-based) [edge weights are skipped].
// Throws std::runtime_error on malformed input. Warnings go to stderr.
// By default weights must be integers in [0, INT_MAX] (what the solvers take); a decimal or
// negative weight is an error. With real_weights=true any real weight is accepted, kept in
// weight_real (and `weight` is left at 0 where the value is not a valid int).
MetisGraph read_metis(const std::string& path, bool real_weights = false);

// The flat arrays the vendored WLMC/FastWClq library entry points expect.
struct SolverArrays {
    std::vector<int*> adj_ptr;
    std::vector<int> degree, weight, bound;  // bound = w(v) + sum of neighbor weights
    std::vector<std::vector<int>> storage;
};
SolverArrays to_solver_arrays(const MetisGraph& g);

// Quality over time: report_improvement(w) prints "IMPROVE <seconds> <weight>" (stdout, flushed)
// when w beats every weight reported before; seconds count from start_clock(), called first
// thing in main(), so they include reading the graph.
void start_clock();
void report_improvement(long long weight);

// Prints the machine-readable block parsed by the Python wrapper.
void print_result(long long weight, const std::vector<int>& clique, double seconds, bool optimal);
