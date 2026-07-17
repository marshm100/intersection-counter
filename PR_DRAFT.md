# PR: Accuracy campaign — item 8 adjudicated, Miovision-parity deliverables, fine-tuned detector promoted (FM51 -9.1% -> +1.1%)

Base: claude/bootstrap-project-structure-TC2A0  <-  Head: claude/accuracy-impl-2026-05-27
Create at: https://github.com/marshm100/intersection-counter/compare/claude/bootstrap-project-structure-TC2A0...claude/accuracy-impl-2026-05-27

## Summary

Three workstreams closed across the 2026-07-14..17 session block (~240 commits):

### Item 8 — attribution walls: CLOSED
- Mechanism 1 (origin-evidence gate + partial-evidence posterior + conservation
  pass) built behind default-OFF flags and adjudicated over THREE blind
  five-camera sweeps: proven where entry-evidence coverage is high (cam2
  9.1 -> 3.3-3.5% per-approach MAE), not blind-deployable at low-coverage
  cameras; retired per its pre-committed budget, code + tests revival-ready.
- All three walls carry evidence-backed verdicts; SB-right's 1.07 recall
  exposed as cancellation (true trackable recall 0.12-0.16).

### 3-E Miovision-parity deliverables: SHIPPED
- Parity-audited against the real client deliverable: geometry-aware Summary
  sheet (per-leg movement columns, I/O, PHF, dual peaks), TMV Table/Data,
  letterhead-configurable PDF (per-minute + 15-min pages), per-intersection-day
  gated export endpoints + card buttons. Verified live; no-formulas test-pinned.

### 3-D detector fine-tune: DONE AND PROMOTED
- In-app labeling tool (new); 430 operator-labeled corridor frames; 64 CPU
  epochs in resumable warm-start chunks on the engineer's laptop.
- Held-out FM51 full-chain gate: total -9.1% -> +1.1%, interval MAE
  8.8% -> 2.5% (PASS), the documented PM low-light miss CLOSED, NB approach
  -19.2% -> +4.6% — on a site the model never trained on.
- Promoted into the Balanced profile (yolo26s_ft1 @640, class-scheme mapped;
  one-line fallback). Known residual (far-field side-leg origin grab) shipped
  eyes-open per operator decision, owned by plan_origin_grab_cycle_2026-07-17
  and surveilled by the flag queue.

### Also
- GPU: detect_batch fixed on the OpenVINO iGPU backend — suite fully green (798).
- Full plan-doc trail for every verdict, including the negatives.

## Test plan
- python -m pytest backend/tests/  (798 passing)
- Live drives recorded in the plan docs (exports via UI; labeler; FM51 replays)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
