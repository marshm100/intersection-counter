"""DB plumbing for the per-camera speed-tiebreak (2026-07-02):
  - intersection_paths.expected_speed  (per-path signature; read by list_paths)
  - cameras.calib_speed_tiebreak       (per-camera opt-in knob)
Both are added by lazy migration and follow the calib_cost_metric pattern.
"""
import json
from datetime import datetime, timezone

import backend.database as db


def _seed(pid: str) -> int:
    """Minimal intersection+camera+legs+one path (expected_speed=4.2). Returns camera_id."""
    (db.PROJECTS_DIR / pid).mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    conn = db.get_connection(pid)  # creates DB + runs the migration
    try:
        conn.execute("INSERT INTO intersections (name,date,sort_order,created_at) "
                     "VALUES ('x','2026-07-06',0,?)", (now,))
        iid = conn.execute("SELECT intersection_id FROM intersections").fetchone()[0]
        conn.execute("INSERT INTO cameras (intersection_id,label,sort_order,created_at) "
                     "VALUES (?,?,?,?)", (iid, "cam", 0, now))
        cid = conn.execute("SELECT camera_id FROM cameras").fetchone()[0]
        for lbl, cd, so, rh in (("N", "N", 0, 0.0), ("S", "S", 1, 180.0)):
            conn.execute("INSERT INTO legs (camera_id,label,cardinal_direction,sort_order,"
                         "origin_zone,reference_heading) VALUES (?,?,?,?,?,?)",
                         (cid, lbl, cd, so, json.dumps([[0, 0]]), rh))
        l1, l2 = [r[0] for r in conn.execute("SELECT leg_id FROM legs ORDER BY leg_id")]
        conn.execute("INSERT INTO intersection_paths (camera_id,origin_leg_id,destination_leg_id,"
                     "polyline,movement_label,expected_speed,created_at) VALUES (?,?,?,?,?,?,?)",
                     (cid, l1, l2, json.dumps([[0, 0], [10, 0]]), "through", 4.2, now))
        conn.commit()
        return cid
    finally:
        conn.close()


def test_expected_speed_reads_back_on_path():
    cid = _seed("st_paths")
    paths = db.list_paths_for_camera("st_paths", cid)
    assert len(paths) == 1
    assert paths[0]["expected_speed"] == 4.2


def test_speed_tiebreak_knob_is_three_state():
    cid = _seed("st_knob")
    # unset -> None so the pipeline resolves to the config default
    assert db.get_camera_calibration_params("st_knob", cid)["speed_tiebreak"] is None
    # explicit opt-in persists
    db.update_camera_calibration("st_knob", cid, calib_speed_tiebreak=1)
    assert db.get_camera_calibration_params("st_knob", cid)["speed_tiebreak"] == 1
    # clear back to unset
    db.update_camera_calibration("st_knob", cid, calib_speed_tiebreak=db.CLEAR_TO_DEFAULT)
    assert db.get_camera_calibration_params("st_knob", cid)["speed_tiebreak"] is None
