"""Unit tests for the view-invariant articulated (semi) size test (§3-D).

The size logic is the crux; the cache/DB linking in services/articulated.py is
validated on FM51 (~82 articulated vs Miovision 102 at K=2.0). These lock the
pure functions in classifier.py.
"""
from backend.services.classifier import (
    build_car_length_baseline, is_articulated, local_car_length,
)


def test_baseline_is_per_band_median_and_drops_sparse_bands():
    # band width 40px. Band 0 (y 0-40): 20 cars len 30. Band 1 (y 40-80): 5 cars
    # (below min_cars -> untrustworthy median -> dropped).
    cars = [(30.0, 10.0)] * 20 + [(50.0, 50.0)] * 5
    base = build_car_length_baseline(cars, band_px=40, min_cars=20)
    assert base == {0: 30.0}


def test_local_car_length_searches_outward_then_gives_up():
    base = {5: 40.0}
    assert local_car_length(210.0, base, 40) == 40.0   # y210 -> band 5 exact
    assert local_car_length(170.0, base, 40) == 40.0   # y170 -> band 4, +1 finds band 5
    assert local_car_length(1000.0, base, 40) is None   # nothing within a few bands


def test_is_articulated_thresholds_on_local_car_ratio():
    base = {0: 30.0}
    assert is_articulated(70.0, 10.0, base, ratio=2.0, band_px=40) is True    # 2.33x -> semi
    assert is_articulated(50.0, 10.0, base, ratio=2.0, band_px=40) is False   # 1.67x -> single-unit
    assert is_articulated(60.0, 10.0, base, ratio=2.0, band_px=40) is False   # exactly 2.0x -> not (>)


def test_is_articulated_undecidable_without_local_baseline():
    # No car baseline near this row -> None (caller leaves it single-unit, never guesses).
    assert is_articulated(999.0, 1000.0, {0: 30.0}, ratio=2.0, band_px=40) is None


# --- stored-bbox post-pass (zero undecidable, no cache) --------------------
import json
from datetime import datetime, timezone

import backend.database as db
from backend.services.articulated import reclassify_articulated


def _seed(pid, rows):
    """rows = [(vehicle_class, bbox_length, bbox_center_y), ...]. Returns camera_id."""
    (db.PROJECTS_DIR / pid).mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection(pid)   # runs the §3-D migration
    try:
        conn.execute("INSERT INTO intersections (name,date,sort_order,created_at) "
                     "VALUES ('a','2026-07-06',0,?)", (now,))
        iid = conn.execute("SELECT intersection_id FROM intersections").fetchone()[0]
        conn.execute("INSERT INTO cameras (intersection_id,label,sort_order,created_at) "
                     "VALUES (?,?,?,?)", (iid, "c", 0, now))
        cid = conn.execute("SELECT camera_id FROM cameras").fetchone()[0]
        conn.execute("INSERT INTO legs (camera_id,label,cardinal_direction,sort_order,"
                     "origin_zone,reference_heading) VALUES (?,?,?,?,?,?)",
                     (cid, "N", "N", 0, json.dumps([[0, 0]]), 0.0))
        lid = conn.execute("SELECT leg_id FROM legs").fetchone()[0]
        for i, (vc, blen, bcy) in enumerate(rows):
            conn.execute(
                "INSERT INTO vehicle_events (camera_id, vehicle_track_id, origin_leg_id, "
                "movement, trajectory_data, trajectory_confidence, vehicle_class, "
                "detection_confidence, timestamp_video, frame_number, bbox_length, bbox_center_y) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, i, lid, "through", "[[0,0]]", 0.9, vc, 0.9, 0.0, i, blen, bcy))
        conn.commit()
        return cid
    finally:
        conn.close()


def test_reclassify_prefers_stored_bbox_zero_undecidable():
    # 25 cars len 30 in one distance band -> baseline 30. Trucks: 3 at 80 (>2x) are
    # articulated, 2 at 50 (<2x) stay single. All decided from the DB, no cache.
    rows = ([("car", 30.0, 100.0)] * 25
            + [("single_unit_truck", 80.0, 100.0)] * 3
            + [("single_unit_truck", 50.0, 100.0)] * 2)
    cid = _seed("artic_stored", rows)
    r = reclassify_articulated("artic_stored", cid, apply=False)
    assert r["baseline_source"] == "stored"
    assert r["undecidable"] == 0
    assert r["cache_linked"] == 0
    assert r["articulated"] == 3
    assert r["single_unit"] == 2


def test_reclassify_apply_writes_articulated_fhwa():
    rows = [("car", 30.0, 100.0)] * 25 + [("single_unit_truck", 80.0, 100.0)] * 2
    cid = _seed("artic_apply", rows)
    r = reclassify_articulated("artic_apply", cid, apply=True)
    assert r["applied"] is True and r["articulated"] == 2
    conn = db.get_connection("artic_apply")
    n9 = conn.execute("SELECT COUNT(*) FROM vehicle_events "
                      "WHERE fhwa_class=9 AND vehicle_class='multi_unit_truck'").fetchone()[0]
    conn.close()
    assert n9 == 2
