# Hand-Drawn Channels as a Classifier Prior — Research Findings

**Date:** 2026-06-04
**Context:** cam5 (N Belt Line Rd & Barnes Bridge Rd), Sunnyvale TX, project `97a7849a`
**Status:** Concept validated at the cell level; marginal net win on a tuned window; clear path forward identified. Not yet shipped to the live pipeline.

---

## 1. The core idea

Let a traffic engineer **hand-draw a curved corridor ("channel") per movement** directly on a camera frame, and use each track's *fit* to those channels as a **supplementary classification signal** — not a replacement for the existing pipeline.

A channel is a **3-point curve**: entry → apex (the bend) → exit, with the centreline a quadratic that passes *through* the apex. Each end carries a **tripwire**, and the corridor **width is the tripwire length, tapering** from the inbound mouth to the outbound mouth.

Mental model the engineer settled on:
> "We have all these stored tracks — what are they, where did they come from, where are they going, and *how closely do they match the road paths the engineer drew?* That match helps us classify."

Key properties:
- **Lane-accurate:** endpoints sit on the correct (right-hand) lane, not on the coarse single-point leg origin. This is the signal, not an error to "snap away."
- **Perspective-aware:** the taper encodes foreshortening (wide near camera, narrow far). The human draws what they *see*, so lens/perspective distortion is captured by eye — no homography needed.
- **Complete:** draw every *physically legal* movement, regardless of whether it occurred in any sample (a movement with 0 volume today can happen tomorrow on a fresh video).
- **Supplementary:** assists the classifier where it's weak; never forces a wholesale relabel.

---

## 2. The tool

`experiments/channel_tool.html` — self-contained vanilla HTML/CSS/JS (no build step; cam5 frame embedded as a data-URI; opens from `file://`).

- **Draw:** New channel → click entry → apex → exit (3 clicks, auto-finishes). Endpoints snap to the nearest leg; origin/dest/movement auto-derive from geometry and **re-derive live** when you drag an endpoint.
- **Edit:** drag green entry / yellow apex / orange exit handles; width via the inbound/outbound sliders **or** by dragging the white tripwire-end handles. Corridor renders as a tapered filled band.
- **I/O:** Copy/Download/Load JSON. Schema: `{origin_leg, destination_leg, movement, entry:[x,y], apex:[x,y], exit:[x,y], width_in, width_out}`.

cam5 calibration baked in (legs table, project `97a7849a`):
`L36 W (176,192)` · `L37 S (140,350)` · `L38 E (482,351)` · `L39 N (477,191)`.

---

## 3. The full-intersection channel set (16 movements)

The engineer drew all 16 (4 approaches × through/right/left/u-turn). **Cross-checked against the cam5 Miovision OD (full-day volumes):**

- **15 of 16 are real movements**, all labelled geometrically correctly.
- Only **WB→WB u-turn has 0 volume** — but it was *kept* deliberately: zero-in-this-sample ≠ impossible, and gating the channel set by observed volume would overfit and fail on a fresh video.
- **The data-driven bank has only 9 paths; Miovision shows 15 exist.** The bank silently drops 6 real movements:
  - **NB→WB right (82/day)** — dropped despite *higher* volume than movements the bank kept ⇒ it's the nearest-anchor **mis-binning**, not a volume gate.
  - WB→NB left (65), EB→WB thru (45), and the three real u-turns (SB 22, EB 11, NB 4).
- The hand-drawn channels recover all 6 — quantified evidence that hand geometry captures movements the derivation structurally loses.

---

## 4. Separation analysis (perspective-corrected)

Measured how far apart movements sharing an approach are, in **lane-width units** (centre-line gap ÷ local corridor width — perspective-correct because both taper with depth). The decisive metric is the path fraction at which two corridors **stop physically overlapping**:

| Approach | Hardest pair | Clears from (path fraction) |
|---|---|---|
| EB | through / left (also through / u-turn) | ~40% (0.55 w/ u-turn) |
| SB | left / u-turn | 80% |
| WB | through / left | 75% |
| NB | left / u-turn | 75% |

- **Right and u-turn separate almost immediately (~10%); through-vs-left and anything-vs-u-turn are the hard pairs.**
- This maps directly onto the live scorer's `JOINT_SCORER_MIN_COVERAGE_FRAC = 0.28`: that's fine for the easy calls, but **through/left needs ≥~0.40 coverage** to be safe — a movement-pair-specific floor the channels reveal.
- Perspective corollary: a **constant** pixel tolerance (`JOINT_SCORER_MAX_COST_PX = 35`) is miscalibrated across the frame (≈2 lanes near the far exits, tight in the foreground). The tapered corridor supplies a **per-location, perspective-correct tolerance** — a real upgrade the channels enable.

---

## 5. The replay experiment (segregated)

