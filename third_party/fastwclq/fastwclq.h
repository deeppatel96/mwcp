#ifndef FASTWCLQ_H
#define FASTWCLQ_H

int fastwclq(int NB_Node, int NB_EDGE, double cutoff, int** AdjacentList, int* Node_Degree, int* Node_Weight, int* Node_Bound);

/* MWCP-WRAPPER: result accessors */
int fastwclq_clique_size();
int fastwclq_get_clique(int *out);
int fastwclq_proved_optimal();
/* MWCP-WRAPPER: cb(weight) on every improvement */
void fastwclq_set_improve_callback(void (*cb)(long));

#endif