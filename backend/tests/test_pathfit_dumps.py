"""Dumps-mode pathfit units (one-system pipeline, 2026-08-21 plan).

The W1a loss traced to 15-min sample thinness; dumps mode pools the
production pass-1 dumps instead. These tests pin the pure pieces: dump
track iteration (mmap + stable argsort ordering), the window overlap
rule, min-support resolution by source, the seeded reservoir with
uncapped support counts, and the kinematics fallback."""
import json
import random
import sys
from collections import defaultdict

import numpy as np
import pytest

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from run_pathfit_cli import (                                    # noqa: E402
    FALLBACK_KIN, MIN_SUPPORT_DUMPS, MIN_SUPPORT_NPZ,
    drop_containing_windows, iter_dump_tracks, kin_for, pool_full,
    resolve_min_support)


def _write_dump(tmp_path, rows):
    tdir = tmp_path / "study_0700.tracks"
    tdir.mkdir()
    arr = np.asarray(rows, dtype=np.float32)
    np.save(tdir / "rows.npy", arr)
    (tdir / "count.txt").write_text(str(len(rows)))
    (tdir / "meta.json").write_text(json.dumps({"format": 2}))
    return tdir


class TestIterDumpTracks:
    def test_interleaved_tids_come_out_frame_ordered(self, tmp_path):
        # two tracks interleaved in the dump (frame-major, as written by
        # pass 1) + one 3-point runt below MIN_SEG_PTS
        rows = []
        for f in range(10):
            rows.append((7, f, 100 + f, 50, 30, 30, 0.9, 2))
            rows.append((3, f, 200 - f, 80, 30, 30, 0.9, 2))
        for f in range(3):
            rows.append((9, f, 5, 5, 30, 30, 0.9, 2))
        tdir = _write_dump(tmp_path, rows)
        tracks = list(iter_dump_tracks(tdir))
        assert len(tracks) == 2
        by_first_x = sorted(tracks, key=lambda t: t[0][1])
        t7 = by_first_x[0]
        assert [p[0] for p in t7] == list(range(10))
        assert t7[0][1:] == (100.0, 50.0)
        assert t7[-1][1:] == (109.0, 50.0)
        t3 = by_first_x[1]
        assert [p[0] for p in t3] == list(range(10))
        assert t3[0][1:] == (200.0, 80.0)

    def test_empty_dump_yields_nothing(self, tmp_path):
        tdir = _write_dump(tmp_path, np.zeros((0, 8), dtype=np.float32))
        assert list(iter_dump_tracks(tdir)) == []


class TestWindowRules:
    def test_containing_window_dropped(self):
        w_big = {"variant": "study_0000", "start_frame": -20,
                 "end_frame": 863980}
        w_small = {"variant": "study_0600", "start_frame": 215980,
                   "end_frame": 719980}
        kept, dropped = drop_containing_windows([w_big, w_small])
        assert kept == [w_small]
        assert dropped == [w_big]

    def test_disjoint_windows_all_kept(self):
        ws = [{"variant": "study_0700", "start_frame": 0, "end_frame": 100},
              {"variant": "study_1600", "start_frame": 200,
               "end_frame": 300}]
        kept, dropped = drop_containing_windows(ws)
        assert kept == ws and dropped == []

    def test_min_support_resolution(self):
        assert resolve_min_support(True, None) == MIN_SUPPORT_DUMPS == 8
        assert resolve_min_support(False, None) == MIN_SUPPORT_NPZ == 5
        assert resolve_min_support(True, 3) == 3
        assert resolve_min_support(False, 11) == 11


class TestReservoirPooling:
    def test_counts_uncapped_storage_capped_and_deterministic(self):
        fulls, counts = defaultdict(list), defaultdict(int)
        rng = random.Random(42)
        for i in range(50):
            pool_full(fulls, counts, (1, 2), f"seg{i}", 10, rng)
        assert counts[(1, 2)] == 50
        assert len(fulls[(1, 2)]) == 10
        fulls2, counts2 = defaultdict(list), defaultdict(int)
        rng2 = random.Random(42)
        for i in range(50):
            pool_full(fulls2, counts2, (1, 2), f"seg{i}", 10, rng2)
        assert fulls[(1, 2)] == fulls2[(1, 2)]

    def test_two_windows_cross_min_support_only_pooled(self):
        # 5 fulls in each of two windows: neither alone reaches the dumps
        # floor (8); pooled they do — the W1a thin-cell fix in miniature
        fulls, counts = defaultdict(list), defaultdict(int)
        rng = random.Random(42)
        for _w in range(2):
            for i in range(5):
                pool_full(fulls, counts, (3, 4), (i,), 500, rng)
        assert counts[(3, 4)] == 10 >= MIN_SUPPORT_DUMPS
        assert 5 < MIN_SUPPORT_DUMPS


class TestKinFallback:
    def test_missing_tracklets_falls_back(self):
        kin, src = kin_for(99, "study_9999", None)
        assert src == "fallback-defaults"
        assert kin == FALLBACK_KIN
        assert kin is not FALLBACK_KIN  # caller gets a copy
