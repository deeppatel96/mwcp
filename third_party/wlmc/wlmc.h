#ifndef WLMC_H
#define WLMC_H



int wlmc(int NB_Node, int NB_EDGE, double cutoff, int** AdjacentList, int* Node_Degree, int* Node_Weight, int* Node_Bound);

/* MWCP-WRAPPER: result accessors */
int wlmc_clique_size(void);
int wlmc_get_clique(int *out);
int wlmc_timed_out(void);
int wlmc_max_nodes(void);
/* MWCP-WRAPPER: cb(weight) on every incumbent change */
void wlmc_set_improve_callback(void (*cb)(int));

#endif