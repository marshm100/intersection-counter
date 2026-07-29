"""Stage-3 footage star rating tests
(docs/plan_stage3_star_rating_2026-07-29.md).

Covers the frozen metric->stars mapping (classify_metrics), the tier-A
metadata path (video_tier + endpoint), and a synthetic end-to-end chain
census (tiny on-disk dump + gates + events) exercising the time-scoped
event join and the same-cell echo signal. The REAL six-site evidence is
scripts/star_rating_gate.py -> runs/stage3_star/rating_gate.json.
"""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection
from backend.services import footage_rating as fr
from backend.services.detection_cache import (
    cache_dir, compute_video_content_hash)

client = TestClient(app)

REC_START = "2026-04-30T07:00:00"


@pytest.fixture()
def project():
    pid = client.post("/api/projects", json={"name": "star-test"}).json()["project_id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _mk_camera(pid, tmp_path, *, height=480, fps=10.0, duration=3600,
               rec_start=REC_START, legs=()):
    """Camera + one video (real dummy file so the content hash works) +
    optional legs [(x, y, heading_deg), ...]."""
    vfile = tmp_path / "clip.mp4"
    if not vfile.exists():
        vfile.write_bytes(b"star-test-video-bytes")
    conn = get_connection(pid)
    with conn:
        iid = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES ('Star', '2026-04-30', 0, 4, '2026-04-30')").lastrowid
        cid = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, 'cam', 0, '2026-04-30')", (iid,)).lastrowid
        conn.execute(
            "INSERT INTO videos (camera_id, sort_order, path, filename, fps, "
            "width, height, total_frames, duration_seconds, file_size_bytes, "
            "recording_start_datetime, added_at) VALUES (?, 0, ?, 'clip.mp4', "
            "?, 640, ?, ?, ?, ?, ?, '2026-04-30')",
            (cid, str(vfile), fps, height, int(duration * fps), duration,
             vfile.stat().st_size, rec_start))
        lids = []
        for (x, y, head) in legs:
            lids.append(conn.execute(
                "INSERT INTO legs (camera_id, label, cardinal_direction, "
                "sort_order, origin_zone, reference_heading) "
                "VALUES (?, 'leg', 'W', 0, ?, ?)",
                (cid, json.dumps([[x, y]]), head)).lastrowid)
    conn.close()
    return iid, cid, lids


# --- the frozen mapping ------------------------------------------------------

class TestClassifyMetrics:
    META_SD = {"height": 480, "width": 640, "fps": 10.0,
               "duration_seconds": 3600, "night_share": 0.0,
               "qualifying_resolution": False}

    def test_no_footage(self):
        r = fr.classify_metrics(None, None)
        assert r["stars"] is None and r["label"] == "No footage"

    def test_resolution_caps_at_four(self):
        r = fr.classify_metrics(self.META_SD, None)
        assert r["stars"] == 4 and r["tier"] == "A"
        assert any("resolution" in x for x in r["reasons"])

    def test_qualifying_resolution_five(self):
        meta = {**self.META_SD, "height": 1080, "width": 1920,
                "qualifying_resolution": True}
        assert fr.classify_metrics(meta, None)["stars"] == 5

    def test_night_dominant_one_star(self):
        meta = {**self.META_SD, "night_share": 0.95}
        r = fr.classify_metrics(meta, None)
        assert r["stars"] == 1

    def test_night_share_is_a_caveat_not_a_cap(self):
        meta = {**self.META_SD, "night_share": 0.4}
        r = fr.classify_metrics(meta, None)
        assert r["stars"] == 4
        assert any("night" in x for x in r["reasons"])

    def _census(self, echo, flip=0.0, valid=True):
        return {"event_join_valid": valid, "echo_share": echo,
                "flip_share": flip, "entry_coverage": 0.5,
                "multi_chain_share": 0.2, "variants": ["w"],
                "event_join_unmapped_share": 0.0 if valid else 0.5}

    def test_echo_over_threshold_drops_to_three(self):
        r = fr.classify_metrics(self.META_SD, self._census(0.10))
        assert r["stars"] == 3 and r["tier"] == "C"
        assert any("echo" in x for x in r["reasons"])

    def test_echo_under_threshold_stays_four(self):
        r = fr.classify_metrics(self.META_SD, self._census(0.02, flip=0.20))
        assert r["stars"] == 4
        assert any("benign" in x for x in r["reasons"])   # flips explained

    def test_invalid_join_is_tier_b_with_reason(self):
        r = fr.classify_metrics(self.META_SD, self._census(None, valid=False))
        assert r["tier"] == "B" and r["stars"] == 4
        assert any("legacy basis" in x for x in r["reasons"])


# --- tier A (metadata) -------------------------------------------------------

