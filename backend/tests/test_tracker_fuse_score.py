"""TRACKER_FUSE_SCORE (2026-09-12): the supervision ByteTrack score fusion is
switchable; default ON (shipped behaviour)."""
import numpy as np

from backend import config
from backend.services import tracker as T


def test_default_on():
    assert config.TRACKER_FUSE_SCORE is True


def test_apply_setting_round_trip():
    from supervision.tracker.byte_tracker import matching as m

    class _D:
        def __init__(self, s):
            self.score = s

    cost = np.array([[0.5, 0.75]])
    dets = [_D(0.5), _D(1.0)]
    T.apply_fuse_score_setting(True)
    fused = m.fuse_score(cost.copy(), dets)
    assert np.allclose(fused, [[0.75, 0.75]])       # 1 - (0.5*0.5), 1 - (0.25*1.0)
    T.apply_fuse_score_setting(False)
    assert np.allclose(m.fuse_score(cost.copy(), dets), cost)
    T.apply_fuse_score_setting(True)
    assert np.allclose(m.fuse_score(cost.copy(), dets), fused)


def test_backend_records_setting():
    be = T.ByteTrackBackend()
    assert be.fuse_score is True
