# OPTIONS INVENTORY — uncharted territory + conclusions drawn too early
# (2026-08-11)

Built for an operator decision: what is actually still available, and which
"dead" conclusions do not deserve their headstones. Compiled from the repo's
own ledgers, not from memory. Nothing here is a recommendation to reopen
everything — several entries are genuinely dead and are listed as such so the
list can be trusted.

**The single most important structural fact in this inventory:** the project
runs a STANDING TWO-ITERATION BUDGET. Mechanisms are retired after two
attempts *whether or not the space is exhausted*, and every one is filed
"revival-ready, code+tests remain". That rule bought discipline and it is why
this codebase is not a graveyard of half-mechanisms — but it means a large
share of the ledger says "we stopped", not "it cannot work". Those are
categories C and D below and they are the richest ground on the list.

---

## A. UNCHARTED — never built, zero code

| # | item | research source | note |
|---|---|---|---|
| A1 | **Stage-1 tubelet stabilization** — detection-level linking, tubelet-average rescoring, gap interpolation | synthesis fact #3 (+6.5 mAP, +10.8 on the flicker split, 2.6 ms/frame CPU) | The only lever aimed at the TRACKER BIRTH GATE. 32% of cam2's cached detections sit in the band the tracker can see but cannot birth from; at cam4/cam5 that band is 0.10→0.35, i.e. most of the far field. Partial prior art survives in the retired `scripts/v2_tubelet.py:216-246`. |
| A2 | **Motion-mask fusion** | synthesis fact #3 | The ONLY detection-side lever not ledgered dead. Cost insight: background subtraction is DECODE-bound, not CNN-bound — ~realtime vs ~20 h for a YOLO re-detect, and it fuses against the EXISTING detection cache. Feasible on this hardware; previously assumed not. |
| A3 | **S3 split** — cut mixed-identity tracklets on motion discontinuity | stage 3 | Zero hits in the codebase. Only *pre-merge* was tried (and killed). The split half of split-then-merge has never been attempted. |
| A4 | **Scale-matched 1280 fine-tune** | synthesis fact #3 (+25% rel at tiny sizes) | ft2 was trained at 640 and runs at 640. "Scale-matched" means fine-tuning AT the inference size on upscaled frames — never done. Expensive (retrain), and `config.py:26-31` records 1280 *inference* as +6% uniform, not far-field. |
| A5 | **Far-ROI crops** | Workstream B | Zero code. |

## B. BUILT but never measured against a gate

| # | item | where | note |
|---|---|---|---|
| B1 | **Structural twin test** (best-successor / best-predecessor collision) | `scripts/v2_common.py:353`, exposed in `v2_reid_dump.py:81` where the comment literally reads *"the untried channel"* | The week-1 verdict named this **item 1** of what to do next. Never run. It is the one twin-class channel that is pure structure — no thresholds, no appearance, no geometry — after four pairwise channels died. |
| B2 | **Zero-velocity link hypothesis at DETECTION level** | exists only at TRACKLET level in `v2_common.py` (`v_stop`, `zv_radius`), and every consumer is a dev script feeding the FAILED G-A1 MCF | The I-24 blind spot the research names explicitly (switches 0.04→0.52 in congestion). Never applied at detection level, which is where A1 would use it. Today's evidence points straight at queues: `EB left` failed at every window on three cameras. |

## C. RETIRED BY THE TWO-ITERATION BUDGET — policy stop, not exhaustion

All flagged "revival-ready, code + tests remain". Each carries measured
evidence that the mechanism family is REAL.

| # | item | verdict text | what it actually established |
|---|---|---|---|
| C1 | **Conservation pass / posterior half** (`plan_conservation_pass_2026-07-15.md:86`) | "RETIRES as a blind five-camera default, per the two-iteration budget. Flags stay OFF." | *"The mechanism family is REAL: cam2 9.1→3.3–3.5% — the corridor's hardest camera passing the 5% bar. It is NOT blind-deployable where evidence coverage is low (36–60%)."* |
| C2 | **Origin-evidence gate + posterior as default** (`MASTER_PLAN:279, :737`) | "RETIRED as a default per the two-iteration budget; flags OFF" | Named future candidates recorded: **evidence-ranked chain arbitration (iteration 4, own plan+budget)** — never done; and the coverage-activation precondition — which DID ship. |
| C3 | **Origin claim-veto + rescue** (`plan_origin_veto_2026-07-17.md:317`) | "FAIL — RETIRED as a default per the two-iteration budget." | FM51-proven in BOTH phases; the corridor over-fires because the frozen `d_main<25` signature does not discriminate at far-field compression. Not "wrong" — mis-scaled. |
| C4 | **LEC2 / cam5 lane-echo bundle** (`plan_cam5_lane_echo_2026-07-27.md:354`) | "two-iteration budget CLOSES the cycle" | Bundle described as *"one honest band-miss from its own bar."* |
| C5 | **cam5 near-gap cycle** (`plan_cam5_neargap_2026-07-29.md`) | two-iteration budget, cam5-only scope | R_off strictly dominates the shipped bundle; nothing shipped per gates. |

