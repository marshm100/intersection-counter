"""FRAME-RATE AWARENESS (config.FPS_AWARE, 2026-09-29): per-frame constants
validated at 10 fps are converted to the video's own frame rate, identity at
10 fps."""
import backend.config as cfg
from backend.services.turn_merge import merge_turn_fragments


def _ev(i, s, e, start=(100.0, 100.0)):
    return {"id": i, "ol": 1, "dl": 2, "mv": "left", "s": s, "e": e, "start": start}


def test_default_off_and_identity(monkeypatch):
    assert cfg.FPS_AWARE is False
    assert cfg.fps_frames(60, 25.0) == 60             # off: unchanged
    monkeypatch.setattr(cfg, "FPS_AWARE", True)
    assert cfg.fps_frames(60, 10.0) == 60             # 10 fps: identity
    assert cfg.fps_frames(40, 10.0) == 40


def test_frame_counts_keep_their_real_time(monkeypatch):
    monkeypatch.setattr(cfg, "FPS_AWARE", True)
    assert cfg.fps_frames(60, 25.0) == 150            # 6 s at 25 fps
    assert cfg.fps_frames(40, 30.0) == 120            # 4 s at 30 fps
    assert cfg.fps_frames(12, 25.0) == 30             # 1.2 s at 25 fps


def test_tracker_velocity_noise_scales_per_step(monkeypatch):
    from backend.services.tracker import ByteTrackBackend
    base = cfg.TRACKER_KF_VEL_STD
    monkeypatch.setattr(cfg, "FPS_AWARE", True)
    monkeypatch.setattr(cfg, "FPS_KF_POWER", 1.0)
    assert abs(ByteTrackBackend(frame_rate=10)._recovery_kwargs["kf_vel_std"] - base) < 1e-12
    assert abs(ByteTrackBackend(frame_rate=25)._recovery_kwargs["kf_vel_std"] - base * 0.4) < 1e-12
    monkeypatch.setattr(cfg, "FPS_KF_POWER", 2.0)
    assert abs(ByteTrackBackend(frame_rate=25)._recovery_kwargs["kf_vel_std"] - base * 0.16) < 1e-12
    monkeypatch.setattr(cfg, "FPS_AWARE", False)
    assert ByteTrackBackend(frame_rate=25)._recovery_kwargs["kf_vel_std"] == base


def test_merge_overlap_limit_is_a_parameter():
    # two coexisting same-cell turns: 20 frames of overlap
    turns = [_ev(1, 0, 50), _ev(2, 30, 80)]
    exp = {(1, 2): 1}
    kept12 = merge_turn_fragments(turns, 30.0, 40.0, expected_by_cell=exp,
                                  queue_aware=True, max_overlap=12)
    kept30 = merge_turn_fragments(turns, 30.0, 40.0, expected_by_cell=exp,
                                  queue_aware=True, max_overlap=30)
    assert kept12 == {1, 2} and kept30 == {1}
