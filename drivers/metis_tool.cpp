// metis_tool: graph conversions for the mwcp wrapper (fast C++ so dense graphs are cheap).
//
//   metis_tool complement IN OUT            complement of IN as KaMIS METIS ("n m 10", sorted lists)
//   metis_tool openpls    IN OUT [--complement]
//        OpenPLS input: unweighted METIS OUT plus OUT.weights ("<0-based id> <weight>" per line),
//        of IN itself or (with --complement) of its complement.
#include <climits>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "common/metis_io.h"

namespace {

struct Out {
    FILE* f;
    std::vector<char> buf;
    explicit Out(const std::string& path) : buf(1 << 20) {
        f = std::fopen(path.c_str(), "w");
        if (!f) throw std::runtime_error("cannot open output: " + path);
        std::setvbuf(f, buf.data(), _IOFBF, buf.size());
    }
    void close() {
        if (std::fclose(f) != 0) throw std::runtime_error("error writing output");
        f = nullptr;
    }
    ~Out() { if (f) std::fclose(f); }
};

// Calls fn(u) for each neighbor u of v in the (optionally complemented) graph, ascending.
template <class F>
void for_neighbors(const MetisGraph& g, int v, bool complement, F fn) {
    const std::vector<int>& a = g.adj[v];  // sorted
    if (!complement) { for (int u : a) fn(u); return; }
    size_t k = 0;
    for (int u = 0; u < g.n; ++u) {
        if (k < a.size() && a[k] == u) { ++k; continue; }
        if (u != v) fn(u);
    }
}

long long edge_count(const MetisGraph& g, bool complement) {
    long long n = g.n;
    return complement ? n * (n - 1) / 2 - g.m : g.m;
}

void write_metis(const MetisGraph& g, bool complement, bool weighted, const std::string& path) {
    const long long m = edge_count(g, complement);
    if (2 * m > INT_MAX)
        std::cerr << "warning: output has " << m << " edges; tools built with 32-bit edge ids "
                     "(e.g. KaMIS without 64BITMODE) cannot read it\n";
    Out out(path);
    if (weighted) std::fprintf(out.f, "%d %lld 10\n", g.n, m);
    else          std::fprintf(out.f, "%d %lld\n", g.n, m);
    for (int v = 0; v < g.n; ++v) {
        bool first = true;
        if (weighted) { std::fprintf(out.f, "%d", g.weight[v]); first = false; }
        for_neighbors(g, v, complement, [&](int u) {
            std::fprintf(out.f, first ? "%d" : " %d", u + 1);  // no trailing spaces (OpenPLS is strict)
            first = false;
        });
        std::fputc('\n', out.f);
    }
    out.close();
}

int usage(const char* argv0) {
    std::cerr << "usage: " << argv0 << " complement IN OUT\n"
              << "       " << argv0 << " openpls IN OUT [--complement]\n";
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) return usage(argv[0]);
    const std::string mode = argv[1], in = argv[2], out = argv[3];
    const bool flag_complement = argc > 4 && std::strcmp(argv[4], "--complement") == 0;
    try {
        MetisGraph g = read_metis(in);
        if (mode == "complement") {
            write_metis(g, true, true, out);
        } else if (mode == "openpls") {
            write_metis(g, flag_complement, false, out);
            Out w(out + ".weights");
            for (int v = 0; v < g.n; ++v) std::fprintf(w.f, "%d %d\n", v, g.weight[v]);
            w.close();
        } else {
            return usage(argv[0]);
        }
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
