"""ATR crossing counter — the pure dedup core."""
from backend.services.atr_counts import dedup_crossings


def test_twin_crossing_deduped():
    ev = [(10.0, 1, True, (100.0, 100.0), "car"),
          (10.4, 1, True, (110.0, 102.0), "car")]     # twin: close in t+space
    kept, dropped = dedup_crossings(ev)
    assert len(kept) == 1 and dropped == 1


def test_platoon_not_deduped():
    # two vehicles 0.5 s apart but 80 px apart = a platoon, both count
    ev = [(10.0, 1, True, (100.0, 100.0), "car"),
          (10.5, 1, True, (180.0, 100.0), "car")]
    kept, dropped = dedup_crossings(ev)
    assert len(kept) == 2 and dropped == 0


def test_opposite_directions_never_dedup():
    ev = [(10.0, 1, True, (100.0, 100.0), "car"),
          (10.2, 1, False, (100.0, 100.0), "car")]
    kept, dropped = dedup_crossings(ev)
    assert len(kept) == 2


def test_window_expiry():
    # same spot 2 s later = the NEXT vehicle in queue discharge
    ev = [(10.0, 1, True, (100.0, 100.0), "car"),
          (12.0, 1, True, (100.0, 100.0), "car")]
    kept, dropped = dedup_crossings(ev)
    assert len(kept) == 2
