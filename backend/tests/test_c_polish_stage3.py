"""C-polish stage 3 (plan_C_polish_2026-07-14 §3b): undo fidelity — the batch
endpoint's prior-values changes list, and the review PATCH manually_edited
override. The worklist's Z-undo reverts through these; without them an
edit-then-undo leaves events falsely marked operator-edited."""
import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection, insert_flag

from backend.tests.test_flags import _mk_site

client = TestClient(app)


@pytest.fixture()
def site():
    pid = client.post("/api/projects", json={"name": "cpolish3-test"}).json()["project_id"]
    iid, cid, lid, eids = _mk_site(pid)
    yield pid, iid, cid, lid, eids
    client.delete(f"/api/projects/{pid}")


def _event(pid, eid):
    conn = get_connection(pid)
    row = conn.execute(
        "SELECT movement, rejected, manually_edited FROM vehicle_events "
        "WHERE event_id = ?", (eid,)).fetchone()
    conn.close()
    return {"movement": row[0], "rejected": row[1], "manually_edited": row[2]}


class TestBatchChanges:
    def test_batch_move_returns_priors_and_undo_restores(self, site):
        pid, iid, cid, lid, eids = site
        # one member pre-edited (manually_edited=1) — undo must keep its 1
        conn = get_connection(pid)
        with conn:
            conn.execute("UPDATE vehicle_events SET manually_edited = 1 "
                         "WHERE event_id = ?", (eids[1],))
        conn.close()
        for eid in eids:
            insert_flag(pid, intersection_id=iid, kind="uncertain_event",
                        subtype="dest_ambiguous", event_id=eid,
                        batch_key="dest|test", impact=1)

        r = client.post(f"/api/projects/{pid}/intersections/{iid}/flags/batch",
                        json={"batch_key": "dest|test", "status": "resolved",
                              "movement": "left"})
        assert r.status_code == 200
        body = r.json()
        assert body["affected"] == 2
        chg = {c["event_id"]: c for c in body["changes"]}
        assert chg[eids[0]]["prior_movement"] == "through"
        assert chg[eids[0]]["prior_manually_edited"] == 0
        assert chg[eids[1]]["prior_manually_edited"] == 1
        assert _event(pid, eids[0]) == {"movement": "left", "rejected": 0,
                                        "manually_edited": 1}

        # the undo path: restore each event from priors, reopen each flag
        for c in body["changes"]:
            r2 = client.patch(f"/api/projects/{pid}/review/{c['event_id']}",
                              json={"movement": c["prior_movement"],
                                    "manually_edited":
                                        bool(c["prior_manually_edited"])})
            assert r2.status_code == 200
            r3 = client.patch(f"/api/projects/{pid}/flags/{c['flag_id']}",
                              json={"status": "open"})
            assert r3.status_code == 200
            assert r3.json()["resolved_at"] is None
        assert _event(pid, eids[0]) == {"movement": "through", "rejected": 0,
                                        "manually_edited": 0}
        assert _event(pid, eids[1])["manually_edited"] == 1   # pre-edit kept
        open_n = client.get(
            f"/api/projects/{pid}/intersections/{iid}/flags?status=open"
        ).json()["flags"]
        assert len(open_n) == 2


class TestReviewPatchManuallyEdited:
    def test_default_edit_still_sets_flag(self, site):
        pid, iid, cid, lid, eids = site
        client.patch(f"/api/projects/{pid}/review/{eids[0]}",
                     json={"movement": "right"})
        assert _event(pid, eids[0])["manually_edited"] == 1

    def test_explicit_override_restores_zero(self, site):
        pid, iid, cid, lid, eids = site
        client.patch(f"/api/projects/{pid}/review/{eids[0]}",
                     json={"movement": "right"})
        client.patch(f"/api/projects/{pid}/review/{eids[0]}",
                     json={"movement": "through", "manually_edited": False})
        assert _event(pid, eids[0]) == {"movement": "through", "rejected": 0,
                                        "manually_edited": 0}

    def test_enriched_flag_carries_manually_edited(self, site):
        pid, iid, cid, lid, eids = site
        fid = insert_flag(pid, intersection_id=iid, kind="uncertain_event",
                          subtype="low_conf", event_id=eids[0], impact=1)
        ev = client.get(f"/api/projects/{pid}/flags/{fid}").json()["event"]
        assert ev["manually_edited"] == 0   # prior capture for the undo stack
