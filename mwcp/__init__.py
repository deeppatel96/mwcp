"""Wrapper that runs multiple Maximum Weight Clique solvers on a METIS graph."""
from pathlib import Path

__version__ = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = REPO_ROOT / "bin"
