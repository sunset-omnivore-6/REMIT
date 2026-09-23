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
    import tempfile
    local_dir = tempfile.mkdtemp(prefix="remit2_e2e_")
    env = {**os.environ, "REMIT2_FIXTURE": str(ROOT / "data/samples/remit_sample.json"),
           "REMIT2_STORE": "local", "REMIT2_LOCAL_DIR": local_dir, "REMIT2_ACTOR": "e2e@test"}
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
        assert page.get_by_text("Ad-hoc:").count() >= 1
        assert page.get_by_text("New ad-hoc").count() == 1
        assert page.get_by_text("available now").count() == 4          # four narratives
        page.screenshot(path=str(tmp_path / "desktop.png"), full_page=True)
        m = b.new_page(viewport={"width": 390, "height": 900})
        m.goto(server, wait_until="networkidle", timeout=120000)
        m.wait_for_selector(".js-plotly-plot", timeout=60000)
        assert m.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")   # no horizontal scroll
        w = b.new_page(viewport={"width": 1920, "height": 1080})
        w.goto(server + "/?mode=wall", wait_until="networkidle", timeout=120000)
        w.wait_for_selector(".js-plotly-plot", timeout=60000)
        assert w.get_by_text("New ad-hoc").count() == 0                 # wall mode hides controls
        b.close()


def test_adhoc_create_and_cancel(server):
    """Create 'Comp 2 + Comp 3 out' at Hornsea Injection through the dialog,
    check the strip/tile react, then cancel it from the register."""
    with playwright.sync_playwright() as p:
        b = _launch(p)
        pg = b.new_page(viewport={"width": 1400, "height": 1100})
        pg.goto(server, wait_until="networkidle", timeout=120000)
        pg.wait_for_selector(".js-plotly-plot", timeout=60000)
        pg.wait_for_timeout(3000)
        pg.get_by_role("button", name="New ad-hoc").click()
        dlg = pg.get_by_role("dialog")
        dlg.get_by_text("Comp 2 · 7.5 GWh/d", exact=True).click()
        dlg.get_by_text("Comp 3 · 7.5 GWh/d", exact=True).click()
        dlg.get_by_label("Notes (required)").fill("e2e: comps 2 and 3 out")
        pg.keyboard.press("Tab")
        pg.wait_for_timeout(1500)
        assert dlg.get_by_text("Effect on Hornsea injection").count() == 1       # preview before saving
        assert dlg.get_by_text("REMIT threshold").count() >= 1
        pg.screenshot(path="/tmp/claude-0/-home-user-REMIT/f30ea6ac-edc2-5863-aead-2e35f003bc8f/scratchpad/e2e_dialog.png")
        dlg.get_by_role("button", name="Save ad-hoc").click()
        pg.wait_for_timeout(6000)
        assert "1 active" in pg.locator("[class*='st-key-r2chip'] button").first.inner_text()
        assert pg.get_by_text("Ad-hoc saved").count() == 1
        card = pg.locator("[class*='st-key-card-atwick-injection'] .r2-kpi").inner_text()
        assert "Ad-hoc" in card                                            # ad-hoc now drives Hornsea Injection
        assert "15.0" in card
        row = pg.locator("[class*='st-key-rvrow-']").first               # register: actions on the row
        row.get_by_role("button", name="Cancel").click()
        dlg = pg.get_by_role("dialog")
        dlg.get_by_label("Reason (required)").fill("test entry")
        pg.keyboard.press("Tab")
        pg.wait_for_timeout(1000)
        dlg.get_by_role("button", name="Cancel this ad-hoc").click()
        pg.wait_for_timeout(6000)
        assert "0 active" in pg.locator("[class*='st-key-r2chip'] button").first.inner_text()
        assert "Ad-hoc" not in pg.locator("[class*='st-key-card-atwick-injection'] .r2-kpi").inner_text()
        assert pg.get_by_text("Traceback").count() == 0
        b.close()
