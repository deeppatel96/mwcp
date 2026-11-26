# mwcp: Maximum Weight Clique solver wrapper

Runs several **Maximum Weight Clique** solvers on one METIS graph, checks every answer,
and reports the best one.

By default it solves MWC on the input graph **as given**. With `--complement` it solves MWC on
the **complement** of the input file. That's for files that already hold the complement, e.g.
a graph built for an MWIS solver: an MWIS of a graph is an MWC of its complement. Vertex ids
are the same either way.

| Solver | Kind | Source |
|---|---|---|
| `wlmc` | exact branch-and-bound (proves optimality if it finishes before the timeout) | vendored, `third_party/wlmc` |
| `fastwclq` | heuristic for large sparse graphs; proves optimality when its reductions empty the graph | vendored, `third_party/fastwclq` |
| `openpls` | phased local search heuristic (never proves optimality; always runs to the timeout) | git submodule, `third_party/open-pls` |
| `kamis_br` | KaMIS weighted branch-and-reduce, run as **MWIS on the complement** (exact if it finishes) | git submodule, `third_party/KaMIS` |
| `kamis_ls` | KaMIS reductions + iterated local search, MWIS on the complement (heuristic) | git submodule, `third_party/KaMIS` |

Every solver gets the graph in the shape it needs. The conversions are done once per run by
`bin/metis_tool` (C++), and only for the selected solvers:

| Solver | gets | without `--complement` | with `--complement` |
|---|---|---|---|
| WLMC, FastWClq | H, as METIS | the input file | complement of the input file |
| OpenPLS | H, unweighted METIS + `.weights` | converted | converted + complemented |
| KaMIS | complement of H, as METIS | complement of the input file | **the input file as is** |

## Docker (Ubuntu 20.04)

Building, testing and running experiments all happen in the container defined by `Dockerfile`.
`scripts/docker.sh` wraps the `docker` commands:

```sh
git submodule update --init               # the submodule sources are copied into the image
scripts/docker.sh build                   # build the image mwcp:ubuntu20 (compiles all solvers)
scripts/docker.sh test                    # run the test suite inside the container

# Experiments: graphs from DATA_DIR (default ./data) appear read-only at /data, and
# RESULTS_DIR (default ./results) at /results. Output files are owned by you, not root.
DATA_DIR=~/graphs scripts/docker.sh mwcp batch /data -t 300 --seeds 0,1,2 -o /results/run1
scripts/docker.sh mwcp solve /data/g.graph -t 60 --complement
scripts/docker.sh shell                   # bash in the container, same mounts
```

- The image uses the stock Ubuntu 20.04 toolchain: gcc 9, Python 3.8 and OpenMP (so KaMIS builds with
  real OpenMP). CMake comes from pip, because 20.04's 3.16 is too old.
- KaMIS is compiled with `-march=native` by default, which tunes it to the **CPU of the machine
  that builds the image**. If you build on one machine and run on another, build with
  `PORTABLE=ON scripts/docker.sh build`. Locally, `mwcp build --portable` does the same.
- Docker on an Apple Silicon Mac builds an arm64 image by default. For an x86_64 server, build
  there, or cross-build with `PORTABLE=ON scripts/docker.sh build --platform linux/amd64`
  (emulated, so slow).
- The image records the repo commit, which `batch` writes to `runs.jsonl`. A `-dirty` suffix means
  the working tree had uncommitted changes.
- Plain docker also works: `docker build -t mwcp:ubuntu20 .`, then
  `docker run --rm -v $PWD/data:/data:ro -v $PWD/results:/results mwcp:ubuntu20 batch /data -o /results/run1`.
  The image's entrypoint is `mwcp`.

## Local build (macOS / Linux)

```sh
git clone --recursive <this repo>        # or: git submodule update --init --recursive
cd mwcp
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'                   # installs the `mwcp` command, plus cmake and pytest
mwcp build                                # = cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
```

The binaries go to `bin/` (`wlmc_cli`, `fastwclq_cli`, `pls`, `kamis_branch_reduce`,
`kamis_weighted_ls`, `metis_tool`). KaMIS is built as a separate CMake project (ExternalProject).
Without an OpenMP runtime (Apple clang), it builds serially against `cmake/omp_stub/omp.h`.
Its weighted solvers call no OpenMP functions. Pass `-DMWCP_WITH_KAMIS=OFF` to skip it.

## Usage

```sh
mwcp list                                              # solvers, and whether each is built
mwcp solve graph.metis                                 # all solvers, 60 s each, one after another
mwcp solve graph.metis -s wlmc,fastwclq -t 300 -p      # chosen solvers, 300 s, run in parallel
mwcp solve graph.metis --json results.json --solution-out sols/
mwcp solve complement.metis --complement -t 60 -p     # input file holds the complement of the MWC graph
```

`--kamis-reductions auto|normal|dense` sets KaMIS's `--reduction_style`. `auto`, the default,
picks `dense` when KaMIS's input has edge density ≥ 0.5. That's the usual case: KaMIS gets the
complement of H, which is dense when H is sparse. KaMIS's initial reductions don't check the
time limit. On a 3000-vertex graph at 99% density, `normal` took 40 s and `dense` took 3 s.

