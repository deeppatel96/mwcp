/* Serial OpenMP stub for building KaMIS's weighted solvers without an OpenMP runtime
 * (Apple clang ships none). KaMIS's wmis code only #includes <omp.h> and calls no omp_*
 * functions; the pragmas are ignored without -fopenmp. Its own no-OpenMP fallback points at a
 * misc/ directory that has no omp.h. These inline fallbacks are here just in case. */
#ifndef MWCP_OMP_STUB_H
#define MWCP_OMP_STUB_H
#ifdef __cplusplus
extern "C" {
#endif
static inline int omp_get_thread_num(void) { return 0; }
static inline int omp_get_num_threads(void) { return 1; }
static inline int omp_get_max_threads(void) { return 1; }
static inline void omp_set_num_threads(int n) { (void)n; }
#ifdef __cplusplus
}
#endif
#endif
