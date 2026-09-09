"""THE JOURNEY STATE MACHINE (operator rulings 2026-09-09).

R1  "The lower corners need to cross the exiting line before it can be
    counted as exit."  A crossing counts only when BOTH bottom corners
    cross the line.
R2  "Once it crosses the exit, that detection ID can no longer be used
    as a valid ID for crossing because that vehicle is already left."
    EXITED is terminal.
Plus his approved split: a single-corner crossing counts when the TRACK
ENDS there (truncated by tracking loss), never when it continues (the
vehicle is sitting on the line).
"""
import backend.config as cfg
import pytest

from backend.services.entry_gates import classify, classify_pair, pair_crossings
from backend.services.pipeline import ProcessingPipeline

FPS = 10.0
# A box intersection: N gate on the left (x=200), S gate on the right
# (x=800), W gate at the bottom (y=600). Inward normals point at the
# centre (500, 300). Same geometry as test_first_exit.
GATES = {
    1: ((200.0, 100.0), (200.0, 500.0), (1.0, 0.0)),      # N (left)
    2: ((800.0, 100.0), (800.0, 500.0), (-1.0, 0.0)),     # S (right)
    3: ((300.0, 600.0), (700.0, 600.0), (0.0, -1.0)),     # W (bottom)
}
HALF_W = 15.0          # box half-width: corners sit at cx -/+ 15


def _line(x0, x1, y, f0, n=40):
    return [(float(f0 + i), x0 + (x1 - x0) * i / (n - 1), float(y))
            for i in range(n)]


def _corners(centre):
    """bottom-centre path -> (left-corner path, right-corner path)."""
    return ([(f, x - HALF_W, y) for f, x, y in centre],
            [(f, x + HALF_W, y) for f, x, y in centre])


def _pair(centre, lanes=None):
    l, r = _corners(centre)
    return classify_pair(l, r, GATES, FPS, lanes)


