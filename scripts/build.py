#!/usr/bin/env python3
"""Build and install mwcp from a clone (run from the repository root).

Steps: fetch the git submodules (KaMIS, OpenPLS) if they are missing, compile every solver and
tool with CMake into ./bin, install the Python package into the Python running this script, and
check the result. Needs a C/C++ toolchain, CMake >= 3.20 and Python >= 3.8 (all present in the
project's Ubuntu 20.04 image). Graphviz is only needed at run time, for SVG output of `draw`.

    python3 scripts/build.py                 # or call build() from your build system

The package is installed in editable mode, so it finds its binaries in <repo>/bin: keep the clone
in place after the build (or set MWCP_BIN_DIR to wherever the bin/ directory ends up).
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Don't tune KaMIS to this machine's CPU (-march=native). Keep True if the build may run on a
# different machine than the one it was built on; False is a little faster on the build machine.
PORTABLE = True

BINARIES = ["wlmc_cli", "fastwclq_cli", "pls", "kamis_branch_reduce", "kamis_weighted_ls",
            "metis_tool", "mwcp_exec", "mwcp_cover"]


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def find_cmake() -> str:
    for cand in (shutil.which("cmake"), str(Path(sys.executable).parent / "cmake")):
        if cand and Path(cand).is_file():
            out = subprocess.run([cand, "--version"], capture_output=True, text=True).stdout
            m = re.search(r"(\d+)\.(\d+)", out)
            if m and (int(m.group(1)), int(m.group(2))) >= (3, 20):
                return cand
    raise SystemExit("error: CMake >= 3.20 not found (e.g. `pip install 'cmake>=3.20'`)")


def build(repo: Path = Path.cwd(), portable: bool = PORTABLE) -> None:
    repo = Path(repo).resolve()
    if not (repo / "CMakeLists.txt").is_file() or not (repo / "mwcp").is_dir():
        raise SystemExit(f"error: {repo} is not the mwcp repository root")

    # 1) Submodule sources (skipped when they are already there, e.g. a --recursive clone).
    if not (repo / "third_party/KaMIS/CMakeLists.txt").is_file() or \
            not (repo / "third_party/open-pls/src/main.cpp").is_file():
        run(["git", "submodule", "update", "--init", "--recursive"], cwd=repo)

    # 2) Solvers and tools -> <repo>/bin.
    cmake = find_cmake()
    build_dir = repo / "build"
    run([cmake, "-S", repo, "-B", build_dir, "-DCMAKE_BUILD_TYPE=Release",
         f"-DMWCP_PORTABLE={'ON' if portable else 'OFF'}"])
    run([cmake, "--build", build_dir, "-j", str(os.cpu_count() or 2)])
    missing = [b for b in BINARIES if not (repo / "bin" / b).is_file()]
    if missing:
        raise SystemExit(f"error: build finished but these are missing from {repo / 'bin'}: {', '.join(missing)}")
    shutil.rmtree(build_dir, ignore_errors=True)   # intermediate objects; bin/ holds the results

    # 3) Python package, into the interpreter running this script.
    run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "-e", repo])

    # 4) Smoke check: the package imports and sees every solver as built.
    run([sys.executable, "-c", "from mwcp.cli import main; raise SystemExit(main(['list']))"], cwd="/")
    print(f"mwcp built: binaries in {repo / 'bin'}", flush=True)


if __name__ == "__main__":
    build()
