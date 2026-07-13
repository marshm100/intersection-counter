# Plan — Stage 3.4: the operator surface (2026-07-13)

Follow-on to `plan_A4_stage3_2026-07-10` (stage 3.3 DONE — endpoints were the
dry-run surface; this stage makes the CARD the surface). MASTER_PLAN §4 item 6.
No accuracy mechanisms change here — frozen constants throughout; this is
plumbing + UI + the dry-run gate for flipping `TWO_PASS_ENABLED`.

## Ground rules inherited

- Corridor is FINAL at 4/5 applied on two-pass (§2d scoreboard); cam4 held on
  attribution research, not operator work. Nothing here re-litigates that.
- Standing rules §2d: drawn channels never in a fitted bank's attribution set;
  merge expecteds corpus-window scale-1; time-based constants (cams 10–25 fps).
- Existing corridor dumps are gated artifacts — the derivation must MATCH them,
  never invalidate them.

## 1. Trim→window derivation (the naming contract)

The dumps already follow a convention the code never wrote down:

- **variant** = `study_` + trim start `%H%M` (study_0700, study_1100, study_0000)
- **frames** = `round((trim_wallclock − recording_start) × fps)`, UNclamped
  (cam3 study_0000 starts at −20: 00:00:00 trim vs 00:00:02 recording start).

Verified against all five cams' dump metas (cam1/4/5 [251980,323980] @10fps,
cam2 [629950,809950] @25fps, cam3 [−20,863980]). `reprocess_camera.
_trim_frame_window` has the same math (but clamps); productize UNclamped into
`backend/services/two_pass.py:derive_windows(project_id, intersection_id)` →
per camera × trim: `{camera_id, trim_id, variant, start_frame, end_frame,
wallclock}`.

**Dump-satisfies-window rule:** same variant name AND dump frames ⊇ derived
frames minus slack (5 s each side) — coverage, not equality, because a trim
edit of a few seconds must not orphan a multi-hour dump, and clamped-vs-
unclamped starts differ by ≤ 2 s here. A dump at the right name that does NOT
cover the window = status `mismatch` (actionable: delete or re-dump; resume
already hard-errors on frame mismatch).

**Dump completeness:** run_pass1 gains a positive `"complete": true` marker
written into meta.json at finish (today nothing distinguishes done from
interrupted — count.txt updates during the run). Legacy dumps (no marker):
complete iff last dumped row is within 300 s of end_frame — covers all five
corridor dumps incl. cam3's empty-midnight 118 s tail gap.

## 2. Pass-2 reuse sidecar: calibration fingerprint (the known limitation)

`run_pass2` reuses `twopass_*.stats.json` on dump-meta equality ONLY — an
operator calibration edit (legs, bank, channels, calib knobs) does not
invalidate a stale working DB, so apply would ship pre-edit counts. Fix:

- `_calib_fingerprint(project_id, camera_id)` = sha256 over canonical JSON of
  (calibration params dict, legs rows, applied `intersection_paths` rows,
  `channels` rows) — everything pass 2 consumes from operator state
  (attribution = applied bank + legs + calib; corpus bank build = channels +
  legs; drawn channels feed BUILDS only, per standing rule 1).
- Sidecar stores it; reuse requires dump_meta match AND fingerprint match.
- Old sidecars lack the key → recompute once (minutes), then carry it.

## 3. Card UI — the two-pass "Confirm & process"