class TestCrossingLaw:
    def test_clean_through_both_corners_pair(self):
        # in over N, out over S; each gate crossed by both corners a
        # couple of frames apart -> one valid crossing per gate.
        o, d, fo, fd, *_rest, tag = _pair(_line(150.0, 850.0, 300.0, 0))
        assert (o, d, tag) == (1, 2, "full")
        # stamped at the LATER corner: the trailing corner over N is
        # the LEFT one (moving right), over S it is also the left one
        l, r = _corners(_line(150.0, 850.0, 300.0, 0))
        valid = pair_crossings(l, r, GATES, FPS)
        assert [(c[1], c[2]) for c in valid] == [(1, True), (2, False)]
        assert fo > 0 and fd > fo

    def test_straddle_is_no_crossing(self):
        # the operator's sample A: the box sits ON the N line. The left
        # corner creeps inward over it while the right corner reads
        # OUTWARD over the same line, and the track continues for 30 s.
        # Corners disagreeing on direction over one line is impossible
        # for a genuine crossing -> nothing counts.
        left = ([(float(i), 195.0, 300.0) for i in range(10)]
                + [(float(i), 205.0, 300.0) for i in range(10, 300)])
        right = ([(float(i), 215.0, 300.0) for i in range(10)]
                 + [(float(i), 198.0, 300.0) for i in range(10, 300)])
        assert pair_crossings(left, right, GATES, FPS) == []
        *_rest, tag = classify_pair(left, right, GATES, FPS)
        assert tag == "no_crossing"

    def test_departure_solo_corner_counts_when_track_ends(self):
        # in over N (paired), then the leading (right) corner crosses S
        # and the track ENDS before the left corner gets there: the
        # trailing corner's evidence was truncated by tracking loss.
        centre = _line(150.0, 850.0, 300.0, 0)[:38]     # ends at x~814
        l, r = _corners(centre)
        assert l[-1][1] < 800.0 < r[-1][1]               # right over, left not
        o, d, *_rest, tag = classify_pair(l, r, GATES, FPS)
        assert (o, d, tag) == (1, 2, "full")

    def test_wobble_solo_corner_refused_when_track_continues(self):
        # same as above but the box then sits still for 20 s with one
        # corner each side of the S line: a vehicle sitting on the
        # threshold, not a departure.
        centre = _line(150.0, 850.0, 300.0, 0)[:38]
        last = centre[-1]
        centre += [(last[0] + 1 + i, last[1], last[2]) for i in range(200)]
        o, d, *_rest, tag = _pair(centre)
        assert (o, d, tag) == (1, None, "entry_only")

    def test_solo_corner_beyond_truncation_window_refused(self, monkeypatch):
        # the split is a TIME rule: ends 0.5 s after -> counted; ends
        # 3 s after -> refused (CROSSING_TRUNCATION_S = 1.0)
        centre = _line(150.0, 850.0, 300.0, 0)[:38]
        last = centre[-1]
        near = centre + [(last[0] + 1 + i, last[1], last[2]) for i in range(5)]
        far = centre + [(last[0] + 1 + i, last[1], last[2]) for i in range(30)]
        assert _pair(near)[-1] == "full"
        assert _pair(far)[-1] == "entry_only"

    def test_born_across_entry_counts(self):
        # G-SM-1 iteration 2: the track is born with its right corner
        # already inside the N line (detected late, box straddling the
        # threshold); the left corner then crosses inward and the track
        # continues for 20 s. The leading corner's crossing was never
        # observable — the entry counts.
        left = _line(190.0, 260.0, 300.0, 0, n=8)      # 190 -> 260 over N
        left += [(float(8 + i), 260.0, 300.0) for i in range(200)]
        right = [(f, x + 30.0, y) for f, x, y in left]    # born at 220
        valid = pair_crossings(left, right, GATES, FPS)
        assert [(c[1], c[2]) for c in valid] == [(1, True)]
        assert classify_pair(left, right, GATES, FPS)[-1] == "entry_only"

    def test_waiting_vehicle_gets_its_entry_but_no_false_exit(self):
        # the waiting-vehicle shape (17526): the right corner was born
        # inside and crept back OUT over the same gate; later the left
        # corner enters. Iteration 2 refused this; iteration 3 (reel 2,
        # operator ruling: a spawned corner "closes properly at the
        # exit") accepts the ENTRY. The earlier OUT wobble is NOT an
        # exit (solo, track continues, no born-across for exits).
        right = ([(float(i), 215.0, 300.0) for i in range(10)]
                 + [(float(i), 190.0, 300.0) for i in range(10, 60)]
                 + [(float(i), 190.0, 300.0) for i in range(60, 300)])
        left = ([(float(i), 185.0, 300.0) for i in range(60)]
                + [(float(i), 210.0, 300.0) for i in range(60, 300)])
        valid = pair_crossings(left, right, GATES, FPS)
        assert [(c[1], c[2]) for c in valid] == [(1, True)]

    def test_born_across_never_applies_to_an_exit(self):
        # born with the right corner already OUTSIDE the S line and the
        # left corner inside; the left corner then crosses out and the
        # track continues: a box parked on the exit line, not an exit.
        left = ([(float(i), 790.0, 300.0) for i in range(10)]
                + [(float(i), 810.0, 300.0) for i in range(10, 300)])
        right = [(f, x + 30.0, y) for f, x, y in left]    # born at 820
        assert pair_crossings(left, right, GATES, FPS) == []

    def test_wide_body_pair_completes_on_the_extension(self, monkeypatch):
        # reel 3: a box so wide its left corner rides past the N gate's
        # drawn END (y < 100). The right corner crosses the drawn
        # segment, the left corner crosses only the extension. With the
        # 25% margin (100 px on a 400 px gate) the pair forms.
        centre = _line(150.0, 850.0, 300.0, 0)
        left = [(f, x - 15.0, 60.0) for f, x, y in centre]      # y=60: off the end
        right = [(f, x + 15.0, y) for f, x, y in centre]
        monkeypatch.setattr(cfg, "GATE_EXTENSION_MARGIN", 0.0)
        assert [(c[1], c[2]) for c in pair_crossings(left, right, GATES, FPS)
                if c[2]] == []                       # drawn: no pair, no entry
        monkeypatch.setattr(cfg, "GATE_EXTENSION_MARGIN", 0.25)
        valid = pair_crossings(left, right, GATES, FPS)
        assert (1, True) in [(c[1], c[2]) for c in valid]

    def test_extension_is_bounded(self, monkeypatch):
        # a corner far beyond the margin (y = -200 on a gate spanning
        # 100..500, margin 100) still misses
        monkeypatch.setattr(cfg, "GATE_EXTENSION_MARGIN", 0.25)
        centre = _line(150.0, 850.0, 300.0, 0)
        left = [(f, x - 15.0, -200.0) for f, x, y in centre]
        right = [(f, x + 15.0, y) for f, x, y in centre]
        valid = pair_crossings(left, right, GATES, FPS)
        assert (1, True) not in [(c[1], c[2]) for c in valid]

    def test_born_across_needs_the_other_corner_within_the_gate_width(self):
        # reel 3: right corner crosses N inward while the left corner
        # sits "inside" N's half-plane but far off the segment's width
        # (y = 900, gate spans 100..500 +25%): not born across.
        left = [(float(i), 260.0, 900.0) for i in range(300)]
        right = ([(float(i), 190.0, 300.0) for i in range(10)]
                 + [(float(i), 210.0, 300.0) for i in range(10, 300)])
        assert pair_crossings(left, right, GATES, FPS) == []

    def test_spawned_corner_may_wobble_out_before_the_entry(self):
        # reel 2 clips 2 and 4: the right corner spawns beyond the N
        # mouth (inside), wobbles OUT over N once, then the left corner
        # enters. The earlier OUT is the spawn settling, not an entry.
        right = ([(float(i), 215.0, 300.0) for i in range(10)]
                 + [(float(i), 190.0, 300.0) for i in range(10, 300)])
        left = ([(float(i), 185.0, 300.0) for i in range(80)]
                + [(float(i), 205.0, 300.0) for i in range(80, 300)])
        valid = pair_crossings(left, right, GATES, FPS)
        assert [(c[1], c[2]) for c in valid] == [(1, True)]

    def test_earlier_inward_crossing_still_disqualifies(self):
        # the other corner was born inside, went OUT, then came back
        # IN over N well before the trailing corner: that earlier
        # INWARD crossing is a real entry attempt, not a spawn settling
        # -> the later solo is not born across
        right = ([(float(i), 215.0, 300.0) for i in range(10)]
                 + [(float(i), 185.0, 300.0) for i in range(10, 40)]
                 + [(float(i), 215.0, 300.0) for i in range(40, 300)])
        left = ([(float(i), 185.0, 300.0) for i in range(80)]
                + [(float(i), 205.0, 300.0) for i in range(80, 300)])
        assert pair_crossings(left, right, GATES, FPS) == []


