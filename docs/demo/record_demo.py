"""Record the <= 30 s demo video from the running app (same idea as SeaGuard: Playwright drives the real UI).

Start the app first:  ..\\.venv\\Scripts\\python -m streamlit run app/streamlit_app.py --server.port 3000
Then, from agrisim/:   ..\\.venv\\Scripts\\python docs/demo/record_demo.py
Output: agrisim_demo_30s.mp4 in the repo root (1920x1080, no sound; add a voice-over in a video editor if wanted).
Needs: pip install playwright imageio-ffmpeg; python -m playwright install chromium
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import Page, sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "agrisim_demo_30s.mp4"   # repo root, next to README.md
W, H = 1920, 1080
MAX_SECONDS = 30.0

CSS = """
#demo-cap{position:fixed;left:calc(50% + 150px);bottom:30px;transform:translateX(-50%);z-index:2147483646;
  max-width:1450px;background:rgba(20,40,24,.9);color:#fff;font:600 27px/1.3 'Segoe UI',Inter,sans-serif;
  padding:14px 26px;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.25);text-align:center}
#demo-cap small{display:block;font-weight:400;font-size:19px;opacity:.9;margin-top:4px}
#demo-card{position:fixed;inset:0;z-index:2147483647;background:#173a22;color:#fff;display:flex;flex-direction:column;
  align-items:center;justify-content:center;font-family:'Segoe UI',Inter,sans-serif;text-align:center}
