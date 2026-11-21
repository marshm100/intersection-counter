---
description: Independent review of an arm plan or a shipped default change, by a session that did not build it
argument-hint: <docs/plan_*.md or a commit range>
---

Review `$ARGUMENTS` as an independent reviewer. You did not build it; do not trust any "done" claim.

1. Read docs/LESSONS.md and the plan. Check it against docs/ARM_TEMPLATE.md: a named requirement and owner,
   a delete line, few constants, a gate declared before scoring. A missing line is a finding.
2. Ground truth FIRST, before reading the builder's narrative:
   - fleet score vs the current default (CLAUDE.md), per-camera and per-window against the gate's thresholds;
   - per-vehicle journey labels (scripts/eval_journeys.py), not just 5/95 totals;
   - confirm the scorer read a fresh working DB (mtime) and that no other fleet ran concurrently.
3. Then spec vs result: did the arm do what its requirement said, and did it delete what it promised?
4. On a risky step, name the test that SHOULD fail if the change were wrong, and say whether it exists.
5. Report bad news first, in plain words, no internal ids. Verdict: PASS / FAIL / PASS-WITH-RULING-NEEDED, with
   anything unproven stated as unproven. Propose a LESSONS.md line only from a measured failure.

Read-only: do not edit code, run fleets, or change defaults.
