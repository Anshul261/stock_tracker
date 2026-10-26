@echo off
rem Opens Still when the project lives inside WSL (for example \\wsl.localhost\Ubuntu\...).
rem Double-click it, or copy a shortcut to your desktop. Requires uv inside WSL.
wsl.exe --cd "%~dp0.." -e bash -lc "uv run --frozen python -m still %*"
