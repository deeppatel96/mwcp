/*
 * mwcp_exec: run a solver and report its peak resident memory.
 *
 *   mwcp_exec <report-file> <program> [args...]
 *
 * Why a separate launcher: on Linux a child forked from the Python wrapper starts as a copy of
 * it, and exec() folds that copy's peak RSS into the new program's ru_maxrss. Every solver would
 * then report at least mwcp's own memory. This launcher is tiny, so forking the solver from here
 * keeps the solver's ru_maxrss its own.
 *
 * On exit it writes "maxrss_kib=<n>" to <report-file>, then exits with the solver's exit code or
 * re-raises the signal that killed it, so the caller sees the solver's status unchanged. SIGTERM
 * makes it SIGKILL the solver, reap it and still write the report (the wrapper's timeout path).
 */
#define _DEFAULT_SOURCE
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static volatile sig_atomic_t child = 0;
static volatile sig_atomic_t kill_requested = 0;

static void on_term(int sig) {
    (void)sig;
    kill_requested = 1;
    if (child > 0) kill((pid_t)child, SIGKILL);
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: mwcp_exec <report-file> <program> [args...]\n");
        return 125;
    }
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_term;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);

    pid_t pid = fork();
    if (pid < 0) {
        perror("mwcp_exec: fork");
        return 125;
    }
    if (pid == 0) {
        signal(SIGTERM, SIG_DFL);
        execvp(argv[2], argv + 2);
        fprintf(stderr, "mwcp_exec: cannot run %s: %s\n", argv[2], strerror(errno));
        _exit(127);
    }
    child = pid;
    if (kill_requested) kill(pid, SIGKILL);  /* SIGTERM arrived before child was set */

    int status = 0;
    struct rusage ru;
    memset(&ru, 0, sizeof ru);
    while (wait4(pid, &status, 0, &ru) < 0) {
        if (errno != EINTR) {
            perror("mwcp_exec: wait4");
            return 125;
        }
    }

    long kib = (long)ru.ru_maxrss;            /* KiB on Linux */
    FILE *f = fopen(argv[1], "w");
    if (f) {
        fprintf(f, "maxrss_kib=%ld\n", kib);
        fclose(f);
    }

    if (WIFSIGNALED(status)) {
        int sig = WTERMSIG(status);
        signal(sig, SIG_DFL);
        raise(sig);
        return 128 + sig;
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 125;
}
