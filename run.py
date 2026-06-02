"""Entrypoint for the local REMIT app.

What this does:
  1. Starts uvicorn serving server.main:app on 127.0.0.1:8765
  2. Opens the default browser at the app URL (after a short delay so
     the server has time to bind the port).

Run with: python run.py
The REMIT.bat / desktop shortcut just calls this.
"""

from __future__ import annotations

import threading
import time
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}/"


def _open_browser_when_ready() -> None:
    # Small delay so uvicorn has bound the port before the browser hits it.
    time.sleep(1.2)
    try:
        webbrowser.open(URL)
    except Exception:
        # Browser launch failure is non-fatal — the URL is in the console.
        pass


def main() -> None:
    print(f"\n  REMIT — local dashboard")
    print(f"  Open: {URL}")
    print(f"  Stop: Ctrl+C in this window\n")

    threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    uvicorn.run(
        "server.main:app",
        host=HOST,
        port=PORT,
        log_level="info",
        access_log=False,  # quieter console
    )


if __name__ == "__main__":
    main()
