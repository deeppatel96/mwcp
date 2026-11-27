#include "metis_io.h"

#include <algorithm>
#include <chrono>
#include <climits>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>

static bool next_content_line(std::ifstream& in, std::string& line) {
    while (std::getline(in, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (!line.empty() && line[0] == '%') continue;  // comment
        return true;
    }
    return false;
}

MetisGraph read_metis(const std::string& path, bool real_weights) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error("cannot open graph file: " + path);

    std::string line;
    // Header: skip comments and blank lines before it.
    do {
        if (!next_content_line(in, line)) throw std::runtime_error("missing METIS header");
    } while (line.find_first_not_of(" \t") == std::string::npos);

    std::istringstream hs(line);
    long long n = 0, m_declared = 0;
    int fmt = 0, ncon = 1;
    if (!(hs >> n >> m_declared)) throw std::runtime_error("bad METIS header: " + line);
    hs >> fmt;
    if (!(hs >> ncon)) ncon = 1;
    if (n < 0 || n > INT_MAX - 2) throw std::runtime_error("vertex count out of range");

    const bool has_vsize = (fmt / 100) % 10 == 1;
    const bool has_vwgt = (fmt / 10) % 10 == 1;
    const bool has_ewgt = fmt % 10 == 1;
    if (has_ewgt) std::cerr << "warning: edge weights present in METIS file; ignoring them\n";
    if (has_vwgt && ncon != 1) std::cerr << "warning: ncon=" << ncon << "; using the first vertex weight\n";

    MetisGraph g;
    g.n = static_cast<int>(n);
    g.weight.assign(g.n, 1);
    g.weight_real.assign(g.n, 1.0);
    g.adj.assign(g.n, {});

    long long self_loops = 0;
    for (int v = 0; v < g.n; ++v) {
        if (!next_content_line(in, line))
            throw std::runtime_error("file ends after " + std::to_string(v) + " of " +
                                     std::to_string(n) + " vertex lines");
        std::istringstream ls(line);
        long long x;
        if (has_vsize) ls >> x;
        if (has_vwgt) {
            std::string tok, first;
            for (int c = 0; c < ncon; ++c) {
                if (!(ls >> tok)) throw std::runtime_error("missing weight on vertex line " + std::to_string(v + 1));
                if (c == 0) first = tok;
            }
            const std::string where = " on vertex line " + std::to_string(v + 1);
            char* end = nullptr;
            const double real = std::strtod(first.c_str(), &end);
            if (end == first.c_str() || *end != '\0' || !std::isfinite(real))
                throw std::runtime_error("bad vertex weight '" + first + "'" + where);
            g.weight_real[v] = real;
            const long long w = std::strtoll(first.c_str(), &end, 10);
            const bool is_int = *end == '\0' && w >= 0 && w <= INT_MAX;
            if (is_int) {
                g.weight[v] = static_cast<int>(w);
            } else if (real_weights) {
                g.weight[v] = 0;
            } else {
                throw std::runtime_error("vertex weight " + first + where + ": the solvers need integer weights "
                                         "in [0, " + std::to_string(INT_MAX) + "]; real-valued (e.g. log-likelihood) "
                                         "weights are supported by `mwcp cover`");
            }
        }
        long long u;
        while (ls >> u) {
            if (has_ewgt) ls >> x;
            if (u < 1 || u > n)
                throw std::runtime_error("neighbor " + std::to_string(u) + " out of range on vertex line " + std::to_string(v + 1));
            if (u - 1 == v) { ++self_loops; continue; }
            g.adj[v].push_back(static_cast<int>(u - 1));
        }
    }

    // Symmetrize + dedupe so the solvers always see a simple undirected graph.
    long long asym = 0;
    std::vector<std::vector<int>> sym(g.n);
    for (int v = 0; v < g.n; ++v)
        for (int u : g.adj[v]) { sym[v].push_back(u); sym[u].push_back(v); }
    long long directed = 0;
    for (int v = 0; v < g.n; ++v) {
        std::sort(sym[v].begin(), sym[v].end());
        sym[v].erase(std::unique(sym[v].begin(), sym[v].end()), sym[v].end());
        std::sort(g.adj[v].begin(), g.adj[v].end());
        g.adj[v].erase(std::unique(g.adj[v].begin(), g.adj[v].end()), g.adj[v].end());
        asym += (long long)(sym[v].size() - g.adj[v].size());
        directed += (long long)sym[v].size();
    }
    g.adj.swap(sym);
    g.m = directed / 2;

    if (self_loops) std::cerr << "warning: dropped " << self_loops << " self loops\n";
    if (asym) std::cerr << "warning: adjacency was not symmetric; added " << asym << " reverse entries\n";
    if (g.m != m_declared)
        std::cerr << "warning: header declares " << m_declared << " edges, found " << g.m << "\n";
    return g;
}

SolverArrays to_solver_arrays(const MetisGraph& g) {
    SolverArrays a;
    a.storage = g.adj;
    a.adj_ptr.resize(g.n);
    a.degree.resize(g.n);
    a.weight = g.weight;
    a.bound.resize(g.n);
    for (int v = 0; v < g.n; ++v) {
        a.adj_ptr[v] = a.storage[v].data();
        a.degree[v] = static_cast<int>(a.storage[v].size());
        long long b = g.weight[v];
        for (int u : g.adj[v]) b += g.weight[u];
        if (b > INT_MAX) throw std::runtime_error("neighborhood weight sum overflows int (solver uses int weights)");
        a.bound[v] = static_cast<int>(b);
    }
    return a;
}

static std::chrono::steady_clock::time_point g_start = std::chrono::steady_clock::now();
static bool g_reported = false;
static long long g_best = 0;

void start_clock() { g_start = std::chrono::steady_clock::now(); }

void report_improvement(long long weight) {
    if (g_reported && weight <= g_best) return;
    g_reported = true;
    g_best = weight;
    const double t = std::chrono::duration<double>(std::chrono::steady_clock::now() - g_start).count();
    std::fflush(stdout);  // keep order with the solvers' own printf output
    std::printf("IMPROVE %.6f %lld\n", t, weight);
    std::fflush(stdout);
}

void print_result(long long weight, const std::vector<int>& clique, double seconds, bool optimal) {
    std::fflush(stdout);
    std::cout << "\nRESULT weight=" << weight << " size=" << clique.size() << " time=" << seconds
              << " optimal=" << (optimal ? 1 : 0) << "\nCLIQUE";
    for (int v : clique) std::cout << ' ' << v;
    std::cout << std::endl;
}
