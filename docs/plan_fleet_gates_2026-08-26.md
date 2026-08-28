# Fleet gate drawing — cams 3/4/5 measured (2026-08-26/27)

Operator drew gates on cams 3/4/5 (cam1 pending — no saved gates in
the DB at measurement time). C0 (skewed-T stem label fix, f3e4165)
landed first per the charter. Postgates snapshot:
backups/project_20260827T040144_postgates_fleet.db (the restore point
that PRESERVES drawn gates). Scratch arm: fresh workdir
fleetgates_20260826, 7 replays, stems fg_cam*_study_*.db, scores
runs/v2_week1/score_fg_*.json. Production untouched.

## Verdict table (movement bar / approach bar, arm vs shipped)

  window            arm              shipped         activation
  cam5 0700         66.4 / 50.0      66.4 / 50.0     0.342 OFF (was 0.330)
  cam5 1100         71.7 / 40.6      71.7 / 40.6     0.420 OFF (was 0.441)
  cam5 1600         63.1 / 21.9      63.1 / 21.9     0.413 OFF (was 0.402)
  cam4 0700         51.9 / 37.5      75.4 / 37.5     0.458 ON
  cam4 1100         59.6 / 66.7      73.5 / 41.7     0.540 ON
  cam4 1600         72.9 / 66.7      75.8 / 66.7     0.433 OFF
  cam3 0600 (14h)   62.5 / 14.9      72.6 / 28.0     0.547 ON
  cam1 0700         60.5 / 62.5      60.5 / 62.5     0.383 OFF (was 0.265)
  cam1 1600         52.5 / 21.9      54.5 / 40.6     0.466 ON  (was 0.438)

(cam1 measured 2026-08-27 after its late gate save — cardinals now
set S/N/W/E during the draw. Same law as the rest: 0700 channel off ->
byte-identical; 1600 channel ON -> movement -2.0, approach -18.7.)

## Reading

- cam5: drawn gates did NOT lift evidence coverage over the 0.45 bar
  (the plan's "within 0.01-0.05 of the bar" hope measured false at
  0700; 1100 even dipped). Channel stayed off -> scores byte-identical
  to production. Inert: no ship, no harm.
- cam4/cam3: gates DID flip the channel on (0700/1100 at cam4; the
  cam3 14h window) — and the movement bar got WORSE exactly where it
  flipped (-23.5, -13.9, -10.1). One bright spot: cam4 1100 approach
  +25.0 (41.7 -> 66.7). cam4 1600 (channel off) moved -2.9 on the
  C0-relabel + gate-geometry effects alone.
- [inference] The cam2 gates win does not transfer bare: cam2's
  activation flip landed on months of curated paths/banks; cams 3/4/5
  have none of that supporting calibration, and cam4 is a driveway T
  whose stub geometry may not suit exits[-1] supremacy semantics.
  Same shape as the identity-stack lesson: each camera's shipped
  basis is its own compensating equilibrium; flipping one honest
  channel on redistributes attribution without fixing what it leans
  on.

## Disposition

- NOT shipped (movement floor fails at cam4/cam3; cam5 inert).
  Negative ledgered here + roadmap changelog.
- Drawn gates STAY saved in the project DB (operator work product,
  preserved by the snapshot). DORMANCY CAVEAT: any future
  Confirm & process on cams 3/4/5 will inherit these gates and the
  activation flips — do not run a production apply on these cameras
  without deciding this ledger's question first.
- cam1: gates saved 2026-08-27 (cardinals set in the draw), measured,
  same negative law. The cam1 orphan-1100-events ruling (add trim vs
  retire the row) remains open.
- FLEET VERDICT COMPLETE: four cameras, one law — channel stays off:
  nothing changes; channel flips on: scores drop (cam4 -23.5/-13.9,
  cam3 -10.1, cam1 approach -18.7). Sole positive: cam4 1100 approach
  +25.0. Bare gates do not transfer the cam2 win; activation needs
  the curated substrate cam2 has (paths/banks) or it redistributes
  attribution onto nothing.
- C0 stands on its own merits (label truth; the Mio-zero phantom
  cell dies) independent of the gates decision.

