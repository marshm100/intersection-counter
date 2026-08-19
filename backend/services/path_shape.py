"""Path shape QA — the fold gate (operator ruling 2026-08-19).

A drivable movement spreads its heading change along an arc; a tracking
splice folds it into a near-reversal concentrated at one point. The live
path banks fit through RAW trajectories were found carrying exactly such
folds (cam2 paths 122/125 at -169/+173 deg in a single chord step; also
cam1 16, cam3 117, cam5 83/84) — the operator ruled concentrated sharp
angles disqualifying for a path. This module is the single home for that
rule so every place a polyline is born or admitted applies the same test.
"""
import math

# Displacement chord for heading estimates: bearings are measured over
# chords spanning >= this much NET displacement, so stationary jitter
# cannot fake a turn (same trick as the A3 pinch discriminator —
# docs/plan_a3_split_2026-08-19.md amendment 3).
PATH_CHORD_PX = 25.0

# A member trajectory whose concentrated flip reaches the A3 pinch angle
# is splice debris and must not vote on a fitted path's shape. Same-zone
# (u-turn) trajectories are exempt — a tight u-turn legitimately hairpins.
MEMBER_PINCH_DEG = 120.0

# A fitted polyline may not concentrate this much heading change into a
# single ~25 px chord step. Real tight corners under perspective spread
# their turn across chords; the condemned live folds measured 116-173 deg.
PATH_FOLD_REJECT_DEG = 100.0


def max_concentrated_turn(points, chord_px: float = PATH_CHORD_PX) -> float:
    """Largest absolute heading change (degrees) between consecutive
    displacement chords of a sequence of (x, y) points.

    Returns 0.0 when the sequence never accumulates two chords (too short,
    or pure stationary jitter — which is the point of chording).
    """
    if len(points) < 3:
        return 0.0
    chords = [tuple(points[0])]
    for q in points[1:]:
        if math.hypot(q[0] - chords[-1][0], q[1] - chords[-1][1]) >= chord_px:
            chords.append((float(q[0]), float(q[1])))
    best = 0.0
    for a, b, c in zip(chords, chords[1:], chords[2:]):
        h1 = math.atan2(b[1] - a[1], b[0] - a[0])
        h2 = math.atan2(c[1] - b[1], c[0] - b[0])
        d = abs(math.degrees(h2 - h1))
        if d > 180.0:
            d = 360.0 - d
        if d > best:
            best = d
    return best
