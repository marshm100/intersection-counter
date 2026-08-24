# Diagnosis: HOW the refit paths lost (G-DG-1 post-mortem, 2026-08-23)

Operator ruling after the verdict: three negatives condemn the current
IMPLEMENTATION, not path averaging as a concept. The intended architecture —
gates cut mouth-to-gate journeys; cut journeys average into a guiding path;
partial tracks classify by comparison against the guides — is sound. This doc
is the track-level answer to "show me how it is failing."

## Method

Same pass-1 dumps feed ctrl and arm, so vehicle_track_id joins 1:1 across the
two working DBs per window. Every difference the path swap made is a per-track
flip. Score artifacts give per-cell Miovision truth.

## Finding 1 — the loss is ONE mechanism, not diffuse

~99% of tracks classify identically either side (57,430/58,186 unchanged at
0700). The flips concentrate overwhelmingly in ONE pattern, in all three
windows: **EB right -> EB through** (164 / 259 / 499 tracks), plus the same
shape at NB (NB through -> NB left: 85 / 99 / 117).

## Finding 2 — the flips live exactly in the cells the curated set left
path-less

The old curated set has NO guide for 28->26 (EB through), 29->26, 26->29 —
the three cells W1a listed for hand-drawing. The refit added guides for all
three. The arm's biggest net gainers are precisely those cells:
EB-thru +287/+397/+719, NB-left +100/+112/+117.

## Finding 3 — against Miovision, BOTH bases are wrong; the arm overshoots
harder (study_1600)

| cell | Mio | ctrl (no EB-thru guide) | arm (new EB-thru guide) |
|---|---|---|---|
| EB through | 454 | 288 (-166 under) | **1028 (+574 over)** |
| EB right | 699 | 1078 (+379 over) | 584 (-115 under) |

With no through-guide, pre-divergence truncated tracks all fall to EB-right
(right overcounted, through undercounted). With a through-guide, the same
tracks over-swing to through — the correction is ~4x the deficit it was
meant to fill.

## Finding 4 — the root cause in one sentence

**EB-right and EB-through share the entire approach until the divergence
point; a truncated track that dies before divergence is geometrically
compatible with both guides, and the matcher pretends shape can arbitrate
anyway.** A straight partial track matches the straight through-guide better
than the curving right-guide, so whichever cell HAS a guide (and how straight
it is) decides hundreds of vehicles that geometry cannot actually decide.

Corroboration: SB-right got WORSE under the cleaner guide (-84 -> -213
against Mio) — the old "splice-shaped fold" path 125 hugged where PARTIAL
tracks actually live and caught them; the idealized full-journey average
misses them. Guides averaged from complete journeys describe complete
vehicles, but the population needing guides is the truncated ones.

## Finding 5 — the fix concept ALREADY EXISTS in this codebase

backend/services/path_divergence.py (built 2026-07-27 for cam5's
claim-eligibility): "a track whose projected coverage on P never reaches past
P's divergence from a sibling cannot geometrically be told apart from that
sibling." That rule is NOT enforced in the pass-2 path-match arbitration that
produced these flips.

## Next-lever hypotheses (pre-register before any scored run)

1. **Divergence-gated arbitration**: when candidate guides share an origin,
   shape may only vote using post-divergence geometry; a track ending before
   the divergence point gets NO shape vote between those cells.
2. **Volume-prior tie-break for pre-divergence tracks**: the corpus bank's
   merge_expecteds gives per-cell expected volumes; use as the prior where
   shape is uninformative.
3. **Guides for the truncated population**: fit per-cell guides from partial
   journeys too (what the old splice paths did by accident), or extend
   full-journey guides with observed truncation geometry.

Artifacts: regatectrl/regatearm working DBs in
_replay_scratch/regate_20260823/, score_regate*_cam2_study_*.json,
scratchpad diff script preserved in this doc's history.
