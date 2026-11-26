"""bin/mwcp_exec: runs a program and reports that program's own peak RSS."""
import signal
import subprocess
import sys
import time

import pytest

from mwcp import BIN_DIR
from mwcp.solvers.base import read_peak_rss_mb

EXEC = BIN_DIR / "mwcp_exec"
pytestmark = pytest.mark.skipif(not EXEC.is_file(), reason="mwcp_exec not built")

# Touch every page so the allocation is resident, not just reserved.
ALLOC = "x = bytearray({mib} * 1024 * 1024)\nfor i in range(0, len(x), 4096): x[i] = 1\n"


def _run(tmp_path, *cmd):
    rep = tmp_path / "rss"
    p = subprocess.run([str(EXEC), str(rep), *cmd], capture_output=True, text=True)
    return p, read_peak_rss_mb(rep)


def test_reports_program_peak_not_parent(tmp_path):
    # Bloat this (parent) process first: a plain fork+exec child would inherit this in ru_maxrss.
    ballast = bytearray(300 * 1024 * 1024)
    ballast[::4096] = b"\x01" * len(ballast[::4096])
    p, small = _run(tmp_path, "true")
    assert p.returncode == 0 and small is not None and small < 50
    p, big = _run(tmp_path, sys.executable, "-c", ALLOC.format(mib=200))
    assert p.returncode == 0 and 200 <= big < 290
    del ballast


def test_passes_through_output_and_exit_code(tmp_path):
    p, mem = _run(tmp_path, sys.executable, "-c", "import sys; print('hi'); sys.exit(3)")
    assert p.returncode == 3 and p.stdout == "hi\n" and mem
    p, _ = _run(tmp_path, str(tmp_path / "no-such-binary"))
    assert p.returncode == 127 and "cannot run" in p.stderr


def test_sigterm_kills_program_and_still_reports(tmp_path):
    rep = tmp_path / "rss"
    proc = subprocess.Popen([str(EXEC), str(rep), sys.executable, "-c",
                             ALLOC.format(mib=64) + "import time\ntime.sleep(60)\n"],
                            start_new_session=True)
    deadline = time.monotonic() + 20
    time.sleep(1.0)
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=max(1, deadline - time.monotonic()))
    assert proc.returncode == -signal.SIGKILL             # the program's fate is passed on
    assert read_peak_rss_mb(rep) >= 64