## G-FP-1 — fleet pass under the shipped counted-path mechanisms
## (declared 2026-08-28, before any scored run)

Context: G-CP-1 shipped on cam2 (+5.8 pooled). The four mechanisms +
MQE are now config defaults; the fleet's dumps/caches exist. This
gate measures cams 1/3/4/5 under the shipped counting layer.

- ARM per camera: pass-2 replays of the existing study dumps with the
  shipped defaults (queue-aware merge, coexisting-twin dedup, flow
  origin inference, MQE; stop-fracture collapse NOT included — it
  lives at pass-1 and these dumps predate it; a dump-rebuild stage is
  a separate decision on this gate's evidence). The drawn gates saved
  2026-08-26 are in the DB and participate — the arm is
  GATES + MECHANISMS combined (the gates-alone negative stands
  separately; this measures the shipped composition).
- Windows: cam1 study_0700/1600 (1100 = the orphan, still open);
  cam3 study_0600 (14 h); cam4 + cam5 study_0700/1100/1600.
- CONTROLS: each camera's shipped standings (movement/approach):
  cam1 60.5/62.5, 54.5/40.6; cam3 72.6/28.0; cam4 75.4/37.5,
  73.5/41.7, 75.8/66.7; cam5 66.4/50.0, 71.7/40.6, 63.1/21.9.
- PASS, per camera: pooled movement above that camera's shipped
  pooled AND no window more than 2.0 below its control. Approach
  recorded (the earlier gates-alone negative collapsed approach —
  a repeat collapse is a per-camera veto even on a movement pass).
- Ship per camera, operator go, standard ladder. MISS per camera:
  ledgered; that camera keeps its shipped basis (the mechanisms
  remain dormant there until its own remedy — their next apply stays
  blocked per the standing caveat).
- Workdir fleetpass_20260828; stems fp_camN_study_W; armed-
  verification via the first window's stats sidecar showing
  twin_dedup/origin_flow_inferred counters.

## G-FP-1 VERDICT (2026-08-28)

  window        arm (mov/app)   shipped (mov/app)   per-camera verdict
  cam3 0600     83.7 / 61.9     72.6 / 28.0         **PASS** (+11.1 / +33.9)
  cam5 0700     72.9 / 46.9     66.4 / 50.0         movement pass (+1.9
  cam5 1100     70.8 / 31.2     71.7 / 40.6           pooled, floors held)
  cam5 1600     63.1 /  6.2     63.1 / 21.9           but approach COLLAPSE
                                                      at 1600 -> VETO
  cam1 0700     64.2 / 50.0     60.5 / 62.5         movement pass (+3.7,
  cam1 1600     60.2 / 15.6     54.5 / 40.6           +5.7) but approach
                                                      collapse -> VETO
  cam4 0700     53.8 / 41.7     75.4 / 37.5         movement MISS (the
  cam4 1100     57.7 / 66.7     73.5 / 41.7           gates-alone shape;
  cam4 1600     72.9 / 66.7     75.8 / 66.7           mechanisms did not
                                                      rescue activation)

- cam3 is the best score ever recorded in this project on both bars
  (movement 83.7; approach 61.9 nearly ties the fleet's best window).
  Both bars UP together — no veto. SHIP awaiting operator go.
- cam5/cam1: the mechanisms lift movement but the approach bar drops,
  hardest at the 1600 windows — the same directional signature as
  cam2's shipped arm (28.1 at 0700/1600). A cross-camera
  approach-bar diagnosis is now the chartered follow-up; neither
  camera ships on this arm.
- cam4: MISS — the driveway-T activation problem is untouched by the
  counting mechanisms; keeps its shipped basis.

## SHIPPED cam3 (2026-08-27/28)

Operator go. Pre-ship backup project_20260827T234931_pre_ship_cam3.db
(integrity ok, 96,919 events). First apply stood down
(no_headroom+no_recovery — the attribution-blind volume gate);
force_once set citing the G-FP-1 PASS + operator go; second run
applied TRUE (operator_force), disposition consumed back to auto.
Post-apply: PRODUCTION = ARM exactly (83.7 movement / 61.9 approach —
project-best both bars). Operator ruling recorded: the other cameras'
non-transfer is a LEDGER NOTE, not a deep-dive; the standing target
is the 5/95 Miovision standard, every camera.

## G-FP-2 — the full cam2 recipe on cams 1/4/5 (declared 2026-08-28)

The G-FP-1 dive found the fleet's counting fixes exposed real deficits
that duplicate inflation had hidden — the deficits the big detector
recovers — and the fleet never got cam2's detector half. Operator
rulings folded in: cam1's gates stay as drawn (T + commercial driveway
4th leg, deliberate); the driveway counts as a REAL leg (accuracy to
reality; a Miovision under-count there is a disclosure item, not our
defect); non-transfers are notes, the target is 5/95 everywhere.

- ARM per camera: fl_ detections (yolo26l@1280 conf 0.10, CUDA, the
  shipped counted_path recipe) -> pass-1 under the camera's calib
  tracker with the shipped defaults (stop-fracture collapse bakes in).
  DECLARED DEVIATION: cam1's calib says botsort+reid; the reid
  embedding sidecar doesn't exist for new detections, so the arm runs
  plain botsort there (a ship would set calib accordingly).
  -> pass-2 with the shipped defaults. Windows: cam1 0700/1600;
  cam4 + cam5 0700/1100/1600.
- CONTROLS: the shipped standings (cam1 60.5/54.5; cam4
  75.4/73.5/75.8; cam5 66.4/71.7/63.1 movement).
- PASS per camera: pooled movement above shipped pooled, no window
  more than 2.0 under its control, approach not collapsing (the
  standing veto). cam1's WB cell is EXPECTED to disagree with the
  reference per the driveway ruling — its readout is annotated, not
  vetoed on that cell alone.
- Ship per camera, operator go, standard ladder.

## G-FP-2 VERDICT + SHIPPED cam1-1600 (2026-08-28)

  window          arm             shipped         read
  cam1 1600       86.2 / 78.1     54.5 / 40.6     BEST WINDOW EVER — SHIPPED
  cam1 0700       63.0 / 31.2     60.5 / 62.5     morning approach broke
                                                  (real NB/SB volume loss
                                                  beyond the driveway cell;
                                                  suspected morning light) — note
  cam5 1100       78.3 / 34.4     71.7 / 40.6     movement +6.6, approach dip — note
  cam5 0700/1600  ~flat           —               note
  cam4 all        worse           —               MISS (not a detection
                                                  problem either) — note

PER-WINDOW SHIP AMENDMENT (operator go "go for it"): the declared
per-camera shape was amended to per-window on the evidence split;
applies are window-scoped by construction. cam1 study_1600 promoted
(pre_fl_* renames aside; corrected sidecar; dump backend botsort —
the declared reid deviation now the shipped basis for THIS window;
future pass-1 rebuilds of this window need calib awareness, ledgered).
Backup project_20260828T142159_pre_ship_cam1_1600.db. First apply
stood down (saturated_geometry+no_headroom); force_once with the
verdict citation; applied TRUE; disposition consumed. Post-apply:
PRODUCTION = ARM exactly: 86.2 / 78.1.

Corridor live standings (movement bar): cam1 60.5 / [1100 orphan] /
86.2; cam2 70.4/71.3/70.3; cam3 83.7; cam4 75.4/73.5/75.8 (old
basis); cam5 66.4/71.7/63.1 (old basis).

## cam5-1100 HELD (2026-08-28) — the gate did its job

Per-window ship attempted on the operator's push; the apply gate stood
down (no_headroom + event_flood) and the flood is REAL: NB_left arm
365 vs Mio 185 (+180, nearly doubled; production +29). Mechanism: the
known cam5 lane-echo class (mouths 160 px apart mint phantom NB
lefts); the old merge's bluntness was accidentally suppressing them,
and the queue-aware merge correctly protects coexisting events —
un-suppressing the phantoms. NOT forced; promotion rolled back
(originals restored, verified). Remedy = cam5 mouth/geometry work
(the calibration-wave item), not a counting-layer force. cam5 keeps
its shipped basis everywhere.
