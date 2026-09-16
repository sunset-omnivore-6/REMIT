"""Browser smoke test: launches the app in fixture mode and checks the hero.
Run: python -m pytest tests/e2e -q   (needs playwright + Chromium;
set PLAYWRIGHT_CHROMIUM to an executable path if not using playwright's own)."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
playwright = pytest.importorskip("playwright.sync_api")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    env = {**os.environ, "REMIT2_FIXTURE": str(ROOT / "data/samples/remit_sample.json")}
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true",
                             "--server.port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.5)
    yield f"http://127.0.0.1:{port}"
    proc.terminate()


def _launch(p):
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM")
    return p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()


def test_hero_renders(server, tmp_path):
    with playwright.sync_playwright() as p:
        b = _launch(p)
        page = b.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(server, wait_until="networkidle", timeout=120000)
        page.wait_for_selector(".js-plotly-plot", timeout=60000)
        page.wait_for_timeout(4000)
        assert page.locator(".js-plotly-plot").count() == 4
        assert page.get_by_text("Traceback").count() == 0
        assert page.get_by_text("Ad-hoc adjustments").count() >= 1
        assert page.get_by_text("available now").count() == 4          # four narratives
        page.screenshot(path=str(tmp_path / "desktop.png"), full_page=True)
        m = b.new_page(viewport={"width": 390, "height": 900})
        m.goto(server, wait_until="networkidle", timeout=120000)
        m.wait_for_selector(".js-plotly-plot", timeout=60000)
        assert m.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")   # no horizontal scroll
        w = b.new_page(viewport={"width": 1920, "height": 1080})
        w.goto(server + "/?mode=wall", wait_until="networkidle", timeout=120000)
        w.wait_for_selector(".js-plotly-plot", timeout=60000)
        assert w.get_by_text("Table view").count() == 0                 # wall mode hides tables/controls
        b.close()
