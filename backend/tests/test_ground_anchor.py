"""The threshold law (operator ruling 2026-09-07) — ground-anchored
gate crossings. A gate is a threshold on the ground: only the bbox
BOTTOM crossing the line counts; a tall vehicle passing in front of
a background line never does."""
import pytest

import backend.config as cfg
import backend.services.pipeline as pl
from backend.services.pipeline import ProcessingPipeline


def _pipe():
    p = ProcessingPipeline.__new__(ProcessingPipeline)
    # one horizontal gate line at y=200, inward normal pointing down
    # (into the intersection below the line)
    p._entry_gates = {7: ((100.0, 200.0), (300.0, 200.0), (0.0, 1.0))}
    p.fps = 25.0
    return p


def _vehicle(traj, heights, widths=None):
    return {"start_frame": 100, "trajectory": traj,
            "bbox_heights": heights,
            "bbox_widths": widths or [30.0] * len(traj)}


def _walk(y0, y1, n=12):
    return [(200.0, y0 + (y1 - y0) * i / (n - 1)) for i in range(n)]


class TestThresholdLaw:
    def test_tall_vehicle_in_front_not_crossing(self, monkeypatch):
        # center drifts from y=215 to y=185 (crosses the line at 200)
        # but the box is 60 tall: bottom goes 245 -> 215, never
        # crossing. Flag off books the crossing; flag on refuses it.
        traj = _walk(215.0, 185.0)
        v = _vehicle(traj, [60.0] * len(traj))
        monkeypatch.setattr(cfg, "GATE_GROUND_ANCHOR", False)
        o_off, d_off, tag_off = _pipe()._gate_evidence(v)
        monkeypatch.setattr(cfg, "GATE_GROUND_ANCHOR", True)
        o_on, d_on, tag_on = _pipe()._gate_evidence(v)
        assert tag_off != "no_crossing"       # the phantom mechanism
        assert (o_on, d_on, tag_on)[2] in (None, "no_crossing")

    def test_real_crossing_counted_under_both(self, monkeypatch):
        # bottom passes over the line: center 250 -> 130 with a 40
        # box => bottom 270 -> 150, genuinely crossing 200
        traj = _walk(250.0, 130.0)
        v = _vehicle(traj, [40.0] * len(traj))
        for flag in (False, True):
            monkeypatch.setattr(cfg, "GATE_GROUND_ANCHOR", flag)
            _o, _d, tag = _pipe()._gate_evidence(v)
            assert tag != "no_crossing", f"flag={flag}"

    def test_missing_heights_falls_back_to_centers(self, monkeypatch):
        monkeypatch.setattr(cfg, "GATE_GROUND_ANCHOR", True)
        traj = _walk(215.0, 185.0)
        v = {"start_frame": 100, "trajectory": traj}   # no ledger
        _o, _d, tag = _pipe()._gate_evidence(v)
        assert tag != "no_crossing"           # center behavior preserved

    def test_short_ledger_falls_back(self, monkeypatch):
        monkeypatch.setattr(cfg, "GATE_GROUND_ANCHOR", True)
        traj = _walk(215.0, 185.0)
        v = _vehicle(traj, [60.0] * 3)        # misaligned ledger
        _o, _d, tag = _pipe()._gate_evidence(v)
        assert tag != "no_crossing"

    def test_one_corner_touch_not_a_crossing(self, monkeypatch):
        # operator refinement: the ENTIRE bottom edge must cross.
        # Gate spans x 100-300 at y=200; the vehicle drives with its
        # bottom at y 230 -> 170 but positioned so only its LEFT
        # corner sweeps the gate's span (cx=310, w=40: corners at 290
        # and 330 — the right corner passes beyond the gate's end).
        traj = [(310.0, 230.0 - 60.0 * i / 11 - 20.0) for i in range(12)]
        v = _vehicle(traj, [40.0] * 12, [40.0] * 12)
        monkeypatch.setattr(cfg, "GATE_GROUND_ANCHOR", True)
        _o, _d, tag = _pipe()._gate_evidence(v)
        assert tag in (None, "no_crossing")

    def test_full_bottom_edge_crossing_counts(self, monkeypatch):
        # both corners within the gate span and both cross -> counts
        traj = _walk(250.0, 130.0)            # cx=200, gate span 100-300
        v = _vehicle(traj, [40.0] * len(traj), [60.0] * len(traj))
        monkeypatch.setattr(cfg, "GATE_GROUND_ANCHOR", True)
        _o, _d, tag = _pipe()._gate_evidence(v)
        assert tag != "no_crossing"


class TestEitherCorner:
    """G-EX-1: gate EVIDENCE accepts a witness from either bottom
    corner; ground anchoring still kills the tall-vehicle illusion."""

    def _wide(self, traj, heights, widths):
        return {"start_frame": 100, "trajectory": traj,
                "bbox_heights": heights, "bbox_widths": widths}

    def test_illusion_still_refused_with_either_corner(self, monkeypatch):
        # THE GUARANTEE: a tall vehicle passing in FRONT of a
        # background line. Centre crosses y=200; the whole bottom
        # edge stays below it, so NEITHER corner crosses — relaxing
        # to either-corner must not resurrect the phantom.
        monkeypatch.setattr(cfg, "GATE_GROUND_ANCHOR", True)
        monkeypatch.setattr(cfg, "GATE_EVIDENCE_EITHER_CORNER", True)
        traj = _walk(215.0, 185.0)
        v = self._wide(traj, [60.0] * len(traj), [30.0] * len(traj))
        _o, _d, tag = _pipe()._gate_evidence(v)
        assert tag in (None, "no_crossing")

    def test_one_corner_witness_accepted(self, monkeypatch):
        # the gate spans x 100-300 at y=200. A box at cx=290 w=40 has
        # its left corner at 270 (over the gate) and its right at 310
        # (past the gate's end). Bottom edge sweeps 230 -> 170.
        monkeypatch.setattr(cfg, "GATE_GROUND_ANCHOR", True)
        traj = [(290.0, 210.0 - 60.0 * i / 11) for i in range(12)]
        v = self._wide(traj, [40.0] * 12, [40.0] * 12)
        monkeypatch.setattr(cfg, "GATE_EVIDENCE_EITHER_CORNER", False)
        _o, _d, strict = _pipe()._gate_evidence(v)
        monkeypatch.setattr(cfg, "GATE_EVIDENCE_EITHER_CORNER", True)
        _o2, _d2, relaxed = _pipe()._gate_evidence(v)
        assert strict in (None, "no_crossing")
        assert relaxed not in (None, "no_crossing")

    def test_flag_off_identical(self, monkeypatch):
        monkeypatch.setattr(cfg, "GATE_GROUND_ANCHOR", True)
        monkeypatch.setattr(cfg, "GATE_EVIDENCE_EITHER_CORNER", False)
        traj = _walk(250.0, 130.0)
        v = self._wide(traj, [40.0] * len(traj), [60.0] * len(traj))
        _o, _d, tag = _pipe()._gate_evidence(v)
        assert tag != "no_crossing"        # a real full-edge crossing
