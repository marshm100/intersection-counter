# New-Site Runbook — Counting an Intersection with Zero Ground Truth

The operating procedure that replaces Miovision. Produces TMC Excel output at the ≤5% net target
with a short, bounded human pass. Background: docs/architecture_research_2026-06-11.md (why this
recipe), docs/phase2_gtfree_findings_2026-06-11.md (bank bootstrap), docs/
phase3_conservation_qa_2026-06-12.md (QA checks), backend/services/spot_check.py (statistics).

## 0. Prerequisites

- Camera video on disk, named so the filename parser extracts camera/date/start time
  (`<cam>_<seq>_<YYYYMMDD>_<HHMMSS> <Intersection Name>.mp4`).
- The app: `py start_server.py` → http://127.0.0.1:5000.
- Footage that meets §0b below, if the deliverable claims the per-movement guarantee.

## 0b. Qualifying footage — the guarantee's precondition (Stage-6.1, 2026-07-29)

The 5/95 per-movement guarantee (per movement cell per 15-min bin: ref ≤100 → ±5 veh;
>100 → ≥95%) is conditional on footage quality — exactly as Miovision conditions their
guarantee on 5-star video. These are OUR measured requirements, not aspiration: each
traces to a wall we hit and could not engineer around on sub-spec footage. The app
computes a star rating per camera at ingest (intersection card → "Footage rating");
sub-spec footage caps at ★★★★ and the guarantee tier (★★★★★) is unreachable — the
rating is the automated check of this section.

**Hard requirements (the guarantee does not apply without all of these):**

1. **Resolution ≥1080p-class.** The measured wall, three independent mechanism
   families deep: far-field vehicle crops at 640×480 carry no identity signal (ReID
   twin spike AUC 0.399), concurrent occlusion twins have no image-space
   discriminator, and formation-limited movements (cam5-EB class) stay unresolvable.
   640×480 is what every legacy study in the corpus used; none of them qualifies.
