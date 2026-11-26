# WLMC: provenance

- **Algorithm authors:** Hua Jiang, Chu-Min Li, Felip Manyà
- **Paper:** An Exact Algorithm for the Maximum Weight Clique Problem in Large Graphs. AAAI 2017.
- **Source of these files:** https://github.com/yuansuny/mwc, commit `4f17b823b8016d51bd43981cd4b832eaac783078`, path `src/solvers/` (wlmc.c, wlmc.h).
  That repo (Sun, Li & Ernst, TPAMI 2019) wrapped the original solver as a library function.
  As far as we could find, there is no official public git repository for WLMC.
- **License:** the upstream repo has no license file. The original authors keep their rights.
  Use for research only, and swap in the authors' original release if you get one.

## Local modifications
The first commit that adds this directory has the files unchanged from upstream.
Every later change is marked with `/* MWCP-WRAPPER */` comments and is visible in `git log -p -- third_party/wlmc`.
