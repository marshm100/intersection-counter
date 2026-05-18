"""v3 Phase 2 — Videos tab API tests.

Exercises bulk upload, filename-parse enrichment, label PATCH, and
save-labels derivation of intersections + cameras.
"""

import os
import shutil
import tempfile
from datetime import datetime

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend import database


client = TestClient(app)


@pytest.fixture()
def project_id():
    """Create a fresh project, yield its id, delete it after the test."""
    r = client.post("/api/projects", json={"name": "v3-videos-test"})
    assert r.status_code == 200, r.text
    pid = r.json()["project_id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _make_fake_video(dir_path: str, name: str, frames: int = 15) -> str:
    p = os.path.join(dir_path, name)
    w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (320, 240))
    for i in range(frames):
        w.write(np.full((240, 320, 3), 50 + i * 10, dtype=np.uint8))
    w.release()
    return p


@pytest.fixture()
def fake_videos():
    tmpdir = tempfile.mkdtemp(prefix="v3_videos_")
    paths = [
        _make_fake_video(tmpdir, "Cam1_01_20260514_080000 Main St.mp4"),
        _make_fake_video(tmpdir, "Cam2_01_20260514_080000 Main St.mp4"),
        _make_fake_video(tmpdir, "Cam1_01_20260515_080000 5th Ave.mp4"),
        _make_fake_video(tmpdir, "DSC00123.mp4"),  # unparseable filename
    ]
    yield paths
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestBulkAttach:
    def test_bulk_adds_all(self, project_id, fake_videos):
        r = client.post(f"/api/projects/{project_id}/videos/bulk",
                        json={"paths": fake_videos})
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) == 4
        # No errors when files actually exist
        errors = [r for r in results if "error" in r]
        assert errors == []

    def test_parsed_fields_populated(self, project_id, fake_videos):
        client.post(f"/api/projects/{project_id}/videos/bulk",
                    json={"paths": fake_videos})
        r = client.get(f"/api/projects/{project_id}/videos")
        vids = r.json()
        cam1 = next(v for v in vids if "Cam1_01_20260514" in v["filename"])
        assert cam1["camera_label_parsed"] == "Cam1"
        assert cam1["intersection_name_label"] == "Main St"
        assert cam1["recording_start_datetime"].startswith("2026-05-14T08:00:00")
        assert cam1["parse_confidence"] == 1.0

    def test_unparseable_filename_has_low_confidence(self, project_id, fake_videos):
        client.post(f"/api/projects/{project_id}/videos/bulk",
                    json={"paths": fake_videos})
        r = client.get(f"/api/projects/{project_id}/videos")
        vids = r.json()
        dsc = next(v for v in vids if v["filename"] == "DSC00123.mp4")
        assert dsc["camera_label_parsed"] == "Unknown"
        assert dsc["parse_confidence"] == 0.0
        assert dsc["intersection_name_label"] is None

    def test_idempotent_re_add(self, project_id, fake_videos):
        client.post(f"/api/projects/{project_id}/videos/bulk",
                    json={"paths": fake_videos[:1]})
        r = client.post(f"/api/projects/{project_id}/videos/bulk",
                        json={"paths": fake_videos[:1]})
        assert r.status_code == 200
        # Same path returns existing row; total video count remains 1.
        r = client.get(f"/api/projects/{project_id}/videos")
        assert len(r.json()) == 1

    def test_partial_success_on_bad_path(self, project_id, fake_videos):
        bad_path = "C:/does/not/exist.mp4"
        r = client.post(f"/api/projects/{project_id}/videos/bulk",
                        json={"paths": [fake_videos[0], bad_path]})
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) == 2
        # First succeeded, second has an error key
        assert "error" not in results[0]
        assert results[1].get("error")


class TestPatchLabels:
    def test_intersection_name_edit(self, project_id, fake_videos):
        client.post(f"/api/projects/{project_id}/videos/bulk",
                    json={"paths": fake_videos[:1]})
        vid = client.get(f"/api/projects/{project_id}/videos").json()[0]
        r = client.patch(
            f"/api/projects/{project_id}/videos/{vid['video_id']}/labels",
            json={"intersection_name": "Main St & 5th Ave"},
        )
        assert r.status_code == 200
        assert r.json()["intersection_name_label"] == "Main St & 5th Ave"

    def test_partial_patch_preserves_other_fields(self, project_id, fake_videos):
        client.post(f"/api/projects/{project_id}/videos/bulk",
                    json={"paths": fake_videos[:1]})
        vid = client.get(f"/api/projects/{project_id}/videos").json()[0]
        original_dt = vid["recording_start_datetime"]
        client.patch(
            f"/api/projects/{project_id}/videos/{vid['video_id']}/labels",
            json={"camera_label": "CamNW"},
        )
        v = client.get(f"/api/projects/{project_id}/videos").json()[0]
        assert v["camera_label_parsed"] == "CamNW"
        assert v["recording_start_datetime"] == original_dt


