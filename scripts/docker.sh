#!/usr/bin/env bash
# Build, test and run the MWCP wrapper in its Ubuntu 20.04 container.
#
#   scripts/docker.sh build [docker build args...]   build the image (PORTABLE=ON env for a portable build)
#   scripts/docker.sh test  [pytest args...]          run the test suite inside the container
#   scripts/docker.sh mwcp  <mwcp args...>            run mwcp with DATA_DIR at /data and RESULTS_DIR at /results
#   scripts/docker.sh shell                           interactive shell with the same mounts
#
# Environment: IMAGE (default mwcp:ubuntu20), DATA_DIR (default ./data, mounted read-only),
#              RESULTS_DIR (default ./results), PORTABLE (ON/OFF, build only).
set -euo pipefail

cd "$(dirname "$0")/.."
IMAGE="${IMAGE:-mwcp:ubuntu20}"
DATA_DIR="${DATA_DIR:-$PWD/data}"
RESULTS_DIR="${RESULTS_DIR:-$PWD/results}"

# Fills the MOUNTS array (an array, because these paths may contain spaces).
MOUNTS=()
set_mounts() {
  mkdir -p "$RESULTS_DIR"  # create on the host first so it's owned by you, not root
  [ -d "$DATA_DIR" ] || { echo "error: DATA_DIR $DATA_DIR does not exist" >&2; exit 1; }
  MOUNTS=(-v "$(cd "$DATA_DIR" && pwd):/data:ro" -v "$(cd "$RESULTS_DIR" && pwd):/results")
}

cmd="${1:-help}"
[ $# -gt 0 ] && shift

case "$cmd" in
  build)
    commit="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
    if [ -n "$(git status --porcelain 2>/dev/null)" ]; then commit="${commit}-dirty"; fi
    # Submodule sources must be checked out: they are copied into the image.
    for f in third_party/open-pls/src/main.cpp third_party/KaMIS/CMakeLists.txt; do
      [ -f "$f" ] || { echo "error: $f missing; run: git submodule update --init" >&2; exit 1; }
    done
    docker build -t "$IMAGE" --build-arg GIT_COMMIT="$commit" --build-arg PORTABLE="${PORTABLE:-OFF}" "$@" .
    ;;
  test)
    docker run --rm --entrypoint python3 -w /opt/mwcp "$IMAGE" -m pytest -q -p no:cacheprovider "$@"
    ;;
  mwcp|run)
    set_mounts
    docker run --rm --init --user "$(id -u):$(id -g)" "${MOUNTS[@]}" "$IMAGE" "$@"
    ;;
  shell)
    set_mounts
    docker run --rm -it --init --user "$(id -u):$(id -g)" "${MOUNTS[@]}" --entrypoint bash "$IMAGE"
    ;;
  *)
    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
    [ "$cmd" = help ] || exit 2
    ;;
esac