class TestTierA:
    def test_video_tier_night_share(self, project, tmp_path):
        # 19:00 start + 2 h -> the 20:00-21:00 hour is night = 0.5
        iid, cid, _ = _mk_camera(project, tmp_path, duration=7200,
                                 rec_start="2026-04-30T19:00:00")
        conn = get_connection(project)
        meta = fr.video_tier(conn, cid)
        conn.close()
        assert meta["night_share"] == pytest.approx(0.5, abs=0.01)

    def test_endpoint_tier_a(self, project, tmp_path):
        iid, cid, _ = _mk_camera(project, tmp_path)
        r = client.get(f"/api/projects/{project}/cameras/{cid}/footage-rating")
        assert r.status_code == 200
        body = r.json()
        assert body["stars"] == 4 and body["tier"] == "A"
        assert "pending" in " ".join(body["reasons"])

    def test_endpoint_404s(self, project):
        r = client.get(f"/api/projects/{project}/cameras/999/footage-rating")
        assert r.status_code == 404


# --- synthetic end-to-end census --------------------------------------------

class TestSyntheticCensus:
    def _write_dump(self, pid, cid, vpath, vrow, tracks, variant="w1"):
        chash, _ = compute_video_content_hash(
            vpath, file_size_bytes=vrow["file_size_bytes"],
            total_frames=vrow["total_frames"])
        tdir = cache_dir(pid, cid, chash) / f"{variant}.tracks"
        tdir.mkdir(parents=True, exist_ok=True)
        rows = [[tid, f, x, y] for tid, pts in tracks.items()
                for (f, x, y) in pts]
        rows.sort(key=lambda r: r[1])
        np.save(tdir / "rows.npy", np.array(rows, dtype=np.float64))
        (tdir / "count.txt").write_text(str(len(rows)))

    def test_census_echo_and_join(self, project, tmp_path):
        # two legs facing each other across a 400 px road; gates are the
        # perpendiculars through the mouths
        iid, cid, lids = _mk_camera(
            project, tmp_path,
            legs=((100.0, 240.0, 0.0), (500.0, 240.0, 180.0)))
        conn = get_connection(project)
        vid, vpath, fsize, tframes = conn.execute(
            "SELECT video_id, path, file_size_bytes, total_frames "
            "FROM videos WHERE camera_id=?", (cid,)).fetchone()
        # track 1 crosses both gates (full); track 2 stays outside spans
        tracks = {
            1: [(f, 50.0 + 55.0 * f, 240.0) for f in range(10)],
            2: [(f, 50.0 + 55.0 * f, 240.0) for f in range(20, 30)],
        }
        self._write_dump(project, cid, vpath,
                         {"file_size_bytes": fsize, "total_frames": tframes},
                         tracks)
        with conn:
            for ts in (0.3, 0.6):        # tid 1: same cell twice = echo
                conn.execute(
                    "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
                    "origin_leg_id, destination_leg_id, movement, "
                    "trajectory_data, trajectory_confidence, vehicle_class, "
                    "detection_confidence, timestamp_video, frame_number) "
                    "VALUES (?, 1, ?, ?, 'through', '[]', 0.9, 'car', 0.9, "
                    "?, ?)", (cid, lids[0], lids[1], ts, int(ts * 10)))
            conn.execute(
                "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
                "origin_leg_id, destination_leg_id, movement, trajectory_data, "
                "trajectory_confidence, vehicle_class, detection_confidence, "
                "timestamp_video, frame_number) VALUES (?, 2, ?, ?, "
                "'through', '[]', 0.9, 'car', 0.9, 2.5, 25)",
                (cid, lids[0], lids[1]))
            # an event OUTSIDE the dump span (uncovered, must not join)
            conn.execute(
                "INSERT INTO vehicle_events (camera_id, vehicle_track_id, "
                "origin_leg_id, destination_leg_id, movement, trajectory_data, "
                "trajectory_confidence, vehicle_class, detection_confidence, "
                "timestamp_video, frame_number) VALUES (?, 1, ?, ?, "
                "'through', '[]', 0.9, 'car', 0.9, 500.0, 5000)",
                (cid, lids[0], lids[1]))
        conn.close()
        census = fr.chain_census(project, cid)
        assert census is not None
        assert census["tracks_mapped"] == 2
        assert census["events_joined"] == 3
        assert census["events_uncovered"] == 1
        assert census["event_join_valid"] is True
        assert census["excess_same_cell"] == 1      # tid-1's repeat
        assert census["echo_share"] == pytest.approx(1 / 3, abs=0.01)
        rating = fr.rate_camera(project, cid)
        assert rating["tier"] == "C"
        assert rating["stars"] == 3                  # echo over the 4% line