**Location:** `experiments/channel_replay/` — fully isolated. Reads the source scratch DB + `project.db` **read-only**; writes only `cam5_channels.db` (a copy) + `results.json`. **Undo = delete the folder.** Nothing in `project.db`, the scratch DBs, or the live pipeline was touched.

**Data:** `cam5_bot_pm.db` (botsort retrack, PM 17:00–17:30, **1,559 tracks**). Metric: `scripts/od_accuracy.py --camera 5` (same net-error definition as the project's headline numbers), run on the copy.

### Results arc

| Config | Net error | Notes |
|---|---|---|
| **Baseline** (botsort + bank, stored) | **16.1%** | hybrid tracker was 9.7% — a different config |
| nearest-point matcher, all 16 | 26.4% | **u-turn magnet:** NB uturn 0→61 |
| nearest-point + exit-anchor gate | 23.3% | u-turn exits coincide with through exits |
| nearest-point, no u-turns | 17.3% | barely changes anything (14 reclass) |
| DTW (order-aware), all 16 | 21.5% | **fixed WB-right 67→14, NB-left** — but u-turns still magnet |
| DTW, no u-turns | 19.6% | fixes WB-right but **wholesale relabel breaks throughs** |
| **DTW + selective override** | **15.9% ✓** | **beats baseline, no regressions** |

### What worked

- **Order-aware matching extracts real signal.** Subsequence DTW (the partial-Fréchet analog), distances normalized to lane-widths, plus a tail-direction gate, **fixed the exact errors the channels were meant to fix**: `WB-right 67→14` (manual 7), `NB-left 98→45` (manual 54). Nearest-point could not.
- **Selective override is the right architecture.** Gate the override on **baseline confidence**: the phantom cells have low `trajectory_confidence` (WB-right 0.27, NB-left 0.24) while correct throughs are high (NB-thru 0.70, SB-thru 0.57). Overriding only when *(channel fit strong, cost ≤ 1.0)* **and** *(baseline weak, conf < 0.45)* produced **29 surgical overrides**, protected the confident throughs, and netted a small win with zero regressions. This is the "supplementary, to assist" model — not wholesale relabel.

### What didn't / caveats

- **The win is marginal (0.2 pt) and possibly within noise on one window.** Structural reason: this window has a **fully Miovision-tuned bank** already at 16.1% — the channels' *worst* showcase (a window dominated by ~1,300 throughs the bank nails; the channels' value is the ~200/day low-volume movements).
- **U-turns must be excluded or constrained.** Their wide, self-returning corridors magnet throughs/lefts via partial match; a hard gate (see §7, median) is needed before they can return.
- **The replay still fell back to the Miovision-built bank** for 527 unmatched tracks, so it did not fully isolate the no-ground-truth deployment scenario (see §8).

---

## 6. The Miovision dependency (the central finding)

**`build_bank.py` cannot build a bank without Miovision.** Confirmed in code:
```
build_bank.py:30   from parse_miovision_xml import parse, slot_labels
build_bank.py:142  cell_manual = cells_for_camera(...)        # Miovision volumes per cell
build_bank.py:185  for (ol,dl,mv), man in sorted(cell_manual.items()...):  # ITERATE Miovision cells
build_bank.py:186  if man < args.min_support: ...             # gate by Miovision volume
```
The bank is **built by iterating over Miovision's movement cells**; every gate (`min_support`, magnet `support > factor*manual`, recovery) is measured against Miovision volume. Strip the ground truth ⇒ `cell_manual` empty ⇒ **zero bank cells ⇒ no bank.**

**Consequences:**
- The "bank beats channels (16.1 vs 15.9)" comparison holds *only because we have cam5's Miovision.* That number is unavailable for a site not yet counted — the entire deployment case.
- For a new intersection there are three options: (a) buy Miovision too (defeats the purpose), (b) an **ungated** data-driven bank (reintroduces every magnet/phantom/mis-bin failure with nothing to catch them), or (c) **hand-drawn channels** (no ground truth needed).
- So the channels aren't a competitor to the Miovision-bank — **they are the Miovision *replacement* for the build step.** Miovision currently tells `build_bank` two things; the channels supply both: *which movements exist* (the engineer drew all legal ones) and *their geometry* (lane-accurate corridors). The volume-based magnet gate becomes unnecessary because curved corridors + order-aware matching reject magnets structurally.

**"Can we duplicate Miovision's method?"** — Yes in principle: Miovision has no ground truth above them either. Commercial video counting (GoodVision, shown by the engineer; Miovision works the same way) = **human "describe scene" (draw the movements) + automated tracking + human QA.** The channels *are* the describe-scene step. We can match the *method* without buying the *data*; the part that's genuinely hard to replace is the human-QA trustedness (see §8).

---

## 7. The median idea (U-turn / left disambiguation)

Draw each road's **median (centreline)**. This adds a **hard, topological constraint** that soft corridor-fit lacks ("which side did it end on / did it cross?"), targeting the U-turn/left hard pair:

