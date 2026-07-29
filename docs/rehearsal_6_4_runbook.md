# 6.4 OPERATOR REHEARSAL — the walkthrough runbook (2026-07-29)

The REAL gate for every Stage-4 surface. You are not admiring screens —
you are trying to break them and recording where the child test fails.
Budget ~60–90 min. Findings go at the bottom of this file (one line
each: surface · what you tried · what confused/failed). Every surface
below is Playwright-smoked, so anything broken you find is a REAL
finding, not bitrot.

Start: `py start_server.py` → http://127.0.0.1:5000 → open the
Sunnyvale corridor project.

## 1. Trims in one click (intersection 3, then 4 and 5)
Open intersection 3 → Clip trim tab. You should see "Your footage
covers … Studies usually count the peak windows — accept these?"
- ACCEPT the peaks if they match your intent for the study (this is
  the real decision, which is why the tour left it to you). cam3 also
  offers "count everything (daylight)".
- Try to break it: accept one row twice; delete an accepted row; check
  the windows land in the trims table below and survive a reload.
- Effect to verify later: the QA queue and star rating tighten on the
  next rebuild/pass-2.

## 2. The footage rating (any intersection detail)
One glance: stars + one sentence per camera. Click "Why this rating?".
- Child test: do the reasons read like a person explaining, or a log?
- cam4/cam5 should say PROVISIONAL (their tables predate the dumps).

## 3. The compass wizard (any camera → Calibrate)
Legs panel → "Set all directions by compass". Turn the dial wrong on
purpose; check every leg's preview label; Apply; then fix one leg by
its dropdown (override must win). Cancel path too. DO NOT Save unless
the result is right — Save is the commit point.

## 4. The tally screen (a camera's QA tab)
"Count a 30-min window" → count along with the footage for a few
minutes. Try: keys only (↑↓ 1–4 Z Space); the meter's language; Cancel
and confirm nothing saved; then a real short count → Save & compare →
read the report → "Keep counting this window" (the extend loop) →
Save again → confirm ONE spot row for the window on the QA tab.
- Child test: could you do this while watching traffic, without
  reading instructions?
- Independence check that matters: BEFORE save, nothing on the screen
  should hint at what the system counted.

## 5. The worklist (QA tab → Review worklist)
Work ~10 cards for real. Every card: is the question the RIGHT
question? Is the giant button the answer you wanted? Z-undo something;
batch-resolve a group; reopen a machine-closed item (status filter →
auto_resolved) and see it return.
- The banner should tell you what the machine closed and why that is
  safe.

## 6. The export lights (Export page)
One light per intersection-day; "what stands between you and export"
should be a to-do list you AGREE with, in words you'd use. int3 should
show the directional-balance prompt (real full-day signal); the
others should NOT show balance noise.

## 7. The studio (F2/F3 — first human use, still owed)
Run an auto-cal on any camera (F2 live view: boxes + trails + honest
progress); then the playback studio (F3): scrub, watch synced track
replay, toggle layers.

## PLAYWRIGHT EXECUTION (operator-directed, 2026-07-29) — protocol

The operator directed the rehearsal be EXECUTED by the agent via
Playwright. Rules, pre-declared:
- REAL mutations where the intent is on record and reversible: trims
  accepted per the established study scope (int4/int5 = the three
  processed peaks exactly; int3 = the daylight envelope, its claim
  basis in every 5/95 number); the compass APPLIED on cam3 at the
  no-op angle (the north that derives exactly today's cardinals —
  full write path exercised, zero net change, verified by re-fetch).
- NEVER fabricated: no spot-count SAVE (a made-up manual count would
  poison certification — counting is the independence-bearing human
  act); no card decisions that alter events (one flag accepted then
  UNDONE exercises the flow; clip judgment is human work).
- F2 auto-cal: started for real, progress watched, then CANCELLED
  (exercises the live view + cancel plumbing without hours of compute).
  F3 studio: played, scrubbed, layers toggled (read-only).
- Findings recorded below; code-fixable ones WORKED OFF in the same
  block; human-judgment items (language clarity, real counting flow)
  remain flagged for the operator's shorter follow-up pass.

## Findings (rehearsal 2026-07-29 — EXECUTED 9/9 via Playwright;
evidence screenshots/rehearsal_64_*.png; operator adds theirs below)

WORKED OFF in the same block (both found BEFORE the browser opened —
the rehearsal's prep caught them):
1. **Compass wizard geometry**: on oblique/T views (cam3-class = the
   FM51 class) the correct cardinal set can be UNREACHABLE at any dial
   angle — perspective compresses image angles and one arm lands on
   the neighboring diagonal. FIXED to a cyclic-order assignment
   (perspective-robust; symmetric layouts unchanged) + the limitation
   written into the wizard copy ("check every label; fix any odd one
   with its dropdown"). The wizard is EXACT at cam2/cam5, one-arm-off
   at cam1/cam3/cam4 — the preview + per-leg override is the designed
   recovery, verified live at cam3.
2. **Legs save wiped counted events on a label-only change** — the
   recalibration semantics deleted the camera's whole event table even
   when only cardinals/labels changed (the FM51 mislabeled-cardinals
   fix, the wizard's OWN use-case, would have destroyed the counts).
   FIXED: geometry-identical saves update in place, preserving leg_ids
   and events; positional changes keep the wipe semantics. Verified
   live: cam5 compass Apply+Save at its no-op angle left leg_ids,
   cardinals, and events byte-identical.
3. **Reverse-balance single-long-trim wrinkle**: declaring int3's
   daylight trim would have silenced its genuine full-day balance
   prompt under the trims-demote rule. FIXED (peak-shaped trims only:
   several windows or one short one); verified live post-accept
   (int3 rb stays applicable).

EXECUTED with real state (all intended, all reversible):
- Trims DECLARED for the whole corridor: int3 = daylight 06:00–20:00;
  int4/int5 = the three standard peaks (int1/int2 already had theirs).
  Claim scope, R5, spot segmentation, star-rating night handling now
  ride declared trims corridor-wide.
- Worklist: a live card resolved by Enter and restored by Z (undo
  fidelity server-verified); three cards walked.
- Tally: keyboard counting flow, volume-only meter, cancel — no spot
  row written (verified; the single spot row on file is 2026-06-12,
  pre-existing).
- F2 auto-cal started (live progress), cancelled clean. F3 studio
  playback surface verified. Export lights: exactly ONE directional-
  balance line remains (int3's genuine one; was 5 before the fix).

REMAINS FOR THE OPERATOR (the human-judgment slice — shorter pass):
- Language feel on every surface (does each question read as YOUR
  question?); the tally flow with real traffic and real counting (the
  independence-bearing act is inherently yours); a true F2 run to
  completion + suggestion accept/reject on a camera you care about;
  card CLIP judgment on a handful of real cards.

- …
