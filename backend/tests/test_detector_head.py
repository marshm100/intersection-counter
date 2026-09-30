"""DETECTOR HEAD (config.DETECT_DEDUP_HEAD / DETECT_HALF, 2026-09-30, phase 4a):
the settings the detector passes to ultralytics, default off."""
import backend.config as cfg
from backend.services.detector import VehicleDetector


def _kw(device="cuda:0"):
    d = VehicleDetector.__new__(VehicleDetector)
    d._device = device
    return d._head_kwargs()


def test_default_off_passes_nothing():
    assert cfg.DETECT_DEDUP_HEAD is False and cfg.DETECT_HALF is False
    assert _kw() == {}


def test_dedup_head_and_half(monkeypatch):
    monkeypatch.setattr(cfg, "DETECT_DEDUP_HEAD", True)
    monkeypatch.setattr(cfg, "DETECT_HALF", True)
    assert _kw() == {"end2end": False, "agnostic_nms": True, "iou": 0.6, "half": True}
    assert "half" not in _kw("cpu")            # FP16 only on CUDA


def test_cache_meta_records_the_head(monkeypatch):
    import backend.services.two_pass as tp
    monkeypatch.setattr(cfg, "DETECT_DEDUP_HEAD", True)
    assert tp._detector_head_recipe()["dedup_head"] is True
