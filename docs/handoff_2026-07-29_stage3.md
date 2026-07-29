# Handoff — 2026-07-29 Stage-3 block (star rating at ingest; STAGE 3 COMPLETE)

Same session as the Stage-2 block (`handoff_2026-07-29_stage2.md`).
Everything on `claude/accuracy-impl-2026-05-27`, committed + pushed.
872 tests green (+12). Plan of record `plan_595_standard_2026-07-28.md`
(STAGE-3 RECORD added); block detail `plan_stage3_star_rating_2026-07-
29.md`. No server left running; production project.db untouched this
block (Stage 2's sweep state stands); new sidecar caches
data/projects/*/footage_rating_cam*.json (cheap, regenerable).

## What happened

1. **Plan doc with a pre-run amendment that mattered**: the first gate
   table leaned on GT knowledge (cam1 ★★★). Computing the phase-0
   censuses' implied values BEFORE building showed tag coverage +
   fragmentation are geometry-confounded corpus-wide (FM51, the
   cleanest site, scores worst on both) and the ONE defensible blind
   axis is same-cell echo composition. Table amended pre-run; the
   refusal to threshold-fit GT-known classes is written into the plan.
2. **3.1 service** (footage_rating.py): tiered blind rating — A
   metadata (640×480 caps ★★★★ everywhere in the corpus: the
   procurement point, now computable), B chain census, C time-scoped
   event join (validity self-checked). Frozen ECHO_SHARE_FAIR = 0.04
   in the measured gap (production clean sites 1.3–2.4% vs cam5/cam4
   replay 5.7/10.7%).
3. **Gate run 1 FAIL = a real catch**: joining events to dumps by id
   MEMBERSHIP let cam1's live-legacy 16:00–18:00 events collide with
   the 07:00 dump's id space → phantom echoes (7.3% vs true 2.4%).
   Fix: events assign to a variant by TIME, then join by id; uncovered
   events counted separately. Threshold untouched. **Run 2: PASS 6/6**
   — cam4/cam5 ★★★ (cam4's phantom pool seen blind), rest ★★★★,
   cam4/cam5/FM51 via the NAMED phase-0 replay basis (their production
   tables predate the on-disk dumps — 37/39/87% unmapped, correctly
   refused; any NEW site joins by construction).
4. **3.2**: GET /projects/{pid}/cameras/{cid}/footage-rating +
   intersection-card panel (stars + one sentence + "Why this rating?",
   tier A/B = PROVISIONAL). Endpoint live-verified against production
   (server started + stopped clean, port-5000 discipline). Honest gap:
   no browser automation this session → the rendered-panel screenshot
   is owed from the next operator session.

## NEXT per the checklist

Stage 4 (child-test UX passes — 4.1 tally spot-count screen with the
live certification meter, 4.2 one-question review cards, 4.3 cardinal
wizard + auto-trims, 4.4 traffic-light export language; the real gate
for all four is the 6.4 operator rehearsal) and/or Stage 5.1 (phantom-
small-cell treatment corridor-wide — now directly motivated: cam4's
echo pool is the star-rating's own finding). 5.2 LEC2 needs [OP]
authorization.

## The operator's court (one URGENT, one new)

- **6.2 QUALIFYING FOOTAGE procurement — URGENT, long-lead.** The star
  rating now SHOWS the ceiling: every corpus camera caps at ★★★★
  solely on resolution. ★★★★★ (the guarantee tier) is empty until
  qualifying footage exists.
- **Studio dry-run** — now also covers the new bin-card worklist AND
  the footage-rating panel (screenshot owed).
- Trims for cams 3/4/5 (tightens claim scope, queue, and the rating's
  night handling).
- 5.2 LEC2 activation authorization (when wanted).

## Standing discipline (unchanged)

Plan doc before mechanism; measured ablations; pre-declared gates
(twice this session a gate KILLED something before it shipped — R1 in
Stage 2, the id-membership join in Stage 3; that is the system
working); negatives are deliverables; name the scoring basis (this
block: production vs phase-0 replay census bases, named per row); FM51
held-out; detached jobs via Start-Process; kill port-5000 owners
before serving; replay scratch in _replay_scratch, never %TEMP%.
