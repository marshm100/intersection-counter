---
description: Produce a one-page laymen's weekly report for the boss from the task log
---

You are writing a **one-page weekly report for a non-technical manager** (the user's boss) summarizing what was built on the Intersection Counter project over the last 7 days.

## Source data

Read `logs/task-log.jsonl` — one JSON object per line, with fields:
- `started_at`, `ended_at`, `duration_seconds`
- `prompt` — the user's verbatim request that kicked off the task
- `files_changed` — files modified during the task
- `commits` — git commits made during the task window (SHA + message)

Filter to entries where `started_at` falls in the **last 7 calendar days** (use today's date as the anchor).

Also read `docs/Implementation_Plan_v2.md` to understand where the project is in its planned build order, and `git log --oneline -n 30` for additional commit context.

## Audience and tone

The reader is a manager who has no idea what YOLO, trajectory clustering, sqlite, or Flask are. Write in plain English. No file paths, no commit SHAs, no jargon. If you must name a feature, name it the way an end-user would (e.g., "the calibration screen", "the review page", "the Excel export").

## Output

Produce ONE page (roughly 400-500 words) with these sections:

### 0. Headline (one line, only if there is one)
If the week produced a single quotable result — a measurable jump in a core metric, a milestone shipped, a breakthrough validated, a blocker finally resolved — lead the report with it as a one-line callout at the very top, set off visually (bold, or under a `HEADLINE` banner). One sentence. In plain English, with the number if there is one.

Examples of what qualifies:
- "Vehicle-counting accuracy on our test intersection jumped from 63% to 92% this week."
- "The tool ran end-to-end on a full 24-hour recording for the first time."
- "Fixed the tracker bug that had been silently dropping ~40% of vehicles."

If nothing this week clears that bar, skip this section entirely — don't manufacture a headline.

### 1. Top-line summary (2-3 sentences)
What was the focus of the week, and how does it move the overall project toward a finished, polished tool that traffic engineers can actually use day-to-day?

### 2. What got done, by day
For each day where work happened, a short paragraph (~2-4 sentences):
- **What area of the project was worked on** — name the user-facing component (e.g., "the review screen, where the engineer corrects mistakes the AI made")
- **What that component is for, in plain English** — one sentence so the boss understands why it matters
- **What was actually built or fixed this day** — bundle small tasks into one story; don't list every prompt verbatim
- **How it fits the bigger picture** — one phrase tying it to the goal of replacing GoodVision/Miovision

Group related prompts. If three prompts in a row were all about the Excel export, write one paragraph about Excel export, not three.

### 3. Time spent
A short table with approximate hours per area of the project. Bucket by user-facing component, not by individual task. Example:
- Review & correction screen: ~3.5 hrs
- Excel report generation: ~2 hrs
- Calibration setup: ~1.5 hrs
- Misc fixes & polish: ~1 hr

Round to the nearest half hour. Pull totals from `duration_seconds`.

### 4. Where the project stands
2-3 sentences on how close the project is to "fully polished and ready for daily use." Use the Implementation Plan to anchor this — what major steps are done, what's still ahead. Be honest but framed for a manager: e.g., "Core processing pipeline and review workflow are working end-to-end; remaining work is polish on the calibration flow and validation against real-world video."

## Hard rules
- One page. Don't sprawl.
- No technical jargon. If your draft contains the words "YOLO", "ORM", "endpoint", "schema", "refactor", or a file path with a slash in it, rewrite that sentence.
- Numbers should be approximate and rounded — the boss wants signal, not precision.
- If the log file doesn't exist or is empty, say so directly and stop. Don't fabricate.
- If there is a real headline this week, it MUST appear at the very top as the one-line callout (section 0) — not buried in a day-by-day paragraph. Look for it in: handoff docs (`docs/handoffs/`), snapshot files (`evaluations/*.json` diffs), and prompts/commits using words like "validates", "jumped", "shipped", "first time", "fixed the bug that". If nothing qualifies, omit section 0 — never invent one.
