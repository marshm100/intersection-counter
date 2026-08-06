# Plan — Pipeline V2 Week-1 derisk block (2026-08-03)

The §2e campaign's first block: prove global assembly beats the curated
state on the two dev cameras, with pre-declared gates, before ANY
product wiring. Plan doc before mechanism, constants ledger mandatory,
Miovision = dev scorer only (never runtime input).

## Scope & non-goals

IN: scripts-only prototypes over EXISTING pass-1 dumps; dev cams cam2
(hardest: occlusion splits + collinear pair) and cam1 (fragment-flood,
PM worst); the synthetic-fragmentation instrument; the assembly solver;
soft assignment of residual partials; dev scoring.
OUT (this block): product/UI wiring, any apply to project.db, schema-bug
fix (parallel product track), detection changes (Workstream B is gated
behind G-A3), cam3/4/5 (they enter at the G-A3 blind transfer).
All artifacts → `runs/v2_week1/` + scratch in `_replay_scratch/`.
Production DB opened READ-ONLY throughout.

## Inputs (verified on disk)

- Pass-1 dumps: `tracks_dir(parquet_path(...))/rows.npy` (+meta.json,
  count.txt), rows = [track_id, frame, x, y, ...]; reader precedent
  `backend/services/two_pass.py::_dump_tracks_pointlists`. Windows:
  cam2 study_0700/1100/1600 (25 fps, botsort recipe, dumps READY);
  cam1 study_0700/study_1600 (10 fps, botsort+reid, dumps READY —
  rebuilt in the 07-31 blind run).
- Leg gates / box sides: operator calibration in project.db (legs,
  intersection box) — the SAME geometry the live chain uses.
- Dev references (scoring only): Miovision per-minute XML via
  `scripts/parse_miovision_xml.py`; curated-table baselines from
  `runs/3b_validation/rule595_pre_blindrun_baseline.json`; wall
  signatures from `docs/phase0_wall_autopsies_2026-07-14.md`.

## Deliverables (scripts, all new, standalone)

D1. `scripts/v2_dump_graph.py` — dump reader → tracklet table
    (id, frames, centroids, endpoint kinematics, gate crossings,
    per-tracklet quality features). Plus `scripts/v2_frag_instrument.py`
    — THE no-GT progress meter: sample confident long tracklets (≥12 s,
    both-gate-crossing, top-quartile length×conf), synthetically cut
    into 2–4 fragments with gaps {0.5 s, 2 s, 10 s, 60 s-stopzone},
    score any stitcher on re-stitch RECALL (correct rejoins) and PURITY
    (no cross-vehicle welds) against co-temporal decoys. Output:
    `runs/v2_week1/frag_instrument_{cam}_{variant}.json`.
D2. `scripts/v2_baseline_greedy.py` — 50-line appearance-free greedy
    stitcher (nearest constant-velocity extrapolation within time/space
    gates) run through D1's instrument: the floor any solver must beat.
    OPTIONAL cross-check: gta-link (MIT) on cam1 only (the one camera
    with a ReID sidecar; appearance is far-band-invalid per the twin
    spike, so this is a sanity point, not a contender).
D3. `scripts/v2_assemble.py` — the MCF assembly (§2e S3+S4):
    - Stage 3: split on motion discontinuity (self-calibrated jerk
      threshold from the window's own confident tracklets); structural
      pre-merge of concurrent near-duplicates (co-life IoU-over-time).
    - Stage 4: node-split tracklet graph; evidence costs; entry/exit/
      stop-zone arcs (zones = image-border band ∪ KDE of long-track
      endpoints; stop zones = endpoint clusters with ~zero end speed);
      link cost = min(const-velocity Gaussian cone, zero-velocity
      hypothesis), α/β fit per window from intra-tracklet prediction
      residuals; heading-compatibility gate; T_max = 120 s.
    - Solver: OR-Tools SimpleMinCostFlow (new dev dep, Apache-2.0),
      costs ×10³ integerized, zero-cost S→T bypass.
D4. `scripts/v2_assign.py` — movement events from assembled chains:
    entry-side→exit-side for complete chains (v3 convention, verbatim);
    residual partials → KDE/completeness likelihood vs prototypes
    clustered from the window's OWN complete chains; low-margin →
    'ambiguous' bucket (future queue feed), never forced.
D5. `scripts/v2_score_dev.py` — per-window: (a) frag-instrument
    recall/purity; (b) per-cell per-15-min 5/95 vs Mio; (c) the wall
    signatures explicitly: cam2 EB-split overcount (+769-class), cam2
    NB-left recall (0.31 floor), cam1-PM SB-thru overcount (416 vs
    338-class); (d) event-count conservation (entries≈exits).
    Output: `runs/v2_week1/verdict_{cam}_{variant}.json` + the block
    verdict doc.

## Pre-declared gates (numeric, measured by D5)

- **G-A1 (cam2 study_0700, held-out 1100/1600):** EB split-flood
  OVERCOUNT halved vs the curated table's signature; NB-left recall does
  not drop; SB-thru/SB-right cells move toward Mio or hold within noise
  (±2 veh/bin); whole-camera 5/95 ≥ curated 46.7% basis on the same
  windows. Constants frozen after 0700 dev; 1100/1600 scored blind.
- **G-A2 (cam1 study_1600):** PM whole-window 5/95 within 2 pts of the
  AM window's score on the same run; SB-thru 17:45-class overcount bins
  brought inside ±5/95; AM window no-regression.
- **Instrument floor:** MCF ≥ greedy baseline on re-stitch recall at
  EVERY gap class, and purity ≥ 0.98 at all gap classes (over-merge
  tripwire) — fail purity ⇒ stop, diagnose, do not tune past it.
- Constants ledger: every constant in D3/D4 is either (a) derived from
  window statistics (named), or (b) listed in the verdict doc with its
  value and justification — any per-CAMERA constant = design failure,
  block fails its own discipline.

## Sequence & effort

Day 1: D1 (reader + instrument) + D2 (greedy floor).
Day 2–3: D3 solve on cam2 0700; iterate against the instrument + wall
signatures. Day 3–4: D4 assignment; G-A1 measurement incl. held-outs.
Day 5: cam1 0700/1600, G-A2; block verdict doc
`docs/plan_v2_week1_verdict.md` (PASS → G-A3 blind-transfer block;
FAIL → drawing board, said plainly).

## Risks on record

- Dump row schema drift between botsort/bytetrack recipes → D1 asserts
  schema from meta.json, fails loudly.
- Stop-zone false links (queue discipline) → purity tripwire + heading
  gate; if purity fails specifically at 60 s gaps, the zero-velocity
  hypothesis needs queue-order constraints (next block, not a hack now).
- cam2 25 fps volume (~180k frames/window) → graph gating keeps arcs
  ~10–30/tracklet; solver <1 min expected; if graph build exceeds ~30
  min, chunk to 15-min segments with overlap-stitch (I-24 precedent).
- Scoring leakage: Mio touched ONLY in D5; D1–D4 never read it —
  enforced by module separation (D5 is the only importer of the parser).