Output is a table (solver, status, weight, clique size, solver time, wall time, proven optimal),
followed by the best result.

- `--json PATH` writes the full results, including every clique (0-based vertex ids). Use `-` for stdout.
- `--solution-out DIR` writes **KaMIS-style** solution files, with one `0`/`1` line per vertex:
  `<graph>.<solver>.sol` for each valid result, plus `<graph>.best.sol`. On a complement graph,
  this file can be used in place of KaMIS's MWIS output.
- Exit code: `0` if at least one solver returned a valid clique, `1` if none did, `2` for bad input.

### Experiments: `mwcp batch`

```sh
mwcp batch graphs/ more/g.graph -t 300 --seeds 0,1,2 -o results/run1 [--complement] [--solutions] [--resume]
```

This runs every selected solver on every graph (files, or all `*.graph` / `*.metis` files in
the given directories) once per seed. It takes the same solver options as `solve`. In `-o DIR`:

| File | Contents |
|---|---|
| `results.jsonl` | one record per (graph, seed, solver): status, weight, size, proven optimal, best weight for that graph, gap to it, solver and wall time, clique. Appended after each graph, so a crash loses at most the current graph. |
| `summary.csv` | the same rows without cliques, rewritten at the end. Ready for pandas or a spreadsheet. |
| `runs.jsonl` | one line per `batch` call: command line, settings, repo commit, host (platform, CPU count, Python). |
| `solutions/` | with `--solutions`, `<graph>.s<seed>.<solver>.sol` in KaMIS 0/1 format. |

`--resume` skips (graph, seed) pairs that already have results with the same settings
(`--complement`, `--timeout`, `--kamis-reductions`), so an interrupted batch can be restarted.
For timing comparisons, leave out `-p`: WLMC and FastWClq cut off on CPU time, and running solvers
side by side makes them compete for cores.

Each result is **verified** against the input: the vertices must form a clique, and their weights
must add up to the reported weight. A result that fails gets status `invalid`. Other statuses are
`timeout` (killed by the wrapper after timeout + max(10 s, 50%) grace), `error` and `unavailable`.

### Input format

METIS as KaMIS uses it:

- header `n m [fmt]`, where `fmt` `10` means vertex weights and `0` (or no `fmt`) means every weight is 1
- `%` comment lines
- one line per vertex: `[weight] neighbors...`, with 1-based neighbor ids

Edge weights (`fmt` `1`/`11`) are ignored with a warning. Self loops are dropped. An asymmetric
adjacency list is symmetrized. Weights must be non-negative ints, and each vertex's neighborhood
weight sum must fit in a 32-bit int (WLMC and FastWClq use `int`). WLMC accepts at most 999,998 vertices.

## Tests

```sh
python -m pytest              # locally
scripts/docker.sh test        # in the Ubuntu 20.04 container
```

Tests cover parser edge cases, and run every solver on random sparse and dense graphs,
checking the results against a brute-force optimum.

## Adding a solver

1. Get the code into `third_party/`, as a submodule if it has a repo.
2. Add a CMake target in `CMakeLists.txt`. If the solver can't read METIS, write a small driver in
   `drivers/` that reuses `drivers/common/metis_io.{h,cpp}` and prints the `RESULT` / `CLIQUE` block
   (`print_result`).
3. Subclass `mwcp.solvers.base.Solver` (`command()` + `parse()`; reuse `parse_driver_block`
   for drivers) and register it in `mwcp/solvers/registry.py`.

## Notes and caveats

- **Provenance / licensing:** WLMC and FastWClq have no official public git repo. Both are
  vendored from <https://github.com/yuansuny/mwc> (commit `4f17b82`), which has no license file.
  See each folder's `PROVENANCE.md`. Local patches only expose the best clique and the optimality
  flag; they are marked `MWCP-WRAPPER`. OpenPLS is GPLv3. KaMIS is MIT, used unmodified at `2e4b386`.
- **Prefer passing the sparse graph.** `--complement` exists so you can test with existing
  complement files. A dense file costs space and time: on a 3000-vertex test graph, the
  complement file was 39 MB against 413 KB, and parsing plus conversion took about 6 s
  against 0.03 s. The wrapper still parses the file in Python to verify results. The MWC
  solvers then run on the sparse graph H either way. Without `--complement`, only the KaMIS
  solvers need the dense complement, which `metis_tool` writes to a temp directory.
- KaMIS's proof of optimality comes from the absence of its `%timeout` line. KaMIS gets the
  input file unchanged under `--complement`, so that file must already be valid KaMIS input
  (sorted adjacency lists, no self loops), as your KaMIS pipeline already requires. KaMIS uses
  32-bit edge ids: 2·m must fit in an int.
- OpenPLS can't read METIS vertex weights, so the wrapper converts the input to an unweighted
  `.graph` file plus a `.graph.weights` file in a temp directory.
- WLMC's cutoff doesn't count its preprocessing, so its wall time can exceed `--timeout`.
- CPU-time based cutoffs (WLMC, FastWClq) are only comparable across solvers when `-p` isn't
  oversubscribing the cores.