2. **Daylight only.** Night / low-light / heavy glare bins are excluded from the
   guarantee (the industry's own exclusion). Watch for low-sun glare ON A SINGLE
   APPROACH — the FM51 PM miss (−12 to −20% for 90 minutes) was exactly this and is
   invisible in a quick footage glance; prefer study windows that keep the sun high
   or behind the camera.
3. **Vantage: high mount, whole intersection + approach entries in frame.** The
   intersection box AND each approach's entry visibly upstream of the movement
   divergence (at least a few car lengths before the stop bar). The corridor's
   oblique low mounts birth far-field tracks 6.7× deeper into the frame than they
   die — vehicles appear only mid-intersection, entries are never observed, and
   whole movement classes become structurally unattributable (cam5's 45% stub
   class). If an approach's entry is not in frame, its movements are not
   guaranteed.
4. **Minimize cross-traffic occlusion.** A view where a high-volume through stream
   passes between the camera and an opposing approach manufactures concurrent
   ID-splits (the cam2 EB double-count class — the one failure the blind censuses
   cannot see). Corner-mounted, elevated views beat edge-on views.
5. **Fixed camera, continuous coverage.** No pans/zooms mid-study; footage covers
   the declared trims plus ~2 min padding each side (the two-pass edge pad).
   ≥10 fps (the corpus baseline; the pipeline is validated at 10–25 fps).

**Procurement guidance (feeds [OP] 6.2 — the acceptance-test study):**
ask for 1080p or 4K fixed-mount recording, mounted high (light pole / mast arm
height, not tripod height), corner vantage covering all approaches' entries,
daylight study windows (avoid dawn/dusk peaks pointing into the sun), standard
TMC windows (AM + midday + PM peaks) with padding. Any modern traffic camera or
temporary pole unit meets this; the constraint is the mount, not the sensor.
After ingest, the star rating on the intersection card tells you within minutes
whether the footage supports the guarantee — check it BEFORE committing to the
full study processing.

## 1. Project + calibration (~30–45 min per camera, once per site)

1. Create the project, upload videos (Videos tab) — intersections build from labels.
2. Open each intersection → Cameras → **Calibrate**:
   - Place the leg origin nodes on each approach arm; set each leg's **cardinal direction** to the
     arm's **POSITION** (the corner it sits on). The dropdown's "— …bound" annotation is that
     approach's direction of *travel* — the opposite — and **that bound direction is what the TMC
     output reports** (a SE-corner leg is the **NW-bound "NWB" approach**). Diagonal positions
     (NE/SE/…) are fine for skewed sites. Left/right/through classification is convention-invariant,
     but the Excel/QA approach LABELS read the bound direction off the cardinal, so a wrong position
     mislabels the approach (the cam1 incident). The bank builder's QA cross-checks headings.
   - Adjust reference headings so the arrow points the direction that approach's traffic travels.
3. **Draw movement channels** ("Movement channels" section): one corridor per movement —
   entry → apex → exit, three clicks, endpoints snap to legs; set mouth widths to cover the lanes.
   - Draw the THROUGH corridors too, not just turns. If a leg's origin node sits on or near the
     path of through traffic (oblique views), channels are what prevents that flow from being
     mis-attributed (the cam1/cam5 failure mode).
   - Movement labels auto-derive from cardinals; override only if genuinely atypical geometry.

## 2. Bootstrap the path bank from the site's own traffic (~1 h machine time)

1. Process a 30–60 min window (Confirm & process), ideally with visible traffic on every movement
   you care about. This populates the detection cache (parquet) + events directly from the app.
   **Use Balanced mode** so the cache variant (`balanced_960_skip1`) matches what the bank builder
   reads by default; in another mode, pass `build_bank_gtfree --variant <mode>_<imgsz>_skip<skip>`
   (e.g. `accurate_1280_skip1`).
2. Build the GT-free bank:
   `py scripts/build_bank_gtfree.py --project <id> --camera <N> --minutes 30`
   - `--project` is the id in the project's URL. It **defaults to the Sunnyvale corridor**
     (`97a7849a`) — for any other site you MUST pass it, or you'll build against corridor data.
   - The window start (`--start-hms`/`--minutes`) is anchored to the video's own
     `recording_start_datetime` from the DB, so any date works.
   - Channels load from the DB automatically.
   - The builder refuses to run (clear message, exit 2) if the detection cache for the window
     doesn't exist yet — finish step 1 first.
3. **Read the QA report** (`evaluations/gtfree_bank_cam<N>_qa.json` + console):
   - `leg_sanity` SUSPECT → fix that leg's heading/cardinal in the UI, rebuild.
   - huge straight "turn" cell / `dedup_dropped` → anchor-on-through-path; check the through
     channels cover those corridors, rebuild.
   - `channel_fallback` rows are fine — those movements use your hand-drawn geometry until real
     trajectories accumulate.
4. Apply: `py scripts/apply_bank.py --project <id> --camera <N> --bank evaluations/gtfree_bank_cam<N>.json --apply`
   (backs up project.db first; `--project` defaults to the corridor, same as the builder).

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

## Blind acceptance — what certification means (§3-B validation 2026-07-28)

The acceptance gate was validated against ground truth on six cameras
(plan_3b_validation_2026-07-28.md). What it certifies, and what it does not:

1. **Count-until-certified, every segment.** The gate proposes one spot
   window per reporting segment (your declared trims). Count each; when
   the tool says "extend the count to ~N vehicles", keep counting — a
   30-minute window at moderate volume usually cannot certify alone.
2. **A "pass" certifies the NET TOTAL (±5%) of your declared reporting
   windows.** Nothing more. Footage outside your trims is uncertified —
   declare trims that match what the deliverable claims.
3. **Per-approach accuracy is surveilled, not certified.** The flag queue
   (coverage, bank-hole, merge feeders) plus the spot report's
   per-approach rows are tripwires: any approach row flagged "outside
   target" or any unresolved queue card on a high-volume movement means
   REVIEW that movement before export. No feasible manual count can
   certify per-approach accuracy blind — treat the queue as the
   per-approach authority.
4. **"Review" is an obligation, not a soft pass.** The gate never
   certifies by vagueness: wide CIs, uncovered segments, or a binding
   approach row all hold the verdict at review until resolved — by more
   counting, by trim scoping, or by working the queue.
