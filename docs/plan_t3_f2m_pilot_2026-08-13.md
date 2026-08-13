# Tier-3 pilot — FRAGMENT-TO-MOVEMENT classification (F2M)
# (2026-08-13)

Operator-approved at the Tier-1 checkpoint (2026-08-12 recommendation).
Literature basis: research_synthesis_queued_2026-08-12 F14/F15/F16 —
likelihood-map fragment classification cut TMC error 16%→4-5% ON
FRAGMENTS THAT NEVER CROSS BOTH GATES, and turn intent is classifiable
2 s ahead from kinematics. Campaign basis: the twin/dedup route to the
queue damage is measured DEAD (B1, five channels); the deficit cells
(cam2 EB_left −14/−79/−161, NB_left −63/−122/−47) are queue-shaped; A1
attacks the never-born half of the deficit, F2M attacks the born-but-
uncounted half. The two are complementary and independently gated.

## Prior art (found 2026-08-13, changes iteration 1's feature space)

`scripts/boxclip_pass2.py` already implements this pilot's core:
`discover_channels` (per-cell mean-polyline prototypes arc-resampled from
the window's OWN full journeys — built BECAUSE drawn centerlines "sit a
lane off... mis-attributed truncated SB-thrus as EB-rights", the recorded
lesson), `attribute` (fragment scorer: distance-to-prototype + angle
misalignment, modes entry/exit/free with gate-evidenence constraining
candidates, margin/ambiguity handling), `posterior_assign`
(lane-likelihood x add-one volume prior), and double-count guards with a
recorded burn ("first run counted them: 193/240 suspicious, EB_right
+316 — pure double-count"). Its module constants were LOST when the
gate machinery was hoisted into backend/services (uses ATTR_MAX_PX etc.,
defines none — currently NameErrors). The pilot reuses the SHAPE and
re-derives every constant self-calibrated, per this campaign's
discipline. The occupancy-map feature space moves to iteration 2.

## Mechanism (GT-free by construction — prime-directive compliant)

1. POPULATION: fragment = a dump track with >= 5 points whose
   vehicle_track_id has NO kept (rejected=0) event in the control DB,
   AND whose fragment CHAIN (build_chain_map_ev on the dump — existing
   machinery) contains no track with a kept event (a chained sibling of
   a counted track IS the counted vehicle — the first double-count
   guard, exact by construction). Census by classify tag reported.
2. PROTOTYPES from the window's OWN gate-verified FULL journeys: per
   (origin, dest) cell with >= 10 fulls, arc-length-resampled mean
   polylines (the discover_channels shape). No bank, no GT.
3. SCORING (the attribute shape): cost per candidate cell = mean over
   the fragment's scored points of distance-to-prototype-polyline +
   angle-misalignment x W_ang, where W_ang = zv_radius / 45deg (a
   heading error of 45deg costs one stopping radius — derived, not
   hand-picked). Gate evidence first: entry_only fragments score their
   LAST 60% of points against that origin's cells only; exit_only
   symmetric (first 60%, dest-constrained); no_crossing scores all
   points against all cells.
4. ASSIGNMENT FLOORS, self-calibrated blind per window: split-half
   validation on the fulls themselves (classify held-out fulls with
   known cells). ATTR_MAX (absolute fit ceiling) = p95 of held-out
   fulls' own best-cost; margin ratio floor = smallest top1/top2 ratio
   achieving >= 0.95 held-out precision. Below-floor fragments stay
   UNASSIGNED. No GT anywhere.
5. REMAINING DOUBLE-COUNT GUARDS (the boxclip burn, adapted):
   (a) same-cell entry-stub + exit-stub pairs within a calibrated gap
   (the window's own median full-transit time x 2) merge to ONE event;
   (b) a fragment whose time span sits within +-2 s of a kept control
   event in the SAME cell is skipped as suspicious (reported, not
   counted). Counts removed by each guard reported per window.
6. COMPOSITION (measurement only, zero backend changes): WAL-safe copy
   (sqlite3 backup — control DBs carry live -wal sidecars, verified) of
   the control DB → INSERT one synthetic event per assigned fragment
   with the NOT-NULL set (vehicle_track_id = fragment tid — the dump
   join is the point; posterior_source='f2m' is the discriminator and
   is deliberately NOT in _ADDITIVE; origin/destination_leg_id from the
   assigned cell; movement = derive_movement(legs[o], legs[d],
   all_legs) — the merge-rescue precedent; trajectory_data/confidence,
   vehicle_class from modal class_id, detection_confidence = mean conf;
   timestamp_video = frame/fps and timestamp_real = ISO(recording_start
   + timestamp_video) — the pipeline's exact formula, frame = classify
   origin_frame when present else median frame). Score the copy with
   stems `f2m_cam2_<window>` (parity copies named distinctly — the
   scorer overwrites by stem).

ACTIVATION NOTE: composition is POST-replay on the control DB — no
re-replay, so the activation state is the control's by construction. The
coupling law (activation-coupling-law) is not in play for this pilot.

CENSUS CAVEAT (recorded): vehicle_track_id is not unique in
vehicle_events (a reused dump id split by the 60-frame finalize gap
writes two events with the same id), so a dump track whose second half
was counted is excluded even where its first half is a genuine fragment
— conservative in the right direction; counted in the census.

## GATES — declared before any run; numbers final

Controls: committed score_d1ctrl_cam2_study_* = 53.4/42.9/44.0. Control
DBs: _replay_scratch/d1_conserve/ctrl/d1ctrl_cam2_*.db (extant).

- **G-F2M-p (parity precondition):** each control COPY scores
  cell-for-cell equal to its committed d1ctrl JSON before any insert.
  Mismatch → stop (stale copy / WAL trap).
- **G-F2M-k (kill gate — study_0700 ONLY, before 1100/1600 run):**
  (a) >= 20 fragments assigned (premise floor: thinner means the born-
  but-uncounted population cannot carry the deficit);
  (b) EB_left AND NB_left |err| both strictly reduced vs control;
  (c) phantom guard: added non-compliant phantom slots <= newly
  compliant slots. FAIL → pilot stops, ledgered, iteration 1 spent.
- **G-F2M-a (counting gate, all 3 cam2 windows):** 5/95 >= control on
  all 3 AND >= +1.0 on at least one; EB_left err strictly reduced on all
  3; NB_left reduced on >= 2 of 3; EB_right watch cell reported (any
  worsening called out); phantom guard per window.
- **Iteration budget 2 from zero.** Iteration 2 (only if G-F2M-k passes
  but G-F2M-a fails, and diagnostics implicate the feature space):
  ONE pre-named change — swap the polyline-distance feature space for a
  smoothed occupancy map over (grid 2x zv_radius, heading octant) built
  from the same fulls (the F16 KDE shape). Anything else is a new
  mechanism with its own plan.

## Deliverables

scripts/v2_f2m_pilot.py (population census, prototypes, floor
calibration report, assignment table by cell, composition, scoring);
runs/v2_week1/f2m_cam2_<window>.json diagnostics; score JSONs;
verdict in this doc. All committed either way.

---

## VERDICT (2026-08-13) — G-F2M-k FAILED on (b); pilot STOPS at one window

G-F2M-p PASS (parity copy cell-for-cell == committed d1ctrl). Pilot ran
clean on study_0700: census 1875 no_crossing / 1788 entry_only / 598
exit_only; 1422 fragments after the chain-sibling guard excluded 544;
floors self-calibrated (ATTR_MAX 65.7 px, margin 0.85, W_ang 0.29 px/deg,
held-out full precision 0.957 at coverage 0.784); guards removed 2
paired + 219 co-temporal; **202 events inserted**.

  gate read (study_0700)              control      f2m       verdict
  (a) assigned >= 20                     —         202        PASS
  (c) phantom guard                   103 cells  103 cells    PASS (zero
      newly compliant bins                +3                  added slots)
  (b) NB_left |err|                      63         28        reduced
  (b) EB_left |err|                      14         68        INCREASED →
                                                              **FAIL**
  5/95 (context, not the gate)         53.4       56.3 (+2.9)

The mechanism recovered real mass precisely where fragments live —
NB_left 348→383 (Mio 411), WB_left 25→51 (Mio 61), SB_right 214→248
(Mio 379) — with ZERO phantom-slot creation, the largest clean
single-window 5/95 gain the campaign has produced at cam2 (+2.9). AND it
mis-attributed ~68 fragments into EB_left (82 inserted into a cell
missing only 14): the entry-mode constraint TRUSTS the fragment's
gate-crossed origin, and cam2's EB origin crossings are the
already-on-record compromised signal (week-1 day-5 addendum: the
EB_right flood is mostly gate geometry / false EB origins). This is now
the THIRD independent mechanism to reproduce the false-EB-origin class
(gate-geometry analysis; the pair-off EB_right flood in E4's
supplementaries, ctrl 494 vs Mio 167; F2M fragment attribution).

Per the pre-declared consequence: **the pilot stops** — no 1100/1600
runs (the kill gate exists precisely so a precision failure cannot hide
inside those windows' larger deficits), iteration 1 spent. Iteration 2
(occupancy feature space) is NOT triggered — its precondition was
G-F2M-k passing, and the diagnosis implicates the ORIGIN TRUST, not the
feature space (held-out full precision was 0.957; the feature space
classifies well).

## LEDGER + named revival (for the operator, Tier-4 candidate)

**F2M-v2: origin-distrust variant** — same mechanism, but entry-mode
does NOT constrain candidates to the gate-crossed origin's cells at
cameras/origins where the strict-full census marks the origin
flip-prone (the `confusion` metric in strict_full_census — an existing,
blind, per-window signal built for exactly this). EB at cam2 measures
confused; the constraint would relax to free-mode there and the
prototypes would adjudicate the origin too. NEW mechanism variant =
its own plan + budget; NOT run today under this block's spent
iteration. The +2.9-with-zero-phantoms result and the 0.957 held-out
precision are the evidence it deserves the slot.