class TestTerminalExit:
    def test_exit_is_terminal(self):
        # in over N, out over S (journey done), then MUCH later the
        # stolen box comes back across S and N: discarded under R2.
        centre = _line(150.0, 850.0, 300.0, 0)
        centre += _line(850.0, 150.0, 320.0, 900)
        o, d, *_rest, tag = _pair(centre)
        assert (o, d, tag) == (1, 2, "full")
        # ...whereas the legacy classifier (last exit wins) loses it
        assert classify(centre, GATES, FPS)[:2] != (1, 2)

    def test_first_valid_crossing_outward_is_exit_only(self):
        # born inside the box, leaves over S, later re-enters over S:
        # EXITED at the first crossing; nothing after it counts.
        centre = _line(500.0, 850.0, 300.0, 0)
        centre += _line(850.0, 500.0, 320.0, 400)
        o, d, *_rest, tag = _pair(centre)
        assert (o, d, tag) == (None, 2, "exit_only")

    def test_genuine_uturn_admitted(self):
        # in over N, deep excursion, long dwell, out over N in the
        # opposite lane -> still a u-turn (admission block reused)
        centre = _line(150.0, 600.0, 280.0, 0)
        centre += [(float(100 + i), 600.0, 280.0 + i) for i in range(80)]
        centre += _line(600.0, 150.0, 360.0, 200)
        o, d, *_rest, tag = _pair(centre)
        assert (o, d, tag) == (1, 1, "full")

    def test_same_leg_jitter_is_not_an_exit(self):
        # in over N, both corners graze back out over N at once (no
        # dwell, no excursion), then the real exit over S. The graze
        # fails the u-turn tests, so it is jitter, not a terminal exit.
        centre = _line(150.0, 260.0, 300.0, 0, n=8)
        centre += _line(260.0, 150.0, 302.0, 8, n=6)
        centre += _line(150.0, 850.0, 304.0, 20)
        o, d, *_rest, tag = _pair(centre)
        assert (o, d, tag) == (1, 2, "full")

    def test_entry_only_when_no_exit(self):
        o, d, *_rest, tag = _pair(_line(150.0, 500.0, 300.0, 0))
        assert (o, d, tag) == (1, None, "entry_only")


