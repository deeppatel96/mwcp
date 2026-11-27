cmake_minimum_required(VERSION 3.20)
project(mwcp_solvers C CXX)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_FLAGS_RELEASE "-O3 -DNDEBUG")
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -DNDEBUG")

# All solver binaries land in <repo>/bin, where the Python wrapper looks for them.
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/bin)

# Vendored research code: silence its warnings instead of patching it.
set(THIRD_PARTY_WARN_OFF -w)

# ---------------------------------------------------------------- shared reader
add_library(metis_io STATIC drivers/common/metis_io.cpp)
target_include_directories(metis_io PUBLIC drivers)
target_compile_options(metis_io PRIVATE -Wall -Wextra)

# ---------------------------------------------------------------- graph conversion tool (complement, OpenPLS input)
# Launcher that runs a solver and reports its own peak RSS (plain C: tiny, so it adds ~1 MiB at most).
add_executable(mwcp_exec drivers/mwcp_exec.c)

# Hypothesis coverage search (mwcp cover): real-valued weights, pool and exact modes.
add_executable(mwcp_cover drivers/cover_main.cpp)
target_link_libraries(mwcp_cover PRIVATE metis_io)

add_executable(metis_tool drivers/metis_tool.cpp)
target_link_libraries(metis_tool PRIVATE metis_io)

# ---------------------------------------------------------------- WLMC (exact)
add_executable(wlmc_cli drivers/wlmc_main.cpp third_party/wlmc/wlmc.c)
target_include_directories(wlmc_cli PRIVATE third_party/wlmc)
target_link_libraries(wlmc_cli PRIVATE metis_io m)
set_source_files_properties(third_party/wlmc/wlmc.c PROPERTIES COMPILE_OPTIONS "${THIRD_PARTY_WARN_OFF}")

# ---------------------------------------------------------------- FastWClq (heuristic, semi-exact)
add_executable(fastwclq_cli drivers/fastwclq_main.cpp third_party/fastwclq/fastwclq.cpp)
target_include_directories(fastwclq_cli PRIVATE third_party/fastwclq)
target_link_libraries(fastwclq_cli PRIVATE metis_io)
set_source_files_properties(third_party/fastwclq/fastwclq.cpp PROPERTIES COMPILE_OPTIONS "${THIRD_PARTY_WARN_OFF}")

# ---------------------------------------------------------------- OpenPLS (submodule, built from its sources)
set(OPENPLS_DIR ${CMAKE_SOURCE_DIR}/third_party/open-pls)
if(NOT EXISTS ${OPENPLS_DIR}/src/main.cpp)
  message(FATAL_ERROR "OpenPLS submodule missing: run `git submodule update --init --recursive`")
endif()
file(GLOB OPENPLS_SOURCES CONFIGURE_DEPENDS ${OPENPLS_DIR}/src/*.cpp)
add_executable(pls ${OPENPLS_SOURCES})
target_compile_definitions(pls PRIVATE GIT_COMMIT=93408ab GIT_STATUS=vendored-submodule)
target_compile_options(pls PRIVATE ${THIRD_PARTY_WARN_OFF})

# ---------------------------------------------------------------- KaMIS (submodule, MWIS on the complement graph)
# KaMIS refers to CMAKE_SOURCE_DIR internally, so it must be its own CMake project
# (ExternalProject), not add_subdirectory. Only the weighted (wmis) solvers are built.
include(ExternalProject)
set(KAMIS_DIR ${CMAKE_SOURCE_DIR}/third_party/KaMIS)
option(MWCP_WITH_KAMIS "Build the KaMIS weighted MIS solvers" ON)
# KaMIS compiles with -march=native when the compiler supports it. Binaries then only run on CPUs
# like the build machine's. MWCP_PORTABLE=ON pre-sets KaMIS's flag-check result to OFF.
option(MWCP_PORTABLE "Don't tune for the build machine's CPU (no -march=native)" OFF)
if(MWCP_WITH_KAMIS)
  if(NOT EXISTS ${KAMIS_DIR}/CMakeLists.txt)
    message(FATAL_ERROR "KaMIS submodule missing: run `git submodule update --init third_party/KaMIS`")
  endif()
  set(KAMIS_BUILD ${CMAKE_BINARY_DIR}/kamis)
  # Use real OpenMP if the compiler has it; otherwise put a serial omp.h stub on the include path.
  find_package(OpenMP COMPONENTS CXX QUIET)
  if(MWCP_PORTABLE)
    set(KAMIS_EXTRA_ARGS -DCOMPILER_SUPPORTS_MARCH_NATIVE=OFF)
  else()
    set(KAMIS_EXTRA_ARGS -UCOMPILER_SUPPORTS_MARCH_NATIVE)
  endif()
  if(NOT OpenMP_CXX_FOUND)
    message(STATUS "KaMIS: no OpenMP runtime found, building serially with cmake/omp_stub")
    # Passed as a standard include dir so CMake quotes it: the repo path may contain spaces.
    list(APPEND KAMIS_EXTRA_ARGS "-DCMAKE_CXX_STANDARD_INCLUDE_DIRECTORIES=${CMAKE_SOURCE_DIR}/cmake/omp_stub")
  endif()
  ExternalProject_Add(kamis
    SOURCE_DIR ${KAMIS_DIR}
    BINARY_DIR ${KAMIS_BUILD}
    CMAKE_ARGS -DCMAKE_BUILD_TYPE=Release
               -DCMAKE_C_COMPILER=${CMAKE_C_COMPILER}
               -DCMAKE_CXX_COMPILER=${CMAKE_CXX_COMPILER}
               -DCMAKE_POLICY_VERSION_MINIMUM=3.5
               ${KAMIS_EXTRA_ARGS}
    BUILD_COMMAND ${CMAKE_COMMAND} --build ${KAMIS_BUILD} --target branch_reduce weighted_ls -j
    INSTALL_COMMAND ${CMAKE_COMMAND} -E copy ${KAMIS_BUILD}/wmis/branch_reduce ${CMAKE_SOURCE_DIR}/bin/kamis_branch_reduce
            COMMAND ${CMAKE_COMMAND} -E copy ${KAMIS_BUILD}/wmis/weighted_ls ${CMAKE_SOURCE_DIR}/bin/kamis_weighted_ls
    BUILD_ALWAYS ON
    USES_TERMINAL_BUILD ON)
endif()
