#!/bin/sh
# Opens Still on Linux: double-click in your file manager (allow it to run), or add it to your launcher.
cd "$(dirname "$0")/.." && exec uv run --frozen python -m still "$@"
