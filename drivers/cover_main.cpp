// mwcp_cover: the heaviest cliques of a graph, up to a probability coverage.
//
// Model: vertex weights are natural-log scores (e.g. log-likelihood ratios), every clique C,
// including the empty one, is a hypothesis, and P(C) is proportional to exp(w(C)).
//
//   mwcp_cover <graph.metis> [--mode pool|exact] [--coverage 0.99] [--k K] [--time SECONDS]
//              [--seed-time SECONDS] [--max-hypotheses N] [--seed S] [--complement]
//              [--max-memory-mb MB]
//
// pool  (default): randomized search for heavy hypotheses. Fast, no coverage guarantee.
// exact          : pool seed, then best-first branch and bound over the clique tree with
//                  coloring bounds on the mass of every unexplored subtree; the coverage it
//                  reports is proven.
//
// Output (stdout): one COVER summary line, then one "HYP <weight> <vertex ids...>" line per
// returned hypothesis (0-based ids, heaviest first). Masses are reported as natural logs.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <queue>
#include <random>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

#include "common/metis_io.h"

namespace {

using Clock = std::chrono::steady_clock;
using Word = uint64_t;
using LD = long double;
const double NEG_INF = -std::numeric_limits<double>::infinity();

// ---------------------------------------------------------------- log-space helpers

double log_add(double a, double b) {  // log(e^a + e^b)
    if (a == NEG_INF) return b;
    if (b == NEG_INF) return a;
    if (a < b) std::swap(a, b);
    return a + std::log1p(std::exp(b - a));
}
double log1p_exp(double a) { return a > 0 ? a + std::log1p(std::exp(-a)) : std::log1p(std::exp(a)); }
double log_expm1(double x) {  // log(e^x - 1), x >= 0
    if (x <= 0) return NEG_INF;
    return x > 30 ? x + std::log1p(-std::exp(-x)) : std::log(std::expm1(x));
}

// ---------------------------------------------------------------- graph (bitsets)

struct Graph {
    int n = 0, nw = 0;
    std::vector<double> w;                 // internal ids: sorted by weight, heaviest first
    std::vector<int> orig;                 // internal id -> original id
    std::vector<std::vector<Word>> adj;    // bitset rows
};

inline bool test(const std::vector<Word>& b, int i) { return (b[i >> 6] >> (i & 63)) & 1; }
inline void set_bit(std::vector<Word>& b, int i) { b[i >> 6] |= Word(1) << (i & 63); }
inline void clear_bit(std::vector<Word>& b, int i) { b[i >> 6] &= ~(Word(1) << (i & 63)); }
inline int first_bit(const std::vector<Word>& b) {
    for (size_t k = 0; k < b.size(); ++k)
        if (b[k]) return int(k * 64 + __builtin_ctzll(b[k]));
    return -1;
}
inline bool empty(const std::vector<Word>& b) {
    for (Word x : b) if (x) return false;
    return true;
}

Graph build(const MetisGraph& mg, bool complement) {
    Graph g;
    g.n = mg.n;
    g.nw = (g.n + 63) / 64;
    std::vector<int> order(g.n);
    for (int i = 0; i < g.n; ++i) order[i] = i;
    std::stable_sort(order.begin(), order.end(),
                     [&](int a, int b) { return mg.weight_real[a] > mg.weight_real[b]; });
    std::vector<int> pos(g.n);
    for (int i = 0; i < g.n; ++i) pos[order[i]] = i;
    g.orig = order;
    g.w.resize(g.n);
    for (int i = 0; i < g.n; ++i) g.w[i] = mg.weight_real[order[i]];
    g.adj.assign(g.n, std::vector<Word>(g.nw, 0));
    for (int v = 0; v < g.n; ++v)
        for (int u : mg.adj[v]) set_bit(g.adj[pos[v]], pos[u]);
    if (complement) {
        for (int v = 0; v < g.n; ++v) {
            for (int k = 0; k < g.nw; ++k) g.adj[v][k] = ~g.adj[v][k];
            if (g.n % 64) g.adj[v][g.nw - 1] &= (Word(1) << (g.n % 64)) - 1;
            clear_bit(g.adj[v], v);
        }
    }
    return g;
}

// Greedy coloring of P into independent sets (a clique uses at most one vertex per set).
// log_b = log prod_sets (1 + sum_v e^{w_v}): bounds the mass of all cliques inside P, the
// empty one included. w_extra = sum_sets max(0, max_v w_v): bounds their best weight.
void color_bound(const Graph& g, const std::vector<Word>& P, double& log_b, double& w_extra,
                 std::vector<Word>& Q, std::vector<Word>& U) {
    Q = P;
    log_b = 0;
    w_extra = 0;
    for (;;) {
        int v = first_bit(Q);
        if (v < 0) break;
        U = Q;
        const double wmax = g.w[v];        // heaviest of the set: internal ids are weight-sorted
        double s = 0;
        while ((v = first_bit(U)) >= 0) {
            s += std::exp(g.w[v] - wmax);
            for (int k = 0; k < g.nw; ++k) U[k] &= ~g.adj[v][k];
            clear_bit(U, v);
            clear_bit(Q, v);
        }
        log_b += log1p_exp(wmax + std::log(s));
        w_extra += std::max(0.0, wmax);
    }
}

// ---------------------------------------------------------------- found hypotheses

uint64_t hash_clique(const std::vector<int>& c) {  // c sorted (internal ids)
    uint64_t h = 0x9e3779b97f4a7c15ULL ^ c.size();
    for (int v : c) {
        uint64_t x = h ^ (uint64_t(v) + 0x9e3779b97f4a7c15ULL + (h << 6) + (h >> 2));
        x ^= x >> 30; x *= 0xbf58476d1ce4e5b9ULL; x ^= x >> 27; x *= 0x94d049bb133111ebULL; x ^= x >> 31;
        h = x;
    }
    return h;
}

struct Hyp {
    double w;
    std::vector<int> c;  // internal ids, sorted
};

// Every distinct hypothesis found adds its mass to log_z; the heaviest `keep` are stored.
// Dedup is by 64-bit hash. A collision would drop a hypothesis's mass, which can only make the
// reported coverage smaller (never wrongly larger).
struct Found {
    std::unordered_set<uint64_t> seen;
    std::vector<Hyp> heap;  // min-heap by weight, size <= keep
    size_t keep;
    double log_z = NEG_INF;
    explicit Found(size_t k) : keep(k) {}
    static bool cmp(const Hyp& a, const Hyp& b) { return a.w > b.w; }
    bool add(double w, const std::vector<int>& c) {
        if (!seen.insert(hash_clique(c)).second) return false;
        log_z = log_add(log_z, w);
        if (heap.size() < keep) {
            heap.push_back({w, c});
            std::push_heap(heap.begin(), heap.end(), cmp);
        } else if (w > heap.front().w) {
            std::pop_heap(heap.begin(), heap.end(), cmp);
            heap.back() = {w, c};
            std::push_heap(heap.begin(), heap.end(), cmp);
        }
        return true;
    }
    bool has(const std::vector<int>& c) const { return seen.count(hash_clique(c)) > 0; }
    std::vector<Hyp> sorted() const {
        std::vector<Hyp> out = heap;
        std::sort(out.begin(), out.end(), [](const Hyp& a, const Hyp& b) { return a.w > b.w; });
        return out;
    }
};

// ---------------------------------------------------------------- pool search

struct Options {
    std::string mode = "pool";
    double coverage = 0.99;
    long long k = 0;
    double time = 10.0;
    double seed_time = -1;
    long long max_hyp = 10000;
    uint64_t seed = 0;
    bool complement = false;
    double max_mem_mb = 2048;
};

struct Stats {
    long long rounds = 0, nodes = 0;
    std::string stop;
};

double elapsed(Clock::time_point t0) { return std::chrono::duration<double>(Clock::now() - t0).count(); }

// All subsets of clique c (sorted, internal ids) within `cut` nats of its best subset, heaviest
// first, at most `limit`. Flipping a vertex (dropping a positive one or keeping a negative one)
// costs |w|; this is the classic k-smallest-subset-sums enumeration over the sorted costs.
void heavy_subsets(const Graph& g, const std::vector<int>& c, double cut, int limit, Found& found) {
    std::vector<std::pair<double, int>> cost;  // (|w|, vertex)
    std::vector<int> base;                     // best subset: the non-negative vertices
    double wbest = 0;
    for (int v : c) {
        cost.push_back({std::fabs(g.w[v]), v});
        if (g.w[v] >= 0) { base.push_back(v); wbest += g.w[v]; }
    }
    std::sort(cost.begin(), cost.end());
    auto emit = [&](const std::vector<int>& flips) {
        std::vector<int> s = base;
        for (int i : flips) {
            int v = cost[i].second;
            auto it = std::lower_bound(s.begin(), s.end(), v);
            if (it != s.end() && *it == v) s.erase(it); else s.insert(it, v);
        }
        double w = 0;
        for (int v : s) w += g.w[v];
        found.add(w, s);
    };
    emit({});
    if (cost.empty()) return;
    // state: (total cost, flip index list); children: append next index, or bump the last one.
    struct State { double cost; std::vector<int> idx; };
    auto cmp = [](const State& a, const State& b) { return a.cost > b.cost; };
    std::priority_queue<State, std::vector<State>, decltype(cmp)> pq(cmp);
    pq.push({cost[0].first, {0}});
    int emitted = 1;
    while (!pq.empty() && emitted < limit) {
        State s = pq.top(); pq.pop();
        if (s.cost > cut) break;
        emit(s.idx);
        ++emitted;
        int last = s.idx.back();
        if (last + 1 < (int)cost.size()) {
            State a = s; a.idx.push_back(last + 1); a.cost += cost[last + 1].first; pq.push(a);
            State b = s; b.idx.back() = last + 1; b.cost += cost[last + 1].first - cost[last].first; pq.push(b);
        }
    }
    (void)wbest;
}

void pool_search(const Graph& g, const Options& o, double budget, Found& found, Stats& st,
                 Clock::time_point t0, bool final_phase) {
    std::mt19937_64 rng(o.seed * 0x9e3779b97f4a7c15ULL + 1);
    std::uniform_real_distribution<double> unif(1e-12, 1.0 - 1e-12);
    std::vector<double> pw(g.n);
    std::vector<Word> cand(g.nw);
    std::unordered_set<uint64_t> bases;
    const double cut = std::log(1e6);   // subsets down to 1e-6 of their clique's best subset
    const int window = 200;
    double z_window = found.log_z;
    found.add(0.0, {});                 // the empty hypothesis
    for (;;) {
        if (elapsed(t0) >= budget) { if (final_phase) st.stop = "time"; return; }
        for (int v = 0; v < g.n; ++v) {
            double u = unif(rng);
            pw[v] = g.w[v] + std::log(u) - std::log1p(-u);  // logistic = difference of two Gumbels
        }
        std::fill(cand.begin(), cand.end(), 0);
        for (int v = 0; v < g.n; ++v) set_bit(cand, v);
        std::vector<int> c;
        for (;;) {
            int best = -1;
            double bw = 0;
            for (int k = 0; k < g.nw; ++k)
                for (Word x = cand[k]; x; x &= x - 1) {
                    int v = int(k * 64 + __builtin_ctzll(x));
                    if (pw[v] > bw) { bw = pw[v]; best = v; }
                }
            if (best < 0) break;
            c.push_back(best);
            for (int k = 0; k < g.nw; ++k) cand[k] &= g.adj[best][k];
        }
        std::sort(c.begin(), c.end());
        double wc = 0;
        for (int v : c) wc += g.w[v];
        found.add(wc, c);
        // One-vertex additions (common neighbors of c), then all heavy subsets of each new base.
        for (int k = 0; k < g.nw; ++k)
            for (Word x = cand[k]; x; x &= x - 1) {
                int u = int(k * 64 + __builtin_ctzll(x));
                std::vector<int> c2 = c;
                c2.insert(std::lower_bound(c2.begin(), c2.end(), u), u);
                found.add(wc + g.w[u], c2);
                // A positive vertex the noise kept out: its subsets are heavy hypotheses too.
                if (g.w[u] > 0 && bases.insert(hash_clique(c2)).second) heavy_subsets(g, c2, cut, 2000, found);
            }
        if (bases.insert(hash_clique(c)).second) heavy_subsets(g, c, cut, 2000, found);
        ++st.rounds;
        if (st.rounds % window == 0) {
            const double added = 1.0 - std::exp(z_window - found.log_z);
            z_window = found.log_z;
            if (added < 1e-4) { if (final_phase) st.stop = "converged"; return; }
        }
    }
}

// ---------------------------------------------------------------- exact search

struct Node {
    double key;          // priority
    double lmass;        // log of the not-yet-counted mass bound of the subtree
    double wub;          // bound on the best weight in the subtree
    double wc;           // w(C)
    std::vector<int> c;  // the clique (internal ids, ascending)
    std::vector<Word> p; // candidates: vertices adjacent to all of C, after C's last vertex
};

void exact_search(const Graph& g, const Options& o, Found& found, Stats& st, Clock::time_point t0,
                  double& log_r_out, double& max_wub_out) {
    const bool topk = o.k > 0;
    std::vector<Word> Q(g.nw), U(g.nw);
    const double M = std::max(0.0, found.heap.empty() ? 0.0 : found.sorted()[0].w);  // linear-space reference
    auto lin = [&](double x) -> LD { return x == NEG_INF ? 0.0L : std::exp((LD)(x - M)); };

    std::vector<Node> store;
    std::vector<int> free_slots;
    auto cmp = [](const std::pair<double, int>& a, const std::pair<double, int>& b) { return a.first < b.first; };
    std::priority_queue<std::pair<double, int>, std::vector<std::pair<double, int>>, decltype(cmp)> heap(cmp);
    const double node_bytes = g.nw * 8.0 + 96;
    const long long max_nodes = (long long)(o.max_mem_mb * 1024 * 1024 / node_bytes);
    LD R = 0;

    auto make = [&](double wc, std::vector<int> c, std::vector<Word> p) {
        double log_b, w_extra;
        color_bound(g, p, log_b, w_extra, Q, U);
        Node nd;
        nd.wc = wc;
        nd.lmass = wc + log_expm1(log_b);   // all cliques C+S with S nonempty
        nd.wub = wc + w_extra;
        nd.key = topk ? nd.wub : nd.lmass;
        nd.c = std::move(c);
        nd.p = std::move(p);
        if (nd.lmass == NEG_INF) return;    // no candidates left
        R += lin(nd.lmass);
        int slot;
        if (!free_slots.empty()) { slot = free_slots.back(); free_slots.pop_back(); store[slot] = std::move(nd); }
        else { slot = (int)store.size(); store.push_back(std::move(nd)); }
        heap.push({store[slot].key, slot});
    };
    auto exact_r = [&]() {
        LD r = 0;  // priority_queue can't be iterated: sum over the live slots
        std::vector<char> live(store.size(), 1);
        for (int s : free_slots) live[s] = 0;
        for (size_t s = 0; s < store.size(); ++s) if (live[s]) r += lin(store[s].lmass);
        return r;
    };
    auto kth_weight = [&]() {
        if ((long long)found.heap.size() < o.k) return -std::numeric_limits<double>::infinity();
        return found.heap.front().w;  // keep == k in top-k mode: the heap minimum is the k-th best
    };

    found.add(0.0, {});
    std::vector<Word> all(g.nw, 0);
    for (int v = 0; v < g.n; ++v) set_bit(all, v);
    make(0.0, {}, all);

    const double tau = o.coverage;
    long long since_check = 0;
    for (;;) {
        if (heap.empty()) { st.stop = "exhausted"; R = 0; break; }
        if (topk && kth_weight() >= heap.top().first) { st.stop = "topk"; break; }
        if (!topk && since_check++ >= 64) {
            since_check = 0;
            LD zf = lin(found.log_z);
            if (R <= zf * (1 - tau) / tau) {
                R = exact_r();
                if (R <= zf * (1 - tau) / tau) { st.stop = "coverage"; break; }
            }
        }
        if ((st.nodes & 255) == 0) {
            if (elapsed(t0) >= o.time) { st.stop = "time"; break; }
            if ((long long)heap.size() > max_nodes) { st.stop = "memory"; break; }
        }
        if ((st.nodes & 4095) == 4095) R = exact_r();  // undo float drift from the running sum

        int slot = heap.top().second;
        heap.pop();
        Node nd = std::move(store[slot]);
        free_slots.push_back(slot);
        R -= lin(nd.lmass);
        ++st.nodes;

        const int v = first_bit(nd.p);       // heaviest candidate (ids are weight-sorted)
        // Include v: a new clique; its candidates are the common neighbors after v.
        std::vector<int> c2 = nd.c;
        c2.push_back(v);
        std::vector<Word> p2(g.nw);
        for (int k = 0; k < g.nw; ++k) p2[k] = nd.p[k] & g.adj[v][k];
        const double w2 = nd.wc + g.w[v];
        found.add(w2, c2);                   // skipped if the pool already found it
        make(w2, c2, std::move(p2));
        // Exclude v: same clique (already counted), one candidate fewer.
        clear_bit(nd.p, v);
        make(nd.wc, std::move(nd.c), std::move(nd.p));
    }
    if (R < 0) R = 0;
    log_r_out = R <= 0 ? NEG_INF : (double)(std::log(R) + M);
    max_wub_out = NEG_INF;
    if (!heap.empty()) {
        double mx = NEG_INF;
        std::vector<char> live(store.size(), 1);
        for (int s : free_slots) live[s] = 0;
        for (size_t s = 0; s < store.size(); ++s) if (live[s]) mx = std::max(mx, store[s].wub);
        max_wub_out = mx;
    }
}

void usage(const char* prog) {
    std::cerr << "usage: " << prog << " <graph.metis> [--mode pool|exact] [--coverage 0.99] [--k K] "
                 "[--time S] [--seed-time S] [--max-hypotheses N] [--seed S] [--complement] "
                 "[--max-memory-mb MB]\n";
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) { usage(argv[0]); return 2; }
    Options o;
    std::string path = argv[1];
    for (int i = 2; i < argc; ++i) {
        std::string a = argv[i];
        auto val = [&]() -> std::string {
            if (i + 1 >= argc) { usage(argv[0]); std::exit(2); }
            return argv[++i];
        };
        if (a == "--mode") o.mode = val();
        else if (a == "--coverage") o.coverage = std::atof(val().c_str());
        else if (a == "--k") o.k = std::atoll(val().c_str());
        else if (a == "--time") o.time = std::atof(val().c_str());
        else if (a == "--seed-time") o.seed_time = std::atof(val().c_str());
        else if (a == "--max-hypotheses") o.max_hyp = std::atoll(val().c_str());
        else if (a == "--seed") o.seed = std::strtoull(val().c_str(), nullptr, 10);
        else if (a == "--complement") o.complement = true;
        else if (a == "--max-memory-mb") o.max_mem_mb = std::atof(val().c_str());
        else { usage(argv[0]); return 2; }
    }
    if (o.mode != "pool" && o.mode != "exact") { usage(argv[0]); return 2; }
    if (!(o.coverage > 0 && o.coverage < 1)) { std::cerr << "error: --coverage must be in (0, 1)\n"; return 2; }

