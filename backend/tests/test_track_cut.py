"""Track Repair Stage 0/1 — the service port + the dump-level transform.

cut_track/pinch_cuts behavior is pinned by test_a3_split.py (unchanged).
Here: cut_dump_rows — determinism, tid renumbering, uncut passthrough,
float32 exactness, and the no-wrong-units-fallback policy.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.services.track_cut import (
    FALLBACK_KIN, MIN_SEG_PTS, cut_dump_rows, cut_track,
)

# One horizontal gate the track crosses outward, then (spliced) re-approaches.
# gates: {leg: (p1, p2, inward_normal)} — inward normal points +y (down).
GATES = {29: ((0.0, 100.0), (200.0, 100.0), (0.0, 1.0))}
FPS = 25.0


def _rows(tracks):
    """{tid: [(frame, x, y), ...]} -> dump rows [N,8] float32."""
    out = []
    for tid, pts in tracks.items():
        for f, x, y in pts:
            out.append([tid, f, x, y, 20.0, 12.0, 0.9, 2.0])
    return np.array(out, dtype=np.float32)


def _spliced_track():
    """Crosses the gate outbound at ~frame 50, then a latch teleport back
    inside and a long second life — the Type-1 geometry-cut shape."""
    a = [(float(f), 100.0, 150.0 - 2.0 * f) for f in range(0, 51)]      # exits y<100 ~f25
    b = [(float(f), 100.0 + (f - 90) * 1.5, 140.0) for f in range(90, 140)]
    return a + b


def _clean_track():
    """Never crosses the gate; smooth; nothing to cut."""
    return [(float(f), 50.0 + f, 200.0) for f in range(0, 40)]


class TestCutDumpRows:
    def test_uncut_tracks_pass_through_verbatim(self):
        rows = _rows({7: _clean_track()})
        out, stats = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        assert stats["cut_tracks"] == 0
        assert np.array_equal(np.sort(out, axis=0), np.sort(rows, axis=0))
        assert out.dtype == np.float32

    def test_spliced_track_is_segmented_and_renumbered(self):
        rows = _rows({7: _spliced_track()})
        out, stats = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        assert stats["cut_tracks"] == 1
        tids = sorted(set(out[:, 0].tolist()))
        assert tids == [1000070.0, 1000071.0]   # CUT_SEG_BASE + tid*10 + k
        # each segment respects MIN_SEG_PTS
        for t in tids:
            assert (out[:, 0] == t).sum() >= MIN_SEG_PTS
        # segment 0 ends before segment 1 begins (cut extends in time)
        f0 = out[out[:, 0] == 1000070.0][:, 1].max()
        f1 = out[out[:, 0] == 1000071.0][:, 1].min()
        assert f0 < f1

    def test_deterministic(self):
        rows = _rows({7: _spliced_track(), 9: _clean_track()})
        a, _ = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        b, _ = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        assert np.array_equal(a, b)

    def test_mixed_dump_keeps_clean_tids(self):
        rows = _rows({7: _spliced_track(), 9: _clean_track()})
        out, stats = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        tids = set(out[:, 0].tolist())
        assert 9.0 in tids                    # clean tid untouched
        assert 7.0 not in tids                # spliced tid replaced by segments
        assert {1000070.0, 1000071.0} <= tids

    def test_float32_tid_exactness(self):
        big = 200000                          # realistic upper tid range
        pts = _spliced_track()
        rows = _rows({big: pts})
        out, _ = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        tids = sorted(set(out[:, 0].tolist()))
        assert tids == [1_000_000.0 + big * 10,
                        1_000_000.0 + big * 10 + 1]  # exact in float32


class TestKinPolicy:
    def test_fallback_kin_units_are_px_per_second(self):
        # the wrong-units fallback (0.8/0.5) must not exist anywhere reachable
        assert FALLBACK_KIN["v_stop"] == 8.0
        assert FALLBACK_KIN["a_allow"] == 12.0

    def test_cut_track_smooth_turner_uncut_under_fallback(self):
        """A smooth 90-degree turner (the false-cut class the pinch gate must
        not fire on) stays whole under the correct-units fallback."""
        pts = []
        for f in range(0, 30):                # southbound approach
            pts.append((float(f), 100.0, 300.0 - 4.0 * f))
        for k in range(1, 31):                # gentle arc to eastbound
            ang = (k / 30.0) * (np.pi / 2)
            pts.append((float(30 + k), 100.0 + 60.0 * np.sin(ang),
                        180.0 - 60.0 * (1 - np.cos(ang))))
        segments, records = cut_track(pts, {}, FPS, dict(FALLBACK_KIN))
        assert records == []
        assert len(segments) == 1 and len(segments[0]) == len(pts)


# ---------------------------------------------------------------------------
# Stage 1 — ensure_cut_dump (derived-dump resolution)
# ---------------------------------------------------------------------------

import json
import sqlite3

import pytest as _pytest

from backend.services.track_cut import ensure_cut_dump


@_pytest.fixture
def cutenv(tmp_path, monkeypatch):
    """A minimal project with one camera, drawn gates, and a base dump."""
    import backend.config as cfg
    import backend.database as dbm
    proj_root = tmp_path / "projects"
    (proj_root / "p1").mkdir(parents=True)
    monkeypatch.setattr(cfg, "PROJECTS_DIR", proj_root)
    monkeypatch.setattr(dbm, "PROJECTS_DIR", proj_root)
    db = proj_root / "p1" / "project.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(dbm.SCHEMA)
    conn.execute("INSERT INTO intersections (intersection_id, name, date, sort_order, leg_count, created_at) "
                 "VALUES (1, 'T', '2026-05-12', 0, 2, '2026-05-12')")
    conn.execute("INSERT INTO cameras (camera_id, intersection_id, label, sort_order, created_at) "
                 "VALUES (2, 1, 'c', 0, '2026-05-12')")
    for lid, gs in ((28, [[0, 100], [200, 100]]), (29, [[0, 300], [200, 300]])):
        conn.execute("INSERT INTO legs (leg_id, camera_id, label, cardinal_direction, sort_order, "
                     "origin_zone, reference_heading, gate_segment) VALUES (?, 2, 'L', 'N', 0, ?, 90.0, ?)",
                     (lid, json.dumps([[100, 100 if lid == 28 else 300]]), json.dumps(gs)))
    conn.commit(); conn.close()

    base = tmp_path / "study_0700.tracks"
    base.mkdir()
    rows = _rows({7: _spliced_track(), 9: _clean_track()})
    np.save(base / "rows.npy", rows)
    (base / "count.txt").write_text(str(len(rows)))
    (base / "meta.json").write_text(json.dumps(
        {"frames": [0, 200], "variant": "study_0700", "complete": True}))
    return {"tdir": base, "rows": rows, "proj": "p1"}


class TestEnsureCutDump:
    def test_builds_reuses_and_repins(self, cutenv):
        v2, tdir2, meta2, rows2 = ensure_cut_dump(
            cutenv["proj"], 2, "study_0700", "hash", 25.0,
            cutenv["tdir"], cutenv["rows"], json.loads((cutenv["tdir"] / "meta.json").read_text()))
        assert v2 == "a3_study_0700"
        assert tdir2.name == "a3_study_0700.tracks"
        assert meta2["a3_cut"]["base_rows"] == len(cutenv["rows"])
        assert (tdir2 / "count.txt").exists()
        stamp = (tdir2 / "rows.npy").stat().st_mtime_ns

        # second call: reused, not rebuilt
        v3, tdir3, meta3, rows3 = ensure_cut_dump(
            cutenv["proj"], 2, "study_0700", "hash", 25.0,
            cutenv["tdir"], cutenv["rows"], json.loads((cutenv["tdir"] / "meta.json").read_text()))
        assert (tdir3 / "rows.npy").stat().st_mtime_ns == stamp
        assert np.array_equal(rows2, rows3)

        # geometry change (gate redraw) forces a rebuild
        import backend.config as cfg
        conn = sqlite3.connect(str(cfg.PROJECTS_DIR / "p1" / "project.db"))
        conn.execute("UPDATE legs SET gate_segment=? WHERE leg_id=29",
                     (json.dumps([[0, 310], [200, 310]]),))
        conn.commit(); conn.close()
        v4, tdir4, meta4, rows4 = ensure_cut_dump(
            cutenv["proj"], 2, "study_0700", "hash", 25.0,
            cutenv["tdir"], cutenv["rows"], json.loads((cutenv["tdir"] / "meta.json").read_text()))
        assert (tdir4 / "rows.npy").stat().st_mtime_ns != stamp

    def test_base_dump_untouched(self, cutenv):
        before = (cutenv["tdir"] / "rows.npy").read_bytes()
        ensure_cut_dump(cutenv["proj"], 2, "study_0700", "hash", 25.0,
                        cutenv["tdir"], cutenv["rows"],
                        json.loads((cutenv["tdir"] / "meta.json").read_text()))
        assert (cutenv["tdir"] / "rows.npy").read_bytes() == before


# ---------------------------------------------------------------------------
# Stage 1a — the graze amendment (operator identity law, 2026-08-24)
# ---------------------------------------------------------------------------

# Two horizontal gates: 28 at y=100 (the grazed line), 29 at y=300 (real
# exit for a southbound through). Inward normals point at the box interior
# between them (28's +y, 29's -y). Entry gate 27 at y=20 (+y inward).
GATES3 = {
    27: ((0.0, 20.0), (200.0, 20.0), (0.0, 1.0)),
    28: ((0.0, 100.0), (200.0, 100.0), (0.0, -1.0)),
    29: ((0.0, 300.0), (200.0, 300.0), (0.0, -1.0)),
}


def _sb_through_graze():
    """IN:27 -> graze OUT:28 -> real OUT:29, smooth throughout."""
    return [(float(f), 100.0, 4.0 * f) for f in range(0, 90)]  # y 0..356


def _real_exit_then_thief():
    """IN:27 -> OUT:29 (real, smooth) then a teleport latch and a long
    opposite ride — the 14859 class."""
    a = [(float(f), 100.0, 4.0 * f) for f in range(0, 80)]      # exits y=300 ~f75
    b = [(float(f), 140.0, 320.0 - 3.0 * (f - 120)) for f in range(120, 180)]
    return a + b


class TestGrazeAmendment:
    def test_smooth_graze_is_skipped_cut_at_real_exit(self):
        segments, records = cut_track(_sb_through_graze(), GATES3, FPS,
                                      dict(FALLBACK_KIN))
        geo = [r for r in records if r[1].get("rule") == "geometry"]
        assert len(geo) == 1
        # cut at the FINAL crossing (29 at y=300 ~ frame 75), not the graze (28 ~ f25)
        assert geo[0][0] > 60 * 1.0
        # segment 1 retains the full journey: crosses 27 in, 28 graze, 29 out
        from backend.services.entry_gates import classify
        o, d, *_r, tag = classify(segments[0], GATES3, FPS)
        assert (o, d, tag) == (27, 29, "full")

    def test_thief_after_real_exit_cut_at_the_theft(self):
        pts = _real_exit_then_thief()
        segments, records = cut_track(pts, GATES3, FPS, dict(FALLBACK_KIN))
        geo = [r for r in records if r[1].get("rule") == "geometry"]
        assert len(geo) == 1
        # the discontinuity follows the ~f75 exit -> cut there (+1s margin)
        assert 70 <= geo[0][0] <= 110
        from backend.services.entry_gates import classify
        o, d, *_r, tag = classify(segments[0], GATES3, FPS)
        assert (o, d) == (27, 29) and tag == "full"
        assert len(segments) >= 2          # the thief survives as its own track

    def test_tail_discontinuity_does_not_cut_at_graze(self):
        """A teleport AFTER the final crossing must not implicate the graze
        (span bounding): the geometry cut stays at the final crossing."""
        pts = _sb_through_graze()
        # teleport tail beyond the final crossing
        pts += [(float(f), 400.0, 380.0) for f in range(150, 160)]
        segments, records = cut_track(pts, GATES3, FPS, dict(FALLBACK_KIN))
        geo = [r for r in records if r[1].get("rule") == "geometry"]
        assert len(geo) == 1
        assert geo[0][0] > 60          # at the y=300 crossing, not the graze
        from backend.services.entry_gates import classify
        o, d, *_r, tag = classify(segments[0], GATES3, FPS)
        assert (o, d, tag) == (27, 29, "full")

    def test_single_exit_tail_trim_unchanged(self):
        """Simple track with one exit and a short smooth tail: cut at the
        exit + margin — identical to pre-amendment behavior."""
        pts = [(float(f), 100.0, 4.0 * f) for f in range(0, 100)]  # one entry 27? crosses 27,28,29
        # use a single-gate world to isolate: entry-free single outbound
        one = {29: ((0.0, 300.0), (200.0, 300.0), (0.0, -1.0))}
        segments, records = cut_track(pts, one, FPS, dict(FALLBACK_KIN))
        geo = [r for r in records if r[1].get("rule") == "geometry"]
        assert len(geo) == 1
        assert abs(geo[0][0] - (75 + 25)) <= 3     # crossing ~f75 + 1s margin


# ---------------------------------------------------------------------------
# Stage 2 — direction gate + chain glue (operator identity law, 2026-08-24)
# ---------------------------------------------------------------------------

from backend.config import TRACK_FINALIZE_GAP_FRAMES
from backend.services.track_cut import CUT_SEG_BASE, glue_chained_fragments
from backend.services.track_chains import (
    STITCH_STAT_DIST, _end_speed, chain_tracks, endpoint_bearings,
)


def _rec(tid, pts, tag):
    """A chain_tracks rec built exactly the way glue builds them."""
    bs, be = endpoint_bearings(pts, FPS)
    return {"tid": tid, "birth": (pts[0][0], pts[0][1], pts[0][2]),
            "death": (pts[-1][0], pts[-1][1], pts[-1][2]),
            "tag": tag, "v_end": _end_speed(pts),
            "b_start": bs, "b_end": be}


def _east(tid_f0, n, x0, y=300.0, v=4.0):
    f0 = float(tid_f0)
    return [(f0 + i, x0 + v * i, y) for i in range(n)]


class TestDirectionGate:
    def test_opposite_direction_moving_pair_vetoed(self):
        a = _east(0, 51, 10.0)                       # dies (210,300) moving E
        b = [(52.0 + i, 215.0 - 4.0 * i, 300.0) for i in range(50)]  # moving W
        stats = {}
        chains = chain_tracks([_rec(1, a, "entry_only"),
                               _rec(2, b, "exit_only")], FPS, stats=stats)
        assert all(len(c) == 1 for c in chains)
        assert stats["direction_rejections"] >= 1

    def test_same_direction_chains(self):
        a = _east(0, 51, 10.0)
        b = _east(52, 50, 215.0)
        chains = chain_tracks([_rec(1, a, "entry_only"),
                               _rec(2, b, "exit_only")], FPS)
        assert any(len(c) == 2 for c in chains)

    def test_stop_side_waiver(self):
        """A ends stationary (queue dwell has no direction) — even a 90°
        discharge (a turner) chains under the frozen stationary rule."""
        a = ([(float(f), 100.0, 100.0 + 2.0 * f) for f in range(0, 50)]
             + [(float(f), 100.0, 198.0) for f in range(50, 120)])  # SB, stops
        b = [(500.0 + i, 105.0 + 4.0 * i, 200.0) for i in range(50)]  # E out
        ra, rb = _rec(1, a, "entry_only"), _rec(2, b, "exit_only")
        assert ra["b_end"] is None            # dwelling endpoint: no bearing
        chains = chain_tracks([ra, rb], FPS)
        assert any(len(c) == 2 for c in chains)

    def test_recs_without_bearing_keys_waived(self):
        """Older callers build recs without bearing keys — untouched."""
        a = _east(0, 51, 10.0)
        b = [(52.0 + i, 215.0 - 4.0 * i, 300.0) for i in range(50)]
        recs = []
        for tid, pts, tag in ((1, a, "entry_only"), (2, b, "exit_only")):
            recs.append({"tid": tid,
                         "birth": (pts[0][0], pts[0][1], pts[0][2]),
                         "death": (pts[-1][0], pts[-1][1], pts[-1][2]),
                         "tag": tag, "v_end": _end_speed(pts)})
        chains = chain_tracks(recs, FPS)
        assert any(len(c) == 2 for c in chains)   # veto waived, rule holds

    def test_endpoint_bearings_shapes(self):
        moving = _east(0, 50, 10.0)
        bs, be = endpoint_bearings(moving, FPS)
        assert bs is not None and be is not None
        stopped_end = ([(float(f), 100.0, 100.0 + 2.0 * f) for f in range(50)]
                       + [(float(f), 100.0, 198.0) for f in range(50, 120)])
        bs2, be2 = endpoint_bearings(stopped_end, FPS)
        assert bs2 is not None and be2 is None
        jitter = [(float(f), 100.0 + (f % 2), 200.0) for f in range(40)]
        assert endpoint_bearings(jitter, FPS) == (None, None)


class TestChainGlue:
    def _stop_gap_rows(self):
        # A (tid 7): SB, then parked 2 s at (100,200); B (tid 9): resumes
        # 30 s later 5 px away — the frozen stationary rule's shape.
        a = ([(float(f), 100.0, 50.0 + 2.0 * f) for f in range(0, 76)]
             + [(float(f), 100.0, 200.0) for f in range(76, 126)])
        b = [(875.0 + i, 105.0, 200.0 + 2.0 * i) for i in range(60)]
        return _rows({7: a, 9: b})

    def test_stop_gap_family_glued_and_bridged(self):
        out, stats = glue_chained_fragments(self._stop_gap_rows(), {}, FPS)
        assert stats["chains_glued"] == 1 and stats["glued_members"] == 2
        tids = set(out[:, 0].tolist())
        assert tids == {7.0}                       # composite = min(members)
        fr = np.sort(out[out[:, 0] == 7.0][:, 1])
        assert np.all(np.diff(fr) == 1.0)          # one row per frame
        assert np.diff(fr).max(initial=1.0) <= TRACK_FINALIZE_GAP_FRAMES
        assert len(np.unique(fr)) == len(fr)       # unique (tid, frame)
        # bridge rows: linear ~ hold within the stationary rule's distance
        bridge = out[(out[:, 1] > 125) & (out[:, 1] < 875)]
        assert len(bridge) == stats["bridged_rows"] == 749
        d = np.hypot(bridge[:, 2] - 100.0, bridge[:, 3] - 200.0)
        assert d.max() <= STITCH_STAT_DIST
        assert np.all(bridge[:, 7] == 2.0)         # no truck votes
        assert np.all(bridge[:, 4] <= 20.0) and np.all(bridge[:, 5] <= 12.0)
        assert np.all((bridge[:, 6] > 0.0) & (bridge[:, 6] <= 0.9))

    def test_overlap_dedupe(self):
        # B born 5 frames BEFORE A dies (the negative-gap move rule)
        a = _east(0, 51, 10.0)                     # dies f50 at (210,300)
        b = [(45.0 + i, 205.0 + 4.0 * i, 300.0) for i in range(56)]
        out, stats = glue_chained_fragments(_rows({3: a, 5: b}), {}, FPS)
        assert stats["chains_glued"] == 1
        assert stats["overlap_dropped_rows"] == 6  # B frames 45..50 dropped
        fr = np.sort(out[out[:, 0] == 3.0][:, 1])
        assert np.all(np.diff(fr) == 1.0)
        assert len(np.unique(fr)) == len(fr)

    def test_direction_veto_end_to_end(self):
        a = _east(0, 51, 10.0)
        b = [(52.0 + i, 215.0 - 4.0 * i, 300.0) for i in range(50)]
        out, stats = glue_chained_fragments(_rows({11: a, 13: b}), {}, FPS)
        assert stats["chains_glued"] == 0
        assert stats["direction_rejections"] >= 1
        assert set(out[:, 0].tolist()) == {11.0, 13.0}

    def test_full_journey_never_glues(self):
        full = _sb_through_graze()                 # 27 -> 29, tag full
        tail = [(92.0 + i, 100.0, 360.0 + 4.0 * i) for i in range(30)]
        out, stats = glue_chained_fragments(_rows({7: full, 8: tail}),
                                            GATES3, FPS)
        assert stats["chains_glued"] == 0
        assert {7.0, 8.0} <= set(out[:, 0].tolist())

    def test_deterministic(self):
        rows = self._stop_gap_rows()
        a, _ = glue_chained_fragments(rows, {}, FPS)
        b, _ = glue_chained_fragments(rows, {}, FPS)
        assert np.array_equal(a, b)


class TestCollisionFix:
    def test_cut_segments_disjoint_from_uncut_tids(self):
        """Pre-fix, track 1's segments became tids 10 and 11 — colliding
        with the real uncut track 10 and silently merging two vehicles."""
        rows = _rows({1: _spliced_track(), 10: _clean_track()})
        out, stats = cut_dump_rows(rows, GATES, FPS, dict(FALLBACK_KIN))
        assert stats["cut_tracks"] == 1
        tids = set(out[:, 0].tolist())
        assert tids == {10.0, CUT_SEG_BASE + 10.0, CUT_SEG_BASE + 11.0}
        # the clean vehicle's rows are exactly its own
        assert (out[:, 0] == 10.0).sum() == len(_clean_track())


class TestEnsureCutDumpGlue:
    def test_glue_recorded_and_flag_repins(self, cutenv, monkeypatch):
        import backend.config as cfg
        m0 = json.loads((cutenv["tdir"] / "meta.json").read_text())
        monkeypatch.setattr(cfg, "CHAIN_GLUE", True)
        _v, tdir, meta, _r = ensure_cut_dump(
            cutenv["proj"], 2, "study_0700", "hash", 25.0,
            cutenv["tdir"], cutenv["rows"], m0)
        assert meta["a3_cut"]["glue"]["enabled"] is True
        assert "families" in meta["a3_cut"]["glue"]
        stamp = (tdir / "rows.npy").stat().st_mtime_ns
        # flipping the flag invalidates reuse (rule-state is part of the key)
        monkeypatch.setattr(cfg, "CHAIN_GLUE", False)
        _v2, tdir2, meta2, _r2 = ensure_cut_dump(
            cutenv["proj"], 2, "study_0700", "hash", 25.0,
            cutenv["tdir"], cutenv["rows"], m0)
        assert (tdir2 / "rows.npy").stat().st_mtime_ns != stamp
        assert meta2["a3_cut"]["glue"] == {"enabled": False}

    def test_default_off_records_disabled(self, cutenv):
        """CHAIN_GLUE defaults OFF (Demo-2 negative): the repair is
        cut-only and the meta says so."""
        m0 = json.loads((cutenv["tdir"] / "meta.json").read_text())
        _v, _t, meta, _r = ensure_cut_dump(
            cutenv["proj"], 2, "study_0700", "hash", 25.0,
            cutenv["tdir"], cutenv["rows"], m0)
        assert meta["a3_cut"]["glue"] == {"enabled": False}
