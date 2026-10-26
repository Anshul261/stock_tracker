"""Run Still: python serve.py (same as python -m still). Local access only."""
import sys

from still.__main__ import main
from still.server import App, create_server  # noqa: F401  Kept for callers that import from serve.

if __name__ == "__main__":
    sys.exit(main())