    try {
        const auto t0 = Clock::now();
        Graph g = build(read_metis(path, /*real_weights=*/true), o.complement);
        const size_t keep = o.k > 0 ? (size_t)o.k : (size_t)std::max<long long>(o.max_hyp, 1);
        Found found(keep);
        Stats st;

        // Global bound on the total mass (all cliques, empty included).
        std::vector<Word> all(g.nw, 0), Q, U;
        for (int v = 0; v < g.n; ++v) set_bit(all, v);
        double log_z_ub, w_extra;
        color_bound(g, all, log_z_ub, w_extra, Q, U);

        double log_r = NEG_INF, max_wub = NEG_INF;
        bool exact = o.mode == "exact";
        if (exact) {
            const double seed_budget = o.seed_time >= 0 ? o.seed_time : 0.1 * o.time;
            if (seed_budget > 0) pool_search(g, o, seed_budget, found, st, t0, false);
            exact_search(g, o, found, st, t0, log_r, max_wub);
        } else {
            pool_search(g, o, o.time, found, st, t0, true);
        }

        // Upper bound on the total mass: what the search proved, capped by the global bound.
        double log_z_upper = log_z_ub;
        if (exact) log_z_upper = std::min(log_z_ub, log_add(found.log_z, log_r));

        std::vector<Hyp> hyps = found.sorted();
        // Returned set: the K heaviest, or the shortest heaviest-first prefix that reaches the
        // target coverage (proven in exact mode, of the mass found in pool mode).
        const double target = exact ? std::log(o.coverage) + log_z_upper : std::log(o.coverage) + found.log_z;
        size_t take = hyps.size();
        if (o.k > 0) {
            take = std::min(hyps.size(), (size_t)o.k);
        } else {
            double z = NEG_INF;
            for (size_t i = 0; i < hyps.size(); ++i) {
                z = log_add(z, hyps[i].w);
                if (z >= target) { take = i + 1; break; }
            }
        }
        take = std::min(take, (size_t)std::max<long long>(o.max_hyp, 1));
        double log_z_ret = NEG_INF;
        for (size_t i = 0; i < take; ++i) log_z_ret = log_add(log_z_ret, hyps[i].w);
        const bool topk_proven = exact && o.k > 0 && take == (size_t)o.k &&
                                 (st.stop == "topk" || st.stop == "exhausted" ||
                                  (take > 0 && hyps[take - 1].w >= max_wub));

        std::printf("COVER mode=%s stop=%s returned=%zu found=%zu log_z_found=%.17g log_z_upper=%.17g "
                    "log_z_returned=%.17g coverage_proved=%.17g coverage_estimate=%.17g topk_proven=%d "
                    "nodes=%lld rounds=%lld time=%.6f\n",
                    o.mode.c_str(), st.stop.c_str(), take, found.seen.size(), found.log_z, log_z_upper,
                    log_z_ret, std::exp(log_z_ret - log_z_upper), std::exp(log_z_ret - found.log_z),
                    topk_proven ? 1 : 0, st.nodes, st.rounds, elapsed(t0));
        for (size_t i = 0; i < take; ++i) {
            std::vector<int> ids;
            for (int v : hyps[i].c) ids.push_back(g.orig[v]);
            std::sort(ids.begin(), ids.end());
            std::printf("HYP %.17g", hyps[i].w);
            for (int v : ids) std::printf(" %d", v);
            std::printf("\n");
        }
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
