@echo off
rem Opens Still from a Windows copy of the project. Requires uv: https://docs.astral.sh/uv/
cd /d "%~dp0.."
uv run --frozen python -m still %*
