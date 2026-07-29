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

## Findings (operator writes here)

- …