New GET `/projects/{pid}/intersections/{iid}/two-pass/plan` (404 when flag
off — the UI's feature probe): derived windows + per-window status
`{cache: ready|missing, dump: ready|partial|missing|mismatch, pass2:
current|stale|missing}` (pass2 currency via the §2 fingerprint).

`POST .../two-pass/process` body gains optional `windows` (absent → derive
from trims server-side). The job loop becomes: for each (camera, window):
ensure dump (**run pass 1 if missing — detect-at-ingest per §4 if the cache
is missing too**) → run_pass2(apply). Progress: v3_run_state (the chip
surface the UI already polls) + per-stage detail in the two-pass job dict
(`stage: pass1|pass2, camera, window, frames done/total`).

Frontend (`setup.js`, vanilla JS per constraints): `v3ConfirmProcess()` probes
the plan endpoint; on 404 → legacy flow unchanged (bit-for-bit when flag off).
When available: confirm popup lists per-camera windows + dump status +
what will run (pass 2 only vs pass 1 first), then posts process. The card
footer shows a compact two-pass readiness line per camera (dump/pass-2 state).
Intersection two-pass status feeds the Processing tab chip via the existing
v3_run_state fallback (no chip rewrite this stage).

## 4. Detection-at-ingest + dumper chunking (~90 s overlap)

For cache-less footage (a brand-new site), pass 1 must not error out — first
run = detect+cache+dump in ONE video decode; re-runs = pass 2 only (§2c).

- `run_pass1`: when the variant parquet is missing/doesn't cover the window,
  fall back to live detection: decode the window (cv2), detect with the
  project's processing-mode config (the corridor study parquets are exactly
  balanced/960/conf 0.1/skip 1), write-through a `DetectionCacheWriter`, feed
  the same NMS→buffer→tracker chain. Detector import stays lazy (test envs).
- **Chunking:** detection is hours-long on CPU, and a crashed ParquetWriter
  file (no footer) is unreadable — so the detect path writes closed per-chunk
  parts (`{variant}.part{k}.parquet`, ~15 min each), records a chunk
  high-water mark, and MERGES parts → `{variant}.parquet` + meta (with
  `windows`) at completion. Resume = re-run from the first incomplete chunk.
- **~90 s overlap:** every resume/chunk-boundary restart of the tracker today
  is a COLD seam — tracks alive at the seam are truncated (the §2c edge-padding
  problem, at seams). Fix in run_pass1 for both paths: on resume, warm the
  tracker over the preceding ~90 s of detections (rows discarded until the
  write boundary). 90 s is time-based (multiplied by fps per camera), covers a
  signal cycle + queue discharge. Track-ID reuse across the seam is already
  handled downstream by the finalize-gap split (same mechanism as tracker ID
  reuse generally). Existing complete dumps are untouched — the warm-up only
  changes what a FUTURE resumed/chunked dump contains.

## 5. Tests

- Derivation: corridor numbers as fixtures (cam1 @10fps → [251980,323980];
  cam2 @25fps → [629950,809950]; cam3 00:00 trim → −20; variant names).
- Sidecar: reuse honored on identical state; broken by a calib/bank/leg/channel
  edit; legacy sidecar (no fingerprint) → recompute.
- Completeness: marker respected; legacy heuristic at 300 s.
- Ingest: stub detector → cache parts merge + dump complete + pass-2 runnable;
  resume from a killed chunk re-enters at the right frame with warm-up.
- Endpoints: plan 404 when disabled; process with no `windows` derives from
  trims; foreign-camera guard preserved.

## 6. The operator dry-run (the stage gate)

`TWO_PASS_ENABLED=1`, Playwright, corridor project 97a7849a:

1. Card with trims already set (intersection 1: 07–09 + 16–18) shows readiness
   per window (study_0700 ready / study_1600 dump missing → the honest state).
2. **Intersection 2 (cam2) is the full-flow card:** add the three study trims
   in the UI (operator step), Confirm & process → three pass-2 runs + apply +
   flag rebuild, minutes each (sidecars will recompute once for the new
   fingerprint). Verify: flag queue populates (S5 rows present), QA acceptance
   gate reflects it, export gate state visible. Screenshots at each step to
   `screenshots/`.
3. Deliverable: go/no-go note on flipping `TWO_PASS_ENABLED` default ON.
   NO-GO criteria: any UI dead-end, any silent failure, apply without backup,
   or the dry-run producing numbers ≠ the §2d scoreboard's applied state
   (reuse/recompute must reproduce — same dump, same calibration, same code).

Out of scope: flipping the default in this session's code (the note decides);
C-stage review-UX polish; any accuracy tuning; S3; §3-D.
