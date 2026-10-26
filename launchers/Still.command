#!/bin/sh
# Opens Still on macOS: double-click in Finder. Requires uv: https://docs.astral.sh/uv/
cd "$(dirname "$0")/.." && exec uv run --frozen python -m still "$@"
