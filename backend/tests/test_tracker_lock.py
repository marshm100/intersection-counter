"""Stage 4 — the bus-law re-association gate (GatedBotSortBackend,
recipe "botsort_locked").

Operator identity law (2026-08-24): occlusion does NOT end identity —
INCOMPATIBLE MOTION does. Each test is one ruling made executable:
- a vehicle resuming on its own trajectory after occlusion is the SAME
  vehicle (generous buffer + gate lets it re-find);
- a parked vehicle reappears where it parked — a detection well away
  from the stop cannot claim its identity (the theft mask);
- a claim that only reveals itself as theft AFTERWARD (the box resumes
  moving the impossible way) breaks identity at the gap via probation —
  the splice-validated 120° flip signature;
- a queued car discharging forward after a long occlusion keeps its
  identity (approach bearing walked back through the dwell);
- short flicker gaps are untouched (grace).
"""
from __future__ import annotations

import pytest

from backend.services.tracker import create_tracker_backend

FPS = 25


def det(x, y, w=30.0, h=20.0, conf=0.9, cid=2):
    return {"bbox": [x - w / 2, y - h / 2, x + w / 2, y + h / 2],
            "confidence": conf, "class_id": cid}


def backend(name="botsort_locked", buffer=750):
    return create_tracker_backend(
        name, track_activation_threshold=0.25,
        minimum_matching_threshold=0.9, frame_rate=FPS,
        lost_track_buffer=buffer)


def run(be, frames):
    """frames: {frame: [det, ...]} sparse; every frame in range is stepped
    (empty updates included — the live cadence). Returns {frame: [ids]}."""
    out = {}
    for f in range(1, max(frames) + 1):
        res = be.update(frames.get(f, []), f)
        out[f] = [r["track_id"] for r in res]
    return out


def _eb_car(f):                      # eastbound 4 px/frame at y=300
    return det(100.0 + 4.0 * f, 300.0)


class TestBusLawGate:
    def test_on_trajectory_resume_keeps_id(self):
        frames = {f: [_eb_car(f)] for f in range(1, 51)}
        frames.update({f: [_eb_car(f)] for f in range(91, 101)})
        out = run(backend(), frames)
        tid = out[50][0]
        assert out[91] == [tid]            # 40-frame occlusion survived
        assert out[100] == [tid]

    def test_parked_truck_distant_claim_vetoed(self):
        """A large parked box: stock BoT-SORT re-activates onto an
        overlapping detection 80 px from the stop; the gate refuses
        (parked cars don't teleport) and a NEW vehicle is born."""
        parked = det(200.0, 300.0, w=120.0, h=60.0)
        claim = det(280.0, 300.0, w=120.0, h=60.0)
        frames = {f: [parked] for f in range(1, 51)}
        frames.update({f: [claim] for f in range(71, 76)})
        out_stock = run(backend("botsort"), frames)
        out_gated = run(backend(), frames)
        tid_stock = out_stock[50][0]
        tid_gated = out_gated[50][0]
        assert tid_stock in out_stock[71]          # stock: identity stolen
        assert tid_gated not in out_gated[75]      # gated: vetoed
        assert out_gated[75] and out_gated[75][0] != tid_gated

    def test_stopped_resume_at_stop_keeps_id(self):
        frames = {f: [det(100.0, 100.0 + 4.0 * f)] for f in range(1, 41)}
        frames.update({f: [det(100.0, 260.0)] for f in range(41, 81)})
        frames.update({f: [det(103.0, 260.0)] for f in range(281, 291)})
        out = run(backend(), frames)
        tid = out[80][0]
        assert out[281] == [tid]           # 200-frame (8 s) bus occlusion

    def test_probation_flip_breaks_identity(self):
        """The canonical theft: at re-acquisition the westbound thief sits
        exactly on the eastbound car's coasted box — positionally
        indistinguishable — then drives WEST. Probation judges the flip
        (>120°) and breaks identity at the gap."""
        frames = {f: [_eb_car(f)] for f in range(1, 51)}
        # thief appears at the coast position (x = 100+4f at f=75 -> 400)
        # and moves west 4 px/frame
        frames.update({f: [det(400.0 - 4.0 * (f - 75), 300.0)]
                       for f in range(75, 100)})
        out = run(backend(), frames)
        tid = out[50][0]
        assert out[75] == [tid]            # theft initially accepted...
        later = out[95]
        assert later and tid not in later  # ...then identity broken
        # and the break is stable: one fresh id carries on
        assert out[95] == out[99]

    def test_queue_discharge_passes_probation(self):
        """Southbound car dwells at the bar, gets occluded 100 frames, then
        discharges forward — approach bearing (walked back through the
        dwell) matches the discharge: SAME vehicle."""
        frames = {f: [det(100.0, 100.0 + 4.0 * f)] for f in range(1, 41)}
        frames.update({f: [det(100.0, 260.0)] for f in range(41, 61)})
        frames.update({f: [det(100.0, 262.0 + 3.0 * (f - 161))]
                       for f in range(161, 181)})
        out = run(backend(), frames)
        tid = out[60][0]
        assert out[161] == [tid]
        assert out[180] == [tid]           # discharge judged compatible

    def test_short_flicker_unaffected(self):
        frames = {f: [_eb_car(f)] for f in range(1, 51)}
        frames.update({f: [_eb_car(f)] for f in range(56, 66)})
        out = run(backend(), frames)
        assert out[56] == [out[50][0]]     # 5-frame gap: grace, no gate

    def test_deterministic(self):
        frames = {f: [_eb_car(f)] for f in range(1, 51)}
        frames.update({f: [det(400.0 - 4.0 * (f - 75), 300.0)]
                       for f in range(75, 100)})
        a = run(backend(), frames)
        b = run(backend(), frames)
        assert a == b
