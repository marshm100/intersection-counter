# New-Site Runbook — Counting an Intersection with Zero Ground Truth

The operating procedure that replaces Miovision. Produces TMC Excel output at the ≤5% net target
with a short, bounded human pass. Background: docs/architecture_research_2026-06-11.md (why this
recipe), docs/phase2_gtfree_findings_2026-06-11.md (bank bootstrap), docs/
phase3_conservation_qa_2026-06-12.md (QA checks), backend/services/spot_check.py (statistics).

## 0. Prerequisites

- Camera video on disk, named so the filename parser extracts camera/date/start time
  (`<cam>_<seq>_<YYYYMMDD>_<HHMMSS> <Intersection Name>.mp4`).
- The app: `py start_server.py` → http://127.0.0.1:5000.

## 1. Project + calibration (~30–45 min per camera, once per site)

1. Create the project, upload videos (Videos tab) — intersections build from labels.
2. Open each intersection → Cameras → **Calibrate**:
   - Place the leg origin nodes on each approach arm; set each leg's **cardinal direction**
     correctly (N = the northbound approach). Cardinals drive movement naming, the Excel join,
     the QA checks, AND the bank builder — a swapped cardinal poisons everything downstream
     (the cam1 incident). The bank builder's QA report cross-checks headings automatically.
   - Adjust reference headings so the arrow points the direction that approach's traffic travels.
3. **Draw movement channels** ("Movement channels" section): one corridor per movement —
   entry → apex → exit, three clicks, endpoints snap to legs; set mouth widths to cover the lanes.
   - Draw the THROUGH corridors too, not just turns. If a leg's origin node sits on or near the
     path of through traffic (oblique views), channels are what prevents that flow from being
     mis-attributed (the cam1/cam5 failure mode).
   - Movement labels auto-derive from cardinals; override only if genuinely atypical geometry.

## 2. Bootstrap the path bank from the site's own traffic (~1 h machine time)

1. Process a 30–60 min window (Confirm & process), ideally with visible traffic on every movement
   you care about. This populates the detection cache + events.
2. Build the GT-free bank:
   `py scripts/build_bank_gtfree.py --camera <N> --minutes 30`
   (channels load from the DB automatically).
3. **Read the QA report** (`evaluations/gtfree_bank_cam<N>_qa.json` + console):
   - `leg_sanity` SUSPECT → fix that leg's heading/cardinal in the UI, rebuild.
   - huge straight "turn" cell / `dedup_dropped` → anchor-on-through-path; check the through
     channels cover those corridors, rebuild.
   - `channel_fallback` rows are fine — those movements use your hand-drawn geometry until real
     trajectories accumulate.
4. Apply: `py scripts/apply_bank.py --camera <N> --bank evaluations/gtfree_bank_cam<N>.json --apply`
   (backs up project.db first).

## 3. Process the full day

Confirm & process the full window (overnight on the target laptop; Balanced mode). Per-camera
tracker knobs (buffered-IoU, birth thresholds — Phase 1) only where diagnosis indicates; defaults
are correct for most cameras.

## 4. QA gate (intersection → QA tab)

The banner is the acceptance gate:
- **Corridor flow conservation** (multi-intersection projects): the primary check — gaps >15%
  implicate counting at one end of the link, and the direction tells you which approach to review.
- **Reverse-movement balance**: informational under 6 h; over a full day, flags are review
  prompts (one-way demand is real — confirm before treating as error).
- **Manual spot count**: propose a window, hand-count it from the raw video, enter the grid.
  - The math: certifying a ±10% CI at 95% needs ~**850 total vehicles** in the window — about
    20–40 minutes at a busy site. Shorter accurate counts report "review" with how much more to
    count. (Conservative independent-Poisson model; see spot_check.py.)
  - PASS requires point error within ±5% AND the CI inside ±10%.

## 5. Targeted review (the "brief human pass")

For every WARN/FAIL: open the Review screen filtered to the implicated approach + movement, fix
mis-attributed events / add missed vehicles (Phase 9 tooling), re-run the QA tab. Iterate until
the banner is READY TO EXPORT. Budget expectation from the corridor: minutes per flagged cell,
not hours per day.

## 6. Export

Excel TMC from the export page (hard-coded integers, cross-camera dedup applied).

## Known limits (honest list)

- ≤5% per-movement fully automated exceeds published SOTA — the spot count + targeted review IS
  the industry-standard recipe (Miovision's own accuracy includes human QA).
- Reverse balance cannot catch correlated errors (both directions wrong together) and false-flags
  genuinely asymmetric demand; corridor consistency carries the verdicts.
- A single-intersection project has no corridor check — the spot count carries the gate alone;
  prefer a longer count window there (aim ≥850 vehicles).
- Spot counts validate NET error per cell. Compensating within-cell errors (miss one vehicle,
  phantom another) needs per-event review to surface.
