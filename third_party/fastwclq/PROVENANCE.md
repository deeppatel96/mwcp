# FastWClq: provenance

- **Algorithm authors:** Shaowei Cai, Jinkun Lin
- **Paper:** Fast Solving Maximum Weight Clique Problem in Massive Graphs. IJCAI 2016 (journal version: Cai & Strash, JAIR 2021).
- **Source of these files:** https://github.com/yuansuny/mwc, commit `4f17b823b8016d51bd43981cd4b832eaac783078`, path `src/solvers/` (fastwclq.cpp, fastwclq.h).
  That repo (Sun, Li & Ernst, TPAMI 2019) wrapped the original solver as a library function.
  As far as we could find, there is no official public git repository for FastWClq.
- **License:** the upstream repo has no license file. The original authors keep their rights.
  Use for research only, and swap in the authors' original release if you get one.

## Local modifications
The first commit that adds this directory has the files unchanged from upstream.
Every later change is marked with `/* MWCP-WRAPPER */` comments and is visible in `git log -p -- third_party/fastwclq`.
