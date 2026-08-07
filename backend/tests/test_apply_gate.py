"""Phase-1 apply gate (plan_v2_apply_gate_2026-08-07): dispositions as
product state + per-window candidate-vs-incumbent adjudication under the
blind guards. No Miovision anywhere in here — the gate reads gate-evidence
censuses and counted tables only.
"""
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import (
    get_connection,
    get_disposition,
    list_adjudications,
    record_adjudication,
    set_disposition,
)

client = TestClient(app)


@pytest.fixture()
def proj():
    pid = client.post("/api/projects",
                      json={"name": "apply-gate-test"}).json()["project_id"]
    yield pid
    client.delete(f"/api/projects/{pid}")


def _mk_cam(pid):
    conn = get_connection(pid)
    with conn:
        iid = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, "
            "created_at) VALUES ('T', '2026-05-12', 0, 4, '2026-05-12')"
        ).lastrowid
        cid = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, "
            "created_at) VALUES (?, 'c', 0, '2026-05-12')", (iid,)).lastrowid
    conn.close()
    return iid, cid


class TestDispositions:
    def test_default_is_auto_and_roundtrip(self, proj):
        _, cid = _mk_cam(proj)
        assert get_disposition(proj, cid, "study_0700") == "auto"
        set_disposition(proj, cid, "study_0700", "hold", note="cam4 lesson")
        assert get_disposition(proj, cid, "study_0700") == "hold"
        # window-scoped, not camera-scoped
        assert get_disposition(proj, cid, "study_1600") == "auto"
        set_disposition(proj, cid, "study_0700", "force_once")
        assert get_disposition(proj, cid, "study_0700") == "force_once"

    def test_auto_reset_deletes_the_row(self, proj):
        _, cid = _mk_cam(proj)
        set_disposition(proj, cid, "study_0700", "hold")
        set_disposition(proj, cid, "study_0700", "auto")
        conn = get_connection(proj)
        n = conn.execute("SELECT COUNT(*) FROM dispositions").fetchone()[0]
        conn.close()
        assert n == 0
        assert get_disposition(proj, cid, "study_0700") == "auto"

    def test_invalid_disposition_rejected_by_schema(self, proj):
        import sqlite3
        _, cid = _mk_cam(proj)
        with pytest.raises(sqlite3.IntegrityError):
            set_disposition(proj, cid, "study_0700", "maybe")

    def test_adjudication_audit_trail(self, proj):
        _, cid = _mk_cam(proj)
        record_adjudication(proj, cid, "study_0700", "stand_down",
                            ["event_flood"], {"flood_share_cand": 0.33})
        record_adjudication(proj, cid, "study_0700", "apply",
                            ["gate_pass"], {"flood_share_cand": 0.07})
        rows = list_adjudications(proj, camera_id=cid, variant="study_0700")
        assert [r["decision"] for r in rows] == ["apply", "stand_down"]
        assert rows[1]["reasons"] == ["event_flood"]
        assert rows[0]["metrics"]["flood_share_cand"] == 0.07
        assert list_adjudications(proj, camera_id=cid + 1) == []
