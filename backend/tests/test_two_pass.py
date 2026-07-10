"""Stage-3 two-pass wiring: the flag gate and the missing-dump guard.
The counting-path fidelity itself is gated by scripts/pass2_parity.py (A2)
and the cam5 product-path run (7.1% MAE == the A4a benchmark, stage-3 doc)."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection

client = TestClient(app)


def _mk_cam(pid):
    conn = get_connection(pid)
    with conn:
        iid = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES ('T', '2026-07-10', 0, 4, '2026-07-10')").lastrowid
        cid = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, 'c', 0, '2026-07-10')", (iid,)).lastrowid
    conn.close()
    return cid


@pytest.fixture()
def proj():
    pid = client.post("/api/projects", json={"name": "twopass-test"}).json()["project_id"]
    cid = _mk_cam(pid)
    yield pid, cid
    client.delete(f"/api/projects/{pid}")


class TestTwoPassGate:
    def test_disabled_by_default_404(self, proj):
        # TWO_PASS_ENABLED defaults OFF: the legacy flow must be untouched and
        # the endpoints invisible.
        pid, cid = proj
        r = client.post(f"/api/projects/{pid}/cameras/{cid}/two-pass/run",
                        json={"variant": "study_0700"})
        assert r.status_code == 404
        assert "disabled" in r.json()["detail"]
        assert client.get(
            f"/api/projects/{pid}/cameras/{cid}/two-pass/status").status_code == 404

    def test_missing_dump_raises_actionable(self, proj):
        pid, cid = proj
        from backend.services.two_pass import run_pass2
        with pytest.raises(ValueError):
            # no video row on the synthetic camera -> actionable error, and a
            # camera WITH video but no dump raises FileNotFoundError ("run
            # pass 1 first") — both surface via /two-pass/status as error.
            run_pass2(pid, cid, variant="study_0700", workdir="unused")