#demo-card h1{font-size:84px;margin:0 0 18px}#demo-card p{font-size:34px;margin:6px 60px;opacity:.95}
#demo-card .s{font-size:24px;opacity:.8;margin-top:28px}
"""


def overlay(page: Page, caption: str | None = None, sub: str = "", card: str | None = None) -> None:
    page.evaluate("""([css, caption, sub, card]) => {
        if (!document.getElementById('demo-css')) { const s = document.createElement('style'); s.id = 'demo-css';
            s.textContent = css; document.head.appendChild(s); }
        for (const id of ['demo-cap', 'demo-card']) { const e = document.getElementById(id); if (e) e.remove(); }
        if (caption) { const d = document.createElement('div'); d.id = 'demo-cap';
            d.innerHTML = caption + (sub ? '<small>' + sub + '</small>' : ''); document.body.appendChild(d); }
        if (card) { const d = document.createElement('div'); d.id = 'demo-card'; d.innerHTML = card;
            document.body.appendChild(d); }
    }""", [CSS, caption, sub, card])


def idle(page: Page, timeout: float = 60) -> None:
    """Wait until Streamlit has finished the current run."""
    page.wait_for_timeout(400)
    end = time.time() + timeout
    while time.time() < end:
        if page.locator('[data-testid="stStatusWidget"]').count() == 0:
            return
        page.wait_for_timeout(200)


def sidebar_choice(page: Page, label: str) -> None:
    page.locator('[data-testid="stSidebar"]').get_by_text(label, exact=True).click()
    idle(page)


def pick_area(page: Page, label: str) -> None:
    page.locator('[data-testid="stSidebar"] [data-testid="stSelectbox"]').first.click()
    page.get_by_role("option", name=label).click()
    idle(page)


def tab(page: Page, name: str) -> None:
    page.get_by_role("tab", name=name).click()
    idle(page)


def show(page: Page, selector: str, margin: int = 60) -> None:
    """Scroll the first matching element of the open tab to the top of the view (the app scrolls in a div)."""
    page.evaluate("""([sel, margin]) => {
        const panel = [...document.querySelectorAll('[role="tabpanel"]')].find(p => !p.hidden && p.offsetParent);
        const el = (panel || document).querySelector(sel) || panel;
        if (!el) return;
        el.scrollIntoView({block: 'start'});
        let s = el.parentElement;
        while (s && !(s.scrollHeight > s.clientHeight && /(auto|scroll)/.test(getComputedStyle(s).overflowY)))
            s = s.parentElement;
        (s || window).scrollBy(0, -margin);
    }""", [selector, margin])
    page.wait_for_timeout(300)


def main() -> None:
    tmp = HERE / "_rec"
    shutil.rmtree(tmp, ignore_errors=True)
    marks = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(tmp),
                                  record_video_size={"width": W, "height": H})
        t0 = time.monotonic()
        page = ctx.new_page()
        page.goto(URL)
        page.get_by_text("Evia sowing decisions").wait_for(timeout=90_000)
        idle(page)
        # 0-4 s: title card over the real app
        marks["start"] = time.monotonic() - t0
        overlay(page, card="<h1>AgriSim AI</h1><p>Crop-rotation and sowing decisions from NASA Earth data</p>"
                           "<p>North Evia, Greece, after the 2021 wildfires</p>"
                           "<p class='s'>NASA Space Apps 2026 · Field Shift: Adapting Farms with NASA Data</p>")
        page.wait_for_timeout(3800)
        # 4-10 s: the Evia decision page
        overlay(page, "Weekly sowing check for each field, from NASA rain, soil moisture and temperature",
                "GPM IMERG · SMAP · POWER · 40 years of Landsat field history. It supports the farmer, never replaces them.")
        page.mouse.wheel(0, 250)
        page.wait_for_timeout(5600)
        # 10-16 s: Area explorer, Evia climate fit
        overlay(page, "Loading the Area explorer…")
        sidebar_choice(page, "Area explorer")
        tab(page, "Climate & crop fit")
        show(page, '[data-testid="stPlotlyChart"]', margin=170)   # the verdict box stays visible above the charts
        overlay(page, "Does an area fit the rules? Climate class from NASA POWER normals",
                "Evia: Csa, Mediterranean, the climate the rules were built for · crop suitability from FAO GAEZ v4")
        page.wait_for_timeout(5600)
        # 16-23 s: Messara, the field outlook map
        overlay(page, "Same pipeline, a second area…")
        pick_area(page, "Messara plain, Crete (second area)")
        tab(page, "Field outlook (ML)")
        show(page, '[data-testid="stDataFrame"]', margin=40)   # scores table, then the field map below it
        page.wait_for_timeout(2500)   # let the 70k-point map draw
        overlay(page, "Same pipeline, any area: 70,854 field pixels in Crete",
                "XGBoost trained on 30 years of Landsat: by 1 March it predicts crop vs fallow with AUC 0.87 on unseen seasons")
        page.wait_for_timeout(6200)
        # 23-27 s: data status
        tab(page, "Data status")
        show(page, '[data-testid="stMetric"]', margin=40)
        overlay(page, "Draw a box anywhere: the pipeline downloads everything and trains the models",
                "Landsat · HLS · IMERG Final + Late · POWER · NASADEM · SoilGrids · runs in the background, resumable")
        page.wait_for_timeout(4200)
        # 27-30 s: closing card
        overlay(page, card="<h1>AgriSim AI</h1><p>NASA data, turned into field decisions</p>"
                           "<p class='s'>Landsat · HLS · GPM IMERG · SMAP · POWER · NASADEM · MODIS</p>"
                           "<p class='s'>github.com/GeorgePanagiotou/agri_sim · Apache-2.0</p>")
        page.wait_for_timeout(3000)
        marks["end"] = time.monotonic() - t0
        video = Path(page.video.path())
        ctx.close()
        browser.close()
    # Loading waits sit between scenes; cut the lead-in, then speed up uniformly only if still > 30 s.
    length = marks["end"] - marks["start"]
    speed = max(1.0, length / (MAX_SECONDS - 0.2))
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-y", "-ss", f"{marks['start']:.2f}", "-i", str(video), "-t", f"{length:.2f}",
           "-vf", f"setpts=PTS/{speed:.4f},fps=30,format=yuv420p", "-an", "-c:v", "libx264", "-preset", "medium",
           "-crf", "22", "-movflags", "+faststart", str(OUT)]
    subprocess.run(cmd, check=True, capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"{OUT.name}: scenes {length:.1f} s, speed x{speed:.2f} -> {length / speed:.1f} s, "
          f"{OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
