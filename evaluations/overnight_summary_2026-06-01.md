# Overnight corridor run — 2026-06-01

Elapsed: 3.4 h.  Log: `overnight_2026-06-01.log`.

net% / gross% = per-minute OD error vs Miovision (lower better).

| run | mode | BoT+bank (net/gross) | bytetrack-hybrid (net/gross) | applied |
|---|---|---|---|---|
| cam4@5min | finish | 18.5/18.5 | 41.0/43.3 | bank (gross 18.5) |
| cam5@5min | finish | 32.2/37.0 | 67.3/69.2 | bank (gross 37.0) |
| cam4@30min | finish | 63.7/66.7 | 22.7/32.7 | hybrid (gross 32.7) |
| cam5@30min | finish | 88.9/98.7 | 29.1/43.2 | hybrid (gross 43.2) |
| cam3@30min-preview | preview | 14.6/18.3 | — | NONE (preview — gate in AM) |
| cam2@30min-preview | preview | 69.4/87.5 | — | NONE (preview — gate in AM) |

## Morning actions
- cam4/cam5: applied automatically (winner by gross, atomic backup). Verify + visual-gate.
- cam2/cam3 30-min: PREVIEW only (project.db untouched). If the 30-min number beats the
  shipped 5-min, ship it with a gated destructive run, e.g.:
  `py scripts/reprocess_camera.py --camera 2 --minutes 30 --yes` then `build_bank`/`apply_*` --apply.
- All applies make a backup in data/projects/97a7849a/backups/.
## Findings & state (added post-run)
**Corridor COMPLETE — all 5 cameras shipped.** Live per-min gross: cam1 18.8% | cam2 38.4% (5-min hybrid) | cam3 13.2% (5-min bank) | cam4 32.7% | cam5 43.2% (both 30-min hybrid). cam2/cam3 untouched (preview was non-destructive).

**KEY FINDING — BoT+bank "snap magnet" at long windows.** BoT+bank gross degraded 5→30min (cam4 18.5→66.7, cam5 37→98.7) while bytetrack-HYBRID improved (cam4 43→33, cam5 69→43). Cause: a low-support RARE-TURN bank path captures the dominant throughs (cam4 30min: EB-left manual 6 → ours 325; NB-thru 728→349). At 5-min the rare turn is below min_support=5 so the bad path doesn't exist. **min_support=5 too low at scale; bank needs a path-quality / through-protection gate.** Hybrid is immune (keeps bytetrack throughs) → it won at 30-min, correctly shipped.

**No action needed tonight** — shipped states are sound and reversible (backups). The bank fix + re-measure of cam3/4/5 is the next-session task. Do NOT ship the 30-min preview banks as-is (they exhibit the snap-magnet bug). Ignore cam2 preview 87.5% (bank-only, not its hybrid path).
