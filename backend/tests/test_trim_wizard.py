"""Stage-4 4.3 tests — cardinal wizard geometry + auto-trims proposal
(plan_stage4_childtest_ux_2026-07-29, GATE 4.3)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection
from backend.services.cardinals import derive_cardinals
from backend.services.queue_autoresolve import claim_windows

client = TestClient(app)

# a 4-leg square around (320, 240): up / right / down / left on screen
SQUARE = {"up": (320.0, 40.0), "right": (600.0, 240.0),
          "down": (320.0, 440.0), "left": (40.0, 240.0)}


class TestDeriveCardinals:
    def test_north_up_is_identity(self):
        c = derive_cardinals(SQUARE, 0.0)
        assert c == {"up": "N", "right": "E", "down": "S", "left": "W"}

    def test_rotation_north_points_screen_right(self):
        # site north lies to screen-right -> the right leg IS the N corner
        c = derive_cardinals(SQUARE, 90.0)
        assert c == {"up": "W", "right": "N", "down": "E", "left": "S"}

    def test_diagonal_snap(self):
        diamond = {"ur": (500.0, 60.0), "dr": (500.0, 420.0),
                   "dl": (140.0, 420.0), "ul": (140.0, 60.0)}
        c = derive_cardinals(diamond, 0.0)
        assert c == {"ur": "NE", "dr": "SE", "dl": "SW", "ul": "NW"}

    def test_small_dial_error_snaps_home(self):
        # 17 degrees off still lands every leg on its nearest corner
        assert derive_cardinals(SQUARE, 17.0) == \
            {"up": "N", "right": "E", "down": "S", "left": "W"}

    def test_empty_ok(self):
        assert derive_cardinals({}, 0.0) == {}

    def test_oblique_t_is_deterministic_neighbor_slot(self):
        # cam3's real geometry (6.4 rehearsal finding #1): the true-N arm
        # sits a full 45 deg off after perspective compression, so the
        # correct {N,S,W} is unreachable from image bearings alone — the
        # wizard must return the DETERMINISTIC nearest cyclic assignment
        # (documented limitation; per-leg override is the recovery).
        t = {"30": (98.7, 359.8), "31": (337.7, 162.0), "32": (406.7, 343.3)}
        out = derive_cardinals(t, 204.0)
        assert out["31"] == "S" and out["32"] == "W"
        assert out["30"] in ("N", "NE")      # the ambiguous arm, stable
        assert derive_cardinals(t, 204.0) == out   # deterministic


@pytest.fixture()
def project():
    pid = client.post("/api/projects", json={"name": "wiz-test"}).json()["project_id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _mk(pid, videos=()):
    """Intersection + camera (+videos [(start_iso, dur_s), ...])."""
    conn = get_connection(pid)
    with conn:
        iid = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES ('Wiz', '2026-04-30', 0, 4, '2026-04-30')").lastrowid
        cid = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, 'cam', 0, '2026-04-30')", (iid,)).lastrowid
        for i, (start, dur) in enumerate(videos):
            conn.execute(
                "INSERT INTO videos (camera_id, sort_order, path, filename, fps, "
                "width, height, total_frames, duration_seconds, file_size_bytes, "
                "recording_start_datetime, added_at) VALUES (?, ?, 'x.mp4', "
                "'x.mp4', 10, 640, 480, 1, ?, 1, ?, '2026-04-30')",
                (cid, i, dur, start))
    conn.close()
    return iid, cid


class TestTrimsProposal:
    def test_short_footage_proposes_its_own_span(self, project):
        iid, cid = _mk(project, [("2026-04-30T07:00:00", 7200)])
        r = client.get(f"/api/projects/{project}/intersections/{iid}"
                       f"/trims/proposal").json()
        assert [p["kind"] for p in r["proposals"]] == ["footage"]
        assert r["proposals"][0]["start_wallclock"] == "07:00:00"
        assert r["proposals"][0]["end_wallclock"] == "09:00:00"
        assert not r["alternative_daylight"]

    def test_full_day_proposes_peaks_and_daylight_alt(self, project):
        iid, cid = _mk(project, [("2026-04-30T00:00:00", 86400)])
        r = client.get(f"/api/projects/{project}/intersections/{iid}"
                       f"/trims/proposal").json()
        peaks = [(p["start_wallclock"], p["end_wallclock"])
                 for p in r["proposals"]]
        assert peaks == [("07:00:00", "09:00:00"), ("11:00:00", "13:00:00"),
                        ("16:00:00", "18:00:00")]
        assert all(p["kind"] == "peak" for p in r["proposals"])
        assert [(a["start_wallclock"], a["end_wallclock"])
                for a in r["alternative_daylight"]] == [("06:00:00", "20:00:00")]

    def test_partial_day_clips_peaks_to_coverage(self, project):
        # footage 08:00-17:00: AM peak clipped to 08-09, PM to 16-17
        iid, cid = _mk(project, [("2026-04-30T08:00:00", 9 * 3600)])
        r = client.get(f"/api/projects/{project}/intersections/{iid}"
                       f"/trims/proposal").json()
        assert [(p["start_wallclock"], p["end_wallclock"])
                for p in r["proposals"]] == [
            ("08:00:00", "09:00:00"), ("11:00:00", "13:00:00"),
            ("16:00:00", "17:00:00")]

    def test_no_videos_is_calm(self, project):
        iid, cid = _mk(project)
        r = client.get(f"/api/projects/{project}/intersections/{iid}"
                       f"/trims/proposal").json()
        assert r["proposals"] == [] and "footage" in r["note"]

    def test_accepted_proposals_reach_the_claim_scope(self, project):
        iid, cid = _mk(project, [("2026-04-30T00:00:00", 86400)])
        r = client.get(f"/api/projects/{project}/intersections/{iid}"
                       f"/trims/proposal").json()
        for p in r["proposals"]:
            rr = client.post(
                f"/api/projects/{project}/intersections/{iid}/trims",
                json={"start_wallclock": p["start_wallclock"],
                      "end_wallclock": p["end_wallclock"]})
            assert rr.status_code == 200
        conn = get_connection(project)
        wins = claim_windows(conn, iid)     # the R5 scope consumer
        conn.close()
        assert wins == [(7 * 3600, 9 * 3600), (11 * 3600, 13 * 3600),
                        (16 * 3600, 18 * 3600)]


class TestDeriveCardinalsEndpoint:
    def test_endpoint_returns_cardinals_and_bounds(self, project):
        iid, cid = _mk(project)
        r = client.post(
            f"/api/projects/{project}/cameras/{cid}/calibration/derive-cardinals",
            json={"north_deg": 0.0,
                  "points": {str(i): list(p) for i, p in
                             enumerate(SQUARE.values())}})
        assert r.status_code == 200
        body = r.json()
        assert body["cardinals"]["0"] == "N" and body["bounds"]["0"] == "S"

    def test_endpoint_guards(self, project):
        iid, cid = _mk(project)
        url = (f"/api/projects/{project}/cameras/{cid}/calibration/"
               f"derive-cardinals")
        assert client.post(url, json={"north_deg": 0.0,
                                      "points": {"a": [1, 2, 3]}}
                           ).status_code == 422
        assert client.post(url, json={"north_deg": 0.0,
                                      "points": {"a": [1, 2]}}
                           ).status_code == 422    # < 2 legs
