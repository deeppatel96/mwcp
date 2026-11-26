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
