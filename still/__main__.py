"""Open Still: start the local server and open it in the browser."""
from pathlib import Path
import argparse
import errno
import shutil
import subprocess
import sys
import webbrowser

from .server import App, create_server


def open_browser(url: str) -> None:
    # Under WSL, open the Windows browser rather than a Linux one that may not exist.
    try:
        wsl = "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        wsl = False
    if wsl and shutil.which("cmd.exe"):
        subprocess.Popen(["cmd.exe", "/c", "start", "", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(url)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="still", description=__doc__)
    parser.add_argument("--port", type=int, default=4173, help="Preferred port; another free one is used if it is busy.")
    parser.add_argument("--no-browser", action="store_true", help="Start without opening a browser window.")
    args = parser.parse_args(argv)
    app = App()
    try:
        server = create_server(args.port, app)
    except OSError as error:
        if error.errno != errno.EADDRINUSE:
            raise
        server = create_server(0, app)
    url = f"http://127.0.0.1:{server.server_port}/"
    app.sync.run_scheduler()
    print(f"Still is running at {url} (this computer only). Quit from Settings, or press Ctrl+C.", flush=True)
    if not args.no_browser:
        open_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.sync.stop()
        server.server_close()
        app.store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
