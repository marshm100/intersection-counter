"""Stage-4 Playwright smoke tour (plan_stage4_childtest_ux, GATE 4.4;
operator-directed 2026-07-29: UI verification by Playwright).

Drives the LIVE app (expects http://127.0.0.1:5000 already serving) over
the production corridor project — STRICTLY READ-ONLY: nothing is saved,
accepted, or applied. Tally counts are made and undone then CANCELLED;
the compass turns then cancels; the trims proposal is looked at, never
accepted (that click is the operator's).

Covers + screenshots (repo screenshots/ per CLAUDE.md):
  1 export traffic lights + child-language items   stage4_44_export_lights.png
  2 trims proposal (undeclared intersection 3)     stage4_43_trims_proposal.png
  3 footage-rating panel (the owed 3.2 shot)       stage3_32_footage_rating.png
  4 tally screen (+1 x2, undo, cancel)             stage4_41_tally.png
  5 worklist one-question card                     stage4_42_worklist_card.png
  6 compass wizard (turn, preview, cancel)         stage4_43_compass.png

Usage: py scripts/ui_tour_stage4.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5000"
PID = "97a7849a"
IID = 3                      # cam3's intersection: no trims, 3 legs, big queue
SHOTS = Path(__file__).resolve().parent.parent / "screenshots"

results: list[tuple[str, bool, str]] = []


def step(name):
    def deco(fn):
        def run(pg):
            try:
                fn(pg)
                results.append((name, True, ""))
                print(f"[TOUR] PASS  {name}", flush=True)
            except Exception as e:
                results.append((name, False, str(e)[:200]))
                print(f"[TOUR] FAIL  {name}: {str(e)[:200]}", flush=True)
        return run
    return deco


@step("open project")
def s_open(pg):
    pg.goto(BASE, wait_until="domcontentloaded")
    pg.wait_for_selector("#page-projects", timeout=15000)
    pg.wait_for_function("typeof openProject === 'function'")
    pg.evaluate(f"openProject('{PID}')")
    pg.wait_for_timeout(1500)


@step("export traffic lights (4.4)")
def s_export(pg):
    pg.evaluate("showPage('page-export'); loadExportPage()")
    pg.wait_for_selector(
        "text=What stands between you and export", timeout=30000)
    pg.wait_for_timeout(400)
    pg.screenshot(path=str(SHOTS / "stage4_44_export_lights.png"),
                  full_page=True)
    body = pg.inner_text("#page-export")
    assert "What stands between you and export" in body
    assert "Count a spot window" in body or "review cards" in body


@step("trims proposal (4.3) — NOT accepted")
def s_trims(pg):
    pg.evaluate("showPage('page-setup')")
    pg.evaluate(f"v3OpenIntersection({IID})")
    pg.wait_for_timeout(1200)
    pg.evaluate("v3SwitchDetailSubTab('trims')")
    pg.wait_for_selector("text=Accept all", timeout=15000)
    body = pg.inner_text("#v3-detail-subcontent")
    assert "07:00" in body and "09:00" in body        # the clipped AM peak
    pg.screenshot(path=str(SHOTS / "stage4_43_trims_proposal.png"),
                  full_page=True)


@step("footage-rating panel (3.2, owed shot)")
def s_rating(pg):
    pg.wait_for_selector("text=Footage rating", timeout=60000)
    body = pg.inner_text("#v3-footage-rating")
    assert "Camera" in body and ("Strong" in body or "Fair" in body
                                 or "provisional" in body)
    pg.screenshot(path=str(SHOTS / "stage3_32_footage_rating.png"),
                  full_page=True)


@step("tally screen (4.1) — count, undo, CANCEL")
def s_tally(pg):
    pg.evaluate("v3SwitchDetailSubTab('qa')")
    pg.wait_for_selector("text=Count a 30-min window", timeout=30000)
    pg.click("text=Count a 30-min window")
    pg.wait_for_selector("text=Count this window", timeout=20000)
    btn = pg.locator("button[id^='tally-']").first
    btn.click()
    btn.click()
    assert btn.locator(".tally-n").inner_text() == "2"
    pg.keyboard.press("z")
    pg.wait_for_timeout(200)
    assert btn.locator(".tally-n").inner_text() == "1"
    body = pg.inner_text("#v3-detail-subcontent")
    assert "Counted: 1" in body                     # the volume-only meter
    assert "system" not in body.lower()             # independence: no leak
    pg.screenshot(path=str(SHOTS / "stage4_41_tally.png"), full_page=True)
    pg.click("text=Cancel")                          # NO save
    pg.wait_for_timeout(400)


@step("worklist one-question card (4.2)")
def s_worklist(pg):
    pg.evaluate(f"openWorklist({IID})")
    pg.wait_for_selector("#page-worklist", timeout=15000)
    pg.wait_for_function(
        """() => {
            const t = document.getElementById('page-worklist').innerText;
            return t.includes('?') || t.includes('Queue clear');
        }""", timeout=45000)
    pg.wait_for_timeout(500)
    body = pg.inner_text("#page-worklist")
    questions = ["Is this a real vehicle?", "Which way did it go?",
                 "Are these separate vehicles?", "Did the system miss",
                 "Fragments or separate", "really this small"]
    assert any(q in body for q in questions), "no question headline found"
    assert "machine closed" in body                  # the visibility banner
    pg.screenshot(path=str(SHOTS / "stage4_42_worklist_card.png"),
                  full_page=True)


@step("compass wizard (4.3) — turn, preview, CANCEL")
def s_compass(pg):
    pg.evaluate("showPage('page-setup')")
    pg.evaluate(f"v3OpenIntersection({IID})")
    pg.wait_for_timeout(1200)
    pg.evaluate("v3SwitchDetailSubTab('cameras')")
    pg.wait_for_selector("text=Recalibrate", timeout=15000)
    pg.evaluate(f"v3CalibrateCamera({IID})")         # camera_id == iid here
    pg.wait_for_selector("text=Set all directions by compass", timeout=30000)
    pg.click("text=Set all directions by compass")
    pg.wait_for_selector("#v3-compass-slider", timeout=10000)
    pg.eval_on_selector(
        "#v3-compass-slider",
        "el => { el.value = 90; el.dispatchEvent(new Event('input')); }")
    try:
        pg.wait_for_function(
            """() => (document.getElementById('v3-compass-list') || {})
                     .innerText?.includes('corner')""", timeout=15000)
    except Exception:
        print("[TOUR][debug] wizard html:",
              pg.inner_html("#v3-compass-wizard")[:400], flush=True)
        raise
    body = pg.inner_text("#v3-compass-wizard")
    assert "-bound approach" in body                 # the verify labels
    pg.screenshot(path=str(SHOTS / "stage4_43_compass.png"), full_page=True)
    pg.evaluate("v3CompassClose()")                  # NO apply


def main() -> int:
    SHOTS.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 1280, "height": 900})
        pg.set_default_timeout(20000)
        pg.on("console", lambda m: m.type == "error" and
              print(f"[TOUR][console] {m.text[:200]}", flush=True))
        pg.on("pageerror", lambda e:
              print(f"[TOUR][pageerror] {str(e)[:200]}", flush=True))
        for fn in (s_open, s_export, s_trims, s_rating, s_tally,
                   s_worklist, s_compass):
            fn(pg)
        browser.close()
    ok = sum(1 for _n, p_, _e in results if p_)
    print(f"[TOUR] {ok}/{len(results)} steps passed", flush=True)
    print("UI TOUR DONE", flush=True)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