- **U-turn (A→A):** crosses *its own road's* median and returns **parallel, opposite direction** → ends nearest the origin road's *opposing-lane* anchor.
- **Left/right (A→cross road):** ends **aligned with the cross road** → nearest a cross-road anchor.
- **Through:** stays aligned with its own road, doesn't reverse.

Two reasons it matters:
1. **It kills the u-turn magnet** — a through magneted by a wide u-turn corridor doesn't cross its own median and return to the origin-opposing anchor, so the hard gate rejects the u-turn label. **With a median drawn, u-turns can be safely re-included.**
2. **It rescues partial tracks** — one median crossing + an endpoint near an anchor classifies U-vs-left without needing 80% coverage.

Cost: ~2 median lines per 4-way, draw-once, Miovision-free. **Not yet implemented.** Next step: draw cam5's two road medians (or seed each ≈ the line through its two opposing leg origins), add a median-crossing + nearest-anchor gate on top of the matcher, re-include u-turns, re-run the selective-override A/B.

---

## 8. Problems that remain without a Miovision bank

Miovision's deepest role wasn't building the bank — it was the **error-detection and tuning oracle** for the whole pipeline. Without it, errors become **silent**. What the channels do *not* solve:

1. **Validation ("am I right?")** — no accuracy number, no A/B, no tuning signal, no confidence to report.
2. **Silent calibration errors** — a mislabelled leg (the cam1 180°-swap shipped wrong counts, caught only by Miovision), bad origin/median/channel → confident wrong output, no internal signal. The channels *are* the calibration now, so a bad drawing is a silent miscount.
3. **Per-camera tuning goes blind** — tracker choice, NMS for high-fps duplication (cam2/25fps), scorer thresholds were all Miovision-tuned.
4. **Tracking-quality problems invisible** — truncation undercounts, ID-switches, double-boxing (how we knew EB-right read 1-of-39, cam2 inflated throughs).
5. **Lost volume prior** — Miovision's distribution (SB-thru 6000 vs u-turn 4) silently resolves ambiguous tracks toward common movements; losing it is *part* of why u-turns magneted.
6. **No improvement loop** — after deployment, no signal to tell a good change from a bad one.

**Realistic substitutes (not zero human effort):**
- **In-house spot-counts** — engineer hand-tallies 1–2 sample windows of the same video. One local ground-truth covers most of the above (validate accuracy, catch calibration errors, pick tracker/NMS, expose gross tracking loss). Same human-verification Miovision uses, at sample scale.
- **Internal consistency checks (free):** flow conservation (vehicles in ≈ out), **cross-camera agreement** (a movement seen by two corridor cameras should match).
- **Auto-detectable:** duplication/high-fps from track-overlap stats; calibration sanity from the engineer eyeballing the drawn overlay.

**Bottom line:** the channels get us off *Miovision-per-study* but **not off human-in-the-loop validation entirely.** "Fully autonomous, no human, no ground truth, trust the counts" is the one promise geometry alone can't keep — and that's also how the commercial tools actually operate.

---

## 9. Open items / next steps

1. **Median gate** (§7) — draw cam5 medians, add median-crossing + nearest-anchor gate, re-include u-turns, re-run A/B.
2. **Decisive deployment test** — channels-only with the **bank removed** (fall back to the Miovision-free geometric classifier, not the bank). If that lands near 16.1% with *no* ground truth, self-sufficiency is shown.
3. **Lane-accurate redraws** — tighten over-wide corridors (esp. u-turns 313/256/246/216 px — these exit near-camera so some width is expected, but the u-turn is the dangerous one).
4. **Perspective-aware tolerance in the live scorer** — replace constant `JOINT_SCORER_MAX_COST_PX = 35` with a per-location lane-width tolerance derived from the corridors.
5. **Minimal validation layer** — define the spot-count workflow + free internal-consistency checks as the concrete oracle substitute.
6. **Per-camera generalization** — repeat the channel set + A/B on a camera/window with a *weak or absent* bank, where the channels should actually win.

---

## 10. Artifacts

- `experiments/channel_tool.html` — the drawing tool (self-contained).
- `experiments/channel_replay/channels_cam5.json` — the 16 hand-drawn channels.
- `experiments/channel_replay/replay_channels.py` — the segregated DTW + selective-override replay.
- `experiments/channel_replay/cam5_channels.db` — last working copy (safe to delete; ~72 MB).
- `experiments/channel_replay/results.json` — last run summary.
- `screenshots/channel_tool_*.png`, `channel_eb_fan.png`, `channel_user_ebsb.png` — tool/analysis captures.

> The channel concept is **validated at the cell level and architecturally sound** (order-aware match + confidence-gated selective override). Its decisive value is **deployability without per-site Miovision**, which the tuned-window A/B understates. The remaining hard problem is **validation without an oracle**, for which a lightweight in-house spot-count is the realistic substitute.