### C-named revival candidates that were WRITTEN DOWN and never executed

1. **Evidence-ranked chain arbitration** (`MASTER_PLAN:738`) — iteration 4 of the posterior family, explicitly scoped as needing its own plan + budget.
2. **Origin-veto site-activation precondition** (`plan_origin_veto:356`) — use the veto RATE itself as a blind health check. Note the doc's own words: *"Same shape as the evidence gate's named coverage-precondition candidate."* That sibling shipped and works. This one never got built.
3. **Compression-relative constants** (`plan_origin_veto:361`) — "25 px is not the same road at different focal lengths; a road-width-normalized `d_main` needs a fresh phase-0 measurement pass, not a knob sweep." This is a general indictment of every frozen pixel constant in the chain, not just the veto's.
4. **Appearance-based twin detection on ReID embeddings** (`plan_cam5_lane_echo:372`) — embeddings already exist per-camera for `botsort+reid`; an embedding twin test is *image-space-compression-immune*, which is precisely why the four dead pairwise channels died.
5. **Per-window composition-adaptive rejection** (`plan_cam5_lane_echo:374`) — an activation-style scaler measurable blind from the census.

## D. THE RETIREMENT REASON HAS SINCE BEEN FIXED — and nobody re-tested

**This is the strongest category on the list.**

C1/C2 were retired for ONE stated reason: not blind-deployable where evidence
coverage is low. The **evidence-activation precondition** is exactly the
decider for that problem. It was built, validated, promoted on 2026-07-27,
and is DEFAULT ON today.

But `backend/config.py:427-429` says, verbatim, that the activation
precondition governs the REPLAY only — *"the run_pass2 posterior extras
`census_expecteds` / `conserve_pass` stay keyed on their own flags; phase 1
never measured them."*

So:
- `ORIGIN_POSTERIOR_ENABLED` is still default OFF (`config.py:419`);
- `conserve_pass` — the corridor's only structural defense against counting
  one fragmented vehicle twice — therefore **never runs** (confirmed: no
  `conservation` key in ANY arm A/B/C sidecar from Block 0);
- and the mechanism that would make it safe is shipped, on, and pointed
  somewhere else.

**D1. Run the conservation pass / census_expecteds under the activation
precondition.** Never measured. The retirement reason is gone.

**D2. Same shape, origin-veto:** its named revival candidate #1 is a
site-activation precondition; the evidence gate's version of that idea
shipped and works; the veto's was never built.

## E. CONCLUDED ON A CONFOUNDED OR TOO-BLUNT INSTRUMENT

| # | conclusion | why it is suspect |
|---|---|---|
| E1 | **The G-A3 "applicability law"** | PROVEN confounded 2026-08-11 — four variables moved at once. cam3's +8.5 turned out to be pair +11.5 and extension −3.0. Directional conclusions survived; every per-window magnitude was wrong. |
| E2 | **`--heading-lock` FAILED** | Judged on aggregate 5/95. Today's phantom instrument showed aggregate 5/95 cannot see a ~150-vehicle defect inside a 6000-event window. The right instrument (phantom-slot / reclassification count) did not exist when it was killed. |
| E3 | **"Journey dedup criterion CLOSED"** | `v2_pair_geometry.py` breaks out at `if f0s[b] > f1s[a]`, so it only ever examined TIME-OVERLAPPING pairs. Sequential fragments of a stopped vehicle — the queue signature — were structurally invisible to it. The conclusion is sound for co-temporal twins and says nothing about queue fragments. |
| E4 | **"Detection recall is not the bottleneck; association is"** (the ft2 lesson, `phase0_diagnostics:73`) | Measured BEFORE any assembly or stabilization existed. **G-A4 was pre-declared precisely to re-test it under the solver — and was never reached.** If association improves, the ft2 disposition is explicitly owed a re-test. This is the campaign's single most load-bearing "dead" conclusion. |
| E5 | **My own G-P1 (today)** | One selector, one formulation: mean gap over links. Never tried per-link, volume-weighted, or the residual SIGN structure — and `reverse_balance` was ledgered untried by my own hand. |

