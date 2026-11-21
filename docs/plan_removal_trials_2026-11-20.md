# ARM — removal trials, step 1: the flag inventory (2026-11-20)

Filled in BEFORE any scoring. This arm builds the list only; no flag is removed and no fleet is run in it.
Each removal it proposes becomes its own later arm with its own gate.

## 1. Requirement — question it
- **What failure does this fix?** `backend/config.py` has ~60 boolean flags (env overrides). CLAUDE.md says "env vars are
  overrides for experiments; nothing in production needs them set", yet no list says which ever changed a result.
  9.123-9.126 deleted four rules by hand with no inventory; `V2_MERGE_RESCUE` is still open as "unproven dead".
- **Whose words?** CLAUDE.md "How we work": "A rule/flag that never changed a result goes to a removal trial"; docs/LESSONS.md
  review-date rule; the handoff of 2026-11-20 ("(1) removal trials: list shipped flags/rules with owner and whether each
  ever changed a result").
- **Physics or recommendation?** Recommendation. If we do nothing: dead experiment flags keep multiplying code paths and
  the unmeasured-default risk after each deletion grows.
- **Raw video + calibration alone?** Not applicable (no runtime change in this arm).

## 2. Delete — before adding
- Makes unnecessary: nothing yet. The inventory is the input that names deletions. The script is throwaway-grade and
  lives in `scripts/` only if it is reused by arm 3; otherwise it is deleted with this arm.
- Add-back rule: n/a until a removal arm runs.

## 3. Simplify
- Zero new constants. The script parses `config.py` text; no thresholds.
- A flag counts as "ever changed a result" only on evidence: an arm result in docs/ or a CLAUDE.md ship line naming it with
  a score. Merely being mentioned in a doc is not evidence.

## 4. Accelerate
- Slowest stage is classification by reading docs. The script pre-computes code refs, default, test refs, script refs and
  doc mentions so only the ambiguous flags are read by hand. No video, no dumps.

## 5. Automate — last
- Nothing yet. The one-off table is the first by-hand run.

## Gate (declared before the run)
- Output: `docs/removal_trials_inventory_2026-11-20.md` — one row per boolean flag: default, owner/ruling, evidence it
  changed a result (cite) or "none found", status = KEEP-SHIPPED / EXPERIMENT-OFF / DEAD-CANDIDATE.
- PASS: every boolean flag in config.py has a row; every DEAD-CANDIDATE cites what was searched; no code or config edited;
  pytest count unchanged at 1394.
- Known risks: "changed a result" evidence may live only in handoffs or the DB; absent there it reads "none found",
  which is not proof of dead. Candidates then need a trial, not a deletion.
- No scorer is read, so the stale-DB check (LESSONS 2026-10-15) does not apply.

## Independent review
`/review-arm docs/plan_removal_trials_2026-11-20.md` in a fresh session, after the inventory exists.

## Review date
2027-02-20.
