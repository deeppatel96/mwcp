"""Wrapper that runs multiple Maximum Weight Clique solvers on a METIS graph."""
import os
from pathlib import Path

__version__ = "0.2.0"

REPO_ROOT = Path(__file__).resolve().parent.parent
# Solver binaries; MWCP_BIN_DIR overrides (e.g. for a non-editable install).
BIN_DIR = Path(os.environ.get("MWCP_BIN_DIR", REPO_ROOT / "bin"))