## F. GENUINELY DEAD — do not re-spike

Listed so the rest of the inventory can be trusted. Each was measured
multiple times or has a understood mechanism for why it must fail.

- SAHI at VGA source; GAN / video super-resolution; feature-level VOD (0–9 AP at <16 px).
- **Four** pairwise channels on far-band concurrent twins: geometry ×2, appearance ×1, co-life IoU ×1. Image-space pairwise signals on that class are exhausted.
- Velocity-continuity link term at 640×480 (8-point fits are noise).
- Drawn-channel attribution as an assignment target (4× measured; snap-magnet).
- Chain-economics MCF with evidence bounties; structural birth/death pricing in bipartite assignment.
- ×-scaled merge expecteds; bank-D drawn-path fill (twice); per-camera detection-profile config lever.
- V2_TIMELOCAL (segment census inherits segment recall bias); V2_GATE_AXIS (perpendicular-to-local-travel refuted as the target).
- Endpoint extension at cam1/cam4/cam5 — three variants measured 2026-08-11; the best is still net-negative where the campaign already stands down.

## G. RESEARCH NOT YET SWEPT

The 2026-08-03 synthesis was four sweeps: TMC counting SOTA, offline global
MOT, low-res detection, industry practice. It is one week old but it was
scoped to the questions we had **before** we knew the damage was turn-shaped
and queue-shaped. Not swept:

- **Tracking/counting for STOPPED and QUEUED vehicles specifically.** The
  research names this as the published blind spot of the best available
  method (I-24) and today's evidence implicates it directly.
- **Trajectory imputation / completion** as its own literature (distinct
  from stitching).
- **Turn-specific fragmentation** — there is in-repo evidence (see H1) that
  fragmentation is regime-dependent, which no sweep has looked for.
- Anything published since 2026-08-03.

## H. IN-REPO, PRE-V2, NEVER RE-TESTED UNDER V2

**H1. The per-regime tracker HYBRID.** `scripts/hybrid_prototype.py`:

> *"ByteTrack gets THROUGHS right (IoU-continuity, no fragmentation on
> straight arterials; SB-thru 425≈manual 424) but fragments TURNS; OC-SORT
> recovers TURNS (2×; NB-left 97≈96) but over-counts throughs (631 vs 424 via
> ID-switches). So: attribute THROUGHS from ByteTrack + TURNS from OC-SORT."*

`assemble_study_hybrid.py` records that cam2/cam4/cam5 once shipped their best
numbers on that hybrid recipe. The current chain uses ONE tracker per camera
(cam1/2/3 botsort, cam4/5 bytetrack). V2 never re-tested the hybrid.

This matters because Block 0 measured that the damage is concentrated in TURN
cells — `EB left` failed at every window on three cameras, and cam1's
reclassification runs through→turn. There is prior in-repo evidence that turn
fragmentation is **tracker-specific and separable by regime**, and it has not
been revisited since the V2 campaign began.

---

## Ranked shortlist (my read, for the operator's decision)

1. **D1 — conservation pass under the activation precondition.** Cheapest
   real option. The mechanism is proven (cam2 9.1→3.3%), the sole reason it
   was retired is fixed and shipped, and nobody re-tested. Config change +
   measurement, no new mechanism.
2. **H1 — re-test the tracker hybrid.** Code exists, and it targets exactly
   the turn cells Block 0 implicated. Cheap relative to its evidence.
3. **A1 + B2 — tubelet stabilization with a zero-velocity hypothesis.** The
   only lever aimed at the real wall (journeys never born). Real build, but
   it has a cheap kill gate (synthetic-fragmentation purity).
4. **G — a second research sweep scoped to queued/stopped vehicles** before
   building A1, since that is where the published blind spot sits.
5. **E4 — re-test the ft2 detection basis** once association improves. Owed
   by a pre-declared gate (G-A4) that was never reached.
6. **B1 — the structural twin test.** Named as the one untried channel, code
   already exists, never gated.
