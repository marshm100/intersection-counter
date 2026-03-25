"""Visual smoke test — screenshots every page via Playwright.

Usage:
    1. Start the server: py start_server.py
    2. Run this script:   py backend/tests/visual_smoke.py

Screenshots are saved to docs/screenshots/.
"""

import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:5000"
OUT_DIR = Path(__file__).resolve().parents[2] / "docs" / "screenshots"


def take(page, name: str, wait_ms: int = 800):
    """Wait briefly for rendering, then screenshot."""
    page.wait_for_timeout(wait_ms)
    path = OUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  -> {path.name}")


def run():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()

        # ---- 1. Load app ----
        print("Loading app...")
        page.goto(BASE_URL, wait_until="networkidle")
        take(page, "01_projects_page")

        # ---- 2. Check if any existing projects with data ----
        projects = page.evaluate("() => API.get('/api/projects')")
        existing_id = None
        for proj in projects:
            if proj.get("has_video") and proj.get("has_legs"):
                existing_id = proj["project_id"]
                break

        # ---- 3. Create a fresh test project ----
        print("Creating test project...")
        result = page.evaluate("() => API.post('/api/projects', {name: 'Visual Smoke Test'})")
        test_id = result["project_id"]

        # Reload project list
        page.evaluate("loadProjectList()")
        take(page, "02_projects_with_test")

        # ---- 4. Setup page (empty — no video) ----
        print("Setup page...")
        page.evaluate(f"() => {{ AppState.currentProject = '{test_id}'; showPage('page-setup'); loadSetupPage(); }}")
        take(page, "03_setup_no_video")

        # ---- 5. Calibration page (empty) ----
        print("Calibration page...")
        page.evaluate(f"() => {{ AppState.currentProject = '{test_id}'; showPage('page-calibration'); loadCalibrationPage(); }}")
        take(page, "04_calibration_empty")

        # ---- 6. Processing page (idle) ----
        print("Processing page...")
        page.evaluate(f"() => {{ AppState.currentProject = '{test_id}'; showPage('page-processing'); loadProcessingPage(); }}")
        take(page, "05_processing_idle")

        # ---- 7. Dashboard page (empty) ----
        print("Dashboard page...")
        page.evaluate(f"() => {{ AppState.currentProject = '{test_id}'; showPage('page-dashboard'); loadDashboardPage(); }}")
        take(page, "06_dashboard_empty")

        # ---- 8. Review page (empty) ----
        print("Review page...")
        page.evaluate(f"() => {{ AppState.currentProject = '{test_id}'; showPage('page-review'); loadReviewPage(); }}")
        take(page, "07_review_empty")

        # ---- 9. Export page (empty) ----
        print("Export page...")
        page.evaluate(f"() => {{ AppState.currentProject = '{test_id}'; showPage('page-export'); loadExportPage(); }}")
        take(page, "08_export_empty")

        # ---- 10. If existing project with data, screenshot those pages too ----
        if existing_id:
            print(f"Found existing project with data: {existing_id}")

            page.evaluate(f"() => {{ AppState.currentProject = '{existing_id}'; showPage('page-setup'); loadSetupPage(); }}")
            take(page, "09_setup_with_video")

            page.evaluate(f"() => {{ AppState.currentProject = '{existing_id}'; showPage('page-calibration'); loadCalibrationPage(); }}")
            take(page, "10_calibration_with_legs")

            page.evaluate(f"() => {{ AppState.currentProject = '{existing_id}'; showPage('page-processing'); loadProcessingPage(); }}")
            take(page, "11_processing_with_data", wait_ms=1500)

            page.evaluate(f"() => {{ AppState.currentProject = '{existing_id}'; showPage('page-dashboard'); loadDashboardPage(); }}")
            take(page, "12_dashboard_with_data")

            page.evaluate(f"() => {{ AppState.currentProject = '{existing_id}'; showPage('page-review'); loadReviewPage(); }}")
            take(page, "13_review_with_data")

            page.evaluate(f"() => {{ AppState.currentProject = '{existing_id}'; showPage('page-export'); loadExportPage(); }}")
            take(page, "14_export_with_data")
        else:
            print("No existing project with video+legs found. Skipping data screenshots.")

        # ---- Cleanup test project ----
        print("Cleaning up test project...")
        page.evaluate(f"() => API.del('/api/projects/{test_id}')")

        browser.close()
        print(f"\nDone! Screenshots saved to: {OUT_DIR}")


if __name__ == "__main__":
    run()