class TestSaveLabels:
    def test_derives_two_intersections_across_dates(self, project_id, fake_videos):
        # Cam1+Cam2 Main St on 5/14, Cam1 5th Ave on 5/15 = 2 intersection-days
        client.post(f"/api/projects/{project_id}/videos/bulk",
                    json={"paths": fake_videos[:3]})
        r = client.post(f"/api/projects/{project_id}/videos/save-labels")
        body = r.json()
        assert len(body["intersections"]) == 2
        names_dates = sorted((i["name"], i["date"]) for i in body["intersections"])
        assert names_dates == [
            ("5th Ave", "2026-05-15"),
            ("Main St", "2026-05-14"),
        ]

    def test_cameras_grouped_within_intersection_day(self, project_id, fake_videos):
        client.post(f"/api/projects/{project_id}/videos/bulk",
                    json={"paths": fake_videos[:3]})
        r = client.post(f"/api/projects/{project_id}/videos/save-labels")
        intersections = r.json()["intersections"]
        main_st = next(i for i in intersections if i["name"] == "Main St")
        # Cam1 + Cam2 both at Main St on 5/14
        cams = database.list_cameras(project_id, main_st["intersection_id"])
        labels = sorted(c["label"] for c in cams)
        assert labels == ["Cam1", "Cam2"]

    def test_skips_videos_with_no_intersection_name(self, project_id, fake_videos):
        # DSC00123.mp4 has no intersection_name_label, so it gets skipped
        client.post(f"/api/projects/{project_id}/videos/bulk",
                    json={"paths": fake_videos})
        r = client.post(f"/api/projects/{project_id}/videos/save-labels")
        body = r.json()
        assert body["videos_skipped"] >= 1

    def test_idempotent_re_save(self, project_id, fake_videos):
        client.post(f"/api/projects/{project_id}/videos/bulk",
                    json={"paths": fake_videos[:3]})
        first = client.post(f"/api/projects/{project_id}/videos/save-labels").json()
        second = client.post(f"/api/projects/{project_id}/videos/save-labels").json()
        # Re-saving should produce the same intersection IDs (upsert path)
        first_ids = sorted(i["intersection_id"] for i in first["intersections"])
        second_ids = sorted(i["intersection_id"] for i in second["intersections"])
        assert first_ids == second_ids

    def test_first_build_reports_created_counts(self, project_id, fake_videos):
        """Frontend uses these counts to render 'Built X new, kept Y' toasts
        so a re-click is honest about whether anything actually changed."""
        client.post(f"/api/projects/{project_id}/videos/bulk",
                    json={"paths": fake_videos[:3]})
        body = client.post(f"/api/projects/{project_id}/videos/save-labels").json()
        # First build of 2 intersections (Main St 5/14, 5th Ave 5/15) and
        # 3 cameras (Cam1+Cam2 at Main St, Cam1 at 5th Ave).
        assert body["intersections_created"] == 2
        assert body["intersections_existed"] == 0
        assert body["cameras_created"] == 3
        assert body["cameras_existed"] == 0

    def test_re_save_reports_existed_not_created(self, project_id, fake_videos):
        """The second click should report everything as existed, nothing
        created — so the UI can say 'no changes' instead of pretending
        another batch was built."""
        client.post(f"/api/projects/{project_id}/videos/bulk",
                    json={"paths": fake_videos[:3]})
        client.post(f"/api/projects/{project_id}/videos/save-labels")
        body = client.post(f"/api/projects/{project_id}/videos/save-labels").json()
        assert body["intersections_created"] == 0
        assert body["cameras_created"] == 0
        assert body["intersections_existed"] >= 2
        assert body["cameras_existed"] >= 3

    def test_videos_linked_to_correct_camera(self, project_id, fake_videos):
        client.post(f"/api/projects/{project_id}/videos/bulk",
                    json={"paths": fake_videos[:3]})
        client.post(f"/api/projects/{project_id}/videos/save-labels")
        # All 3 videos should now have a camera_id
        vids = client.get(f"/api/projects/{project_id}/videos").json()
        camera_id_videos = [v for v in vids if v.get("camera_id")]
        assert len(camera_id_videos) == 3