# ---- pipeline dispatch -------------------------------------------------

def _pipe():
    p = ProcessingPipeline.__new__(ProcessingPipeline)
    # one VERTICAL gate line at x=200, inward normal pointing right
    # (the corners share a y, so only a vertical line lets them cross
    # at different frames)
    p._entry_gates = {7: ((200.0, 100.0), (200.0, 300.0), (1.0, 0.0))}
    p.fps = 10.0
    return p


def _vehicle(traj, heights=None, widths=None):
    return {"start_frame": 100, "trajectory": traj,
            "bbox_heights": heights or [40.0] * len(traj),
            "bbox_widths": widths or [30.0] * len(traj)}


def _walk_x(x0, x1, n=12, y=200.0):
    return [(x0 + (x1 - x0) * i / (n - 1), y) for i in range(n)]


@pytest.fixture
def machine_on(monkeypatch):
    monkeypatch.setattr(cfg, "JOURNEY_STATE_MACHINE", True)


class TestPipelineDispatch:
    def test_full_edge_crossing_is_evidence(self, machine_on):
        o, d, tag = _pipe()._gate_evidence(_vehicle(_walk_x(150.0, 300.0)))
        assert (o, tag) == (7, "entry_only")

    def test_straddle_refused(self, machine_on):
        # box 30 wide parked on the line: cx wobbles 199 <-> 201, so
        # the left corner (cx-15) and right corner (cx+15) never both
        # cross; the centre path alone would book a crossing.
        traj = [(199.0 if i % 20 < 10 else 201.0, 200.0) for i in range(200)]
        o, d, tag = _pipe()._gate_evidence(_vehicle(traj))
        assert tag in (None, "no_crossing")

    def test_tall_vehicle_illusion_still_refused(self, machine_on):
        # a horizontal gate at y=200 with the box passing in FRONT of
        # it: centre crosses, the bottom edge never does
        p = _pipe()
        p._entry_gates = {7: ((100.0, 200.0), (300.0, 200.0), (0.0, 1.0))}
        traj = [(200.0, 215.0 - 30.0 * i / 11) for i in range(12)]
        o, d, tag = p._gate_evidence(_vehicle(traj, heights=[60.0] * 12))
        assert tag in (None, "no_crossing")

    def test_missing_ledger_falls_back(self, machine_on):
        v = {"start_frame": 100, "trajectory": _walk_x(150.0, 300.0)}
        o, d, tag = _pipe()._gate_evidence(v)
        assert (o, tag) == (7, "entry_only")      # centre behaviour

    def test_flag_off_identical(self, monkeypatch):
        # with the machine off, _gate_evidence is today's code: for
        # the shipped combination and for bare defaults alike
        monkeypatch.setattr(cfg, "JOURNEY_STATE_MACHINE", False)
        trajs = [_walk_x(150.0, 300.0),
                 [(199.0 if i % 20 < 10 else 201.0, 200.0) for i in range(200)]]
        for anchor, either in ((False, False), (True, True)):
            monkeypatch.setattr(cfg, "GATE_GROUND_ANCHOR", anchor)
            monkeypatch.setattr(cfg, "GATE_EVIDENCE_EITHER_CORNER", either)
            for traj in trajs:
                v = _vehicle(traj)
                got = _pipe()._gate_evidence(v)
                pts = [(float(100 + i), float(x),
                        float(y) + (20.0 if anchor else 0.0))
                       for i, (x, y) in enumerate(traj)]
                if anchor:
                    l = [(f, x - 15.0, y) for f, x, y in pts]
                    r = [(f, x + 15.0, y) for f, x, y in pts]
                    cl, cr = (classify(l, _pipe()._entry_gates, 10.0),
                              classify(r, _pipe()._entry_gates, 10.0))
                    exp_o = cl[0] if cl[0] == cr[0] else (cl[0] or cr[0])
                    assert got[0] == exp_o
                else:
                    c = classify(pts, _pipe()._entry_gates, 10.0)
                    assert got == (c[0], c[1], c[6])
