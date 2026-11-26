# MWCP solver wrapper on Ubuntu 20.04: build, test and run experiments.
#
#   scripts/docker.sh build      # or: docker build -t mwcp:ubuntu20 .
#   scripts/docker.sh test
#   scripts/docker.sh mwcp batch /data -t 60 --seeds 0,1,2 -o /results/run1
#
# Build args:
#   PORTABLE=ON    don't tune KaMIS for the build machine's CPU (-march=native). Use it when the
#                  image is built on one machine and run on another.
#   GIT_COMMIT     recorded in batch results (runs.jsonl). scripts/docker.sh fills it in.
FROM ubuntu:20.04

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential python3 python3-venv python3-pip ca-certificates \
    graphviz \
 && rm -rf /var/lib/apt/lists/*

# Ubuntu 20.04 ships CMake 3.16 and the build needs >= 3.20, so CMake comes from pip.
# Python is the system 3.8.
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN python3 -m venv /opt/venv \
 && pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir "cmake==3.31.*" "pytest>=7,<9"

WORKDIR /opt/mwcp

# 1) Solver binaries. Only the C/C++ sources are copied, so editing Python code doesn't
#    trigger a rebuild of the solvers.
COPY CMakeLists.txt ./
COPY cmake cmake
COPY drivers drivers
COPY third_party third_party
ARG PORTABLE=OFF
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DMWCP_PORTABLE=${PORTABLE} \
 && cmake --build build -j"$(nproc)" \
 && rm -rf build \
 && ls -l bin

# 2) Python wrapper (editable, so it finds /opt/mwcp/bin) and the test suite.
COPY pyproject.toml README.md ./
COPY mwcp mwcp
COPY tests tests
RUN pip install --no-cache-dir -e . && mwcp list

ARG GIT_COMMIT=unknown
ENV MWCP_GIT_COMMIT=${GIT_COMMIT}

# Mount points for experiments: graphs in /data (read-only), results in /results.
RUN mkdir -p /data /results && chmod 777 /results
WORKDIR /results
ENTRYPOINT ["mwcp"]
CMD ["--help"]
