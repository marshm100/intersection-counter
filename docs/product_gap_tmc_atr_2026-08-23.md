# Product gap analysis — replacing Miovision TMC + ATR (2026-08-23)

Mission: run TMC and ATR studies for free on our own devices, replacing
Miovision. Written against base-20260823 (commit 73a28a5, suite 1,019 green,
controls byte-identical on this machine).

## Verdict in three lines

- **TMC engine: complete end to end.** Detection (3 modes incl. site-tuned
  ft2, FM51-validated 3.0% interval MAE) → tracking → turn classification →
  cross-camera dedup → Excel TMC + Miovision-style PDF with peak-hour/PHF.
  The machinery is not the gap.
- **TMC accuracy is the gap:** movement 65.6 / approach 43.4 vs ±5%-in-95%-
  of-bins. Research verdict (roadmap §7d): nobody holds that bar pure-ML on
  sub-1080p; Miovision's unreviewed sensors measured 26–42% RMSE. The product
  is ML + measured review + certification, not a perfect model.
- **ATR does not exist** — but it skips turn attribution entirely (where all
  the error mass lives) and B1's drawn gate line IS the ATR screenline
  primitive. Cheapest new product on the board.

## TMC gaps, ranked

1. **Approach volume** (missing vehicles, not missorted) — volume ladder:
   E1 embedding dedup → QD discharge counting → K1 GLS balancing. Portfolio:
   mid ~57 pure-ML; **~70–85 with a measured review pass**.
2. **Movement** — the in-flight gate thread (B1 draw → pathfit → regate) + C0
   label fix. Best-ever 87.5 on clean geometry (FM51 held-out).
3. **R0 never run** — one reviewed window, scored both bars before/after.
   1–2 operator-hours, zero code, decides whether the sellable product exists
   NOW at a known review-hours price.
4. **CERT** — importance-sampled certification: "±5%/95% certified per study,
   0.5–1.5 review-h/day, auditable." No incumbent publishes the math.
5. **Peds/bikes** — dropped in v2, required for agency deliverable parity.
   YOLO already detects both; needs zones + counting + export + review. Weeks.
6. Ops (real but not blocking): per-machine venv+CUDA setup ~10 min; new-site
   fine-tune/labeling loop (labeler + finetune pipeline in-repo); capture
   hardware is outside the code and sub-1080p optics own the last points.

Corpus constraints: the five corridor videos stayed on the company OneDrive —
A2/A4 re-detection levers are dead on this corpus unless retrieved from the
boss's copy. ~37 diagnostic scripts still hash the video file and will crash
until swept (production replay chain fixed 2026-08-23).

## ATR: what it takes

| Ingredient | Have it? |
|---|---|
| Detect→track chain | yes (Balanced mode volume accuracy already ATR-grade) |
| Screenline w/ directional crossing | **yes — B1 gate_segment, verbatim** |
| Binning + Excel/PDF machinery | yes (new sheet layouts only) |
| Midblock study type (model + UI) | no — the actual build |
| Multi-day runs | untested (clips + checkpoints exist; storage fine) |
| Speed percentiles | no — needs ground-plane scale calibration; phase 2 |
| Axle counts | never (video = length classes; disclose in report) |

MVP = midblock project type + one drawn screenline + directional hourly/15-min
export. Weeks of reuse-heavy work, independent of the accuracy campaign.

## Quickest path

1. **Gate thread** (days, in flight): draw cam2 gates → pathfit → combined-
   basis regate, fresh controls. + C0.
2. **R0** (1–2 operator-hours): THE decider. If ML+review clears the bar on a
   window, the TMC replacement exists that day; everything after is cost
   reduction.
3. **ATR MVP** (weeks, parallel): second billable study type, immune to the
   turn-attribution problem.
4. **Volume ladder → CERT** (weeks–months): shrink review hours, then make
   the claim auditable. The certification story is the differentiator.
5. **Peds/bikes** (weeks): last; nothing upstream depends on it.

License note: ultralytics is AGPL-3.0 — fine for producing studies in-house;
revisit only if the software itself is ever distributed or sold.

Shareable version of this analysis (same content, formatted):
https://claude.ai/code/artifact/8594047f-9ba6-4dd6-bca6-e725fba07a1a
