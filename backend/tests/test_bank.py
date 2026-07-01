"""Tests for the Phase 2a GT-free bank build (backend/routers/bank.py +
backend/services/bank_builder.py).

The router contract (404 / idle) uses a real fixture. The build-job orchestration
is tested deterministically by injecting a fake `build_bank_gtfree` module into
sys.modules — so no detection cache is needed and no real DB is touched (the
builder's actual output is validated separately via the CLI)."""
import sys
import time
import types

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection
from backend.services import bank_builder

client = TestClient(app)


def _mk_camera(pid):
    conn = get_connection(pid)
    with conn:
        cur = conn.execute(
            "INSERT INTO intersections (name, date, sort_order, leg_count, created_at) "
            "VALUES ('Bank Int', '2026-07-01', 0, 4, '2026-07-01')")
        iid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO cameras (intersection_id, label, sort_order, created_at) "
            "VALUES (?, 'cam', 0, '2026-07-01')", (iid,))
        cid = cur.lastrowid
    conn.close()
    return iid, cid


@pytest.fixture()
def bank_project():
    pid = client.post("/api/projects", json={"name": "bank-test"}).json()["project_id"]
    iid, cid = _mk_camera(pid)
    yield pid, iid, cid
    client.delete(f"/api/projects/{pid}")


@pytest.fixture()
def fake_builder():
    """Swap in a fake build_bank_gtfree so start_build's worker runs deterministically."""
    saved = sys.modules.get("build_bank_gtfree")
    mod = types.ModuleType("build_bank_gtfree")

    class BankBuildError(Exception):
        pass

    mod.BankBuildError = BankBuildError
    sys.modules["build_bank_gtfree"] = mod
    yield mod
    if saved is not None:
        sys.modules["build_bank_gtfree"] = saved
    else:
        sys.modules.pop("build_bank_gtfree", None)


def _wait(pid, cid, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = bank_builder.get_build_status(pid, cid)
        if st.get("status") not in ("running",):
            return st
        time.sleep(0.05)
    return bank_builder.get_build_status(pid, cid)


# ---- router contract --------------------------------------------------------

class TestBankRouter:
    def test_status_idle_before_build(self, bank_project):
        pid, _iid, cid = bank_project
        r = client.get(f"/api/projects/{pid}/cameras/{cid}/bank/status")
        assert r.status_code == 200
        assert r.json()["status"] == "idle"

    def test_build_unknown_camera_404(self, bank_project):
        pid, _iid, _cid = bank_project
        assert client.post(f"/api/projects/{pid}/cameras/9999/bank/build").status_code == 404
        assert client.get(f"/api/projects/{pid}/cameras/9999/bank/status").status_code == 404


# ---- job orchestration (fake builder) --------------------------------------

class TestBuildJob:
    def test_build_completes_with_qa_summary(self, bank_project, fake_builder):
        pid, _iid, cid = bank_project
        fake_builder.build_gtfree_bank = lambda **kw: {
            "out_path": kw["out"], "qa_path": kw["out"].replace(".json", "_qa.json"),
            "paths": [1, 2, 3],
            "qa": {"n_tracks_usable": 42, "ambiguous_pairs": [],
                   "leg_sanity": [{"leg_id": 1, "verdict": "ok"},
                                  {"leg_id": 2, "verdict": "SUSPECT_LABEL_OR_HEADING"}],
                   "missing_movements": [{"cell": "L1->L2", "movement": "left"}],
                   "cells": [{"status": "admitted"}, {"status": "admitted"},
                             {"status": "bearing_rejected"},
                             {"status": "admitted", "warn": "straight_turn", "cell": "L3->L4"}]},
        }
        assert bank_builder.start_build(pid, cid, minutes=5)["status"] == "running"
        st = _wait(pid, cid)
        assert st["status"] == "complete"
        s = st["summary"]
        assert s["n_paths"] == 3
        assert s["n_admitted"] == 3 and s["n_rejected"] == 1
        assert s["n_tracks_usable"] == 42
        assert len(s["missing_movements"]) == 1
        assert len(s["leg_sanity_warnings"]) == 1        # only the SUSPECT one
        assert len(s["straight_turn_warnings"]) == 1

    def test_build_actionable_error_surfaced(self, bank_project, fake_builder):
        pid, _iid, cid = bank_project

        def _boom(**kw):
            raise fake_builder.BankBuildError("!! no detection cache — process a window first")

        fake_builder.build_gtfree_bank = _boom
        bank_builder.start_build(pid, cid)
        st = _wait(pid, cid)
        assert st["status"] == "error"
        assert st["actionable"] is True
        assert "detection cache" in st["error"]

    def test_second_build_while_running_is_noop(self, bank_project, fake_builder):
        import threading
        pid, _iid, cid = bank_project
        release = threading.Event()   # block the worker so the job stays 'running'

        def _blocking(**kw):
            release.wait(3)
            return {"out_path": kw["out"], "qa_path": "", "paths": [], "qa": {"cells": []}}

        fake_builder.build_gtfree_bank = _blocking
        try:
            bank_builder.start_build(pid, cid)
            second = bank_builder.start_build(pid, cid)   # status set synchronously to 'running'
            assert second.get("already") is True and second["status"] == "running"
        finally:
            release.set()
            _wait(pid, cid)


def test_qa_summary_pure():
    result = {"paths": [1, 2], "qa": {"cells": [
        {"status": "admitted"}, {"status": "minor_incoherent_rejected"}],
        "missing_movements": [], "leg_sanity": [], "ambiguous_pairs": []}}
    s = bank_builder._qa_summary(result)
    assert s["n_paths"] == 2 and s["n_admitted"] == 1 and s["n_rejected"] == 1
