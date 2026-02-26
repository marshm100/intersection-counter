import pytest
import shutil
from fastapi.testclient import TestClient
from backend.app import app
from backend.config import PROJECTS_DIR

client = TestClient(app)

@pytest.fixture(autouse=True)
def cleanup():
    """Remove any test projects before and after tests."""
    yield
    # Clean up projects created during tests
    if PROJECTS_DIR.exists():
        for d in PROJECTS_DIR.iterdir():
            if d.is_dir() and d.name.startswith("test") is False:
                # Only clean up short hex-style IDs (8 chars) to avoid nuking non-test data
                if len(d.name) == 8:
                    shutil.rmtree(d, ignore_errors=True)

def test_list_empty():
    response = client.get("/api/projects")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_create_project():
    response = client.post("/api/projects", json={"name": "Test Intersection"})
    assert response.status_code == 200
    data = response.json()
    assert "project_id" in data
    assert data["name"] == "Test Intersection"
    assert len(data["project_id"]) == 8
    # Clean up
    shutil.rmtree(PROJECTS_DIR / data["project_id"], ignore_errors=True)

def test_create_and_list():
    r1 = client.post("/api/projects", json={"name": "Project A"})
    r2 = client.post("/api/projects", json={"name": "Project B"})
    id1 = r1.json()["project_id"]
    id2 = r2.json()["project_id"]

    response = client.get("/api/projects")
    projects = response.json()
    ids = [p["project_id"] for p in projects]
    assert id1 in ids
    assert id2 in ids

    # Clean up
    shutil.rmtree(PROJECTS_DIR / id1, ignore_errors=True)
    shutil.rmtree(PROJECTS_DIR / id2, ignore_errors=True)

def test_get_project():
    r = client.post("/api/projects", json={"name": "Detail Test"})
    pid = r.json()["project_id"]

    response = client.get(f"/api/projects/{pid}")
    assert response.status_code == 200
    data = response.json()
    assert data["project_name"] == "Detail Test"
    assert data["status"] == "created"

    # Clean up
    shutil.rmtree(PROJECTS_DIR / pid, ignore_errors=True)

def test_rename_project():
    r = client.post("/api/projects", json={"name": "Old Name"})
    pid = r.json()["project_id"]

    response = client.put(f"/api/projects/{pid}/name", json={"name": "New Name"})
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"

    detail = client.get(f"/api/projects/{pid}")
    assert detail.json()["project_name"] == "New Name"

    # Clean up
    shutil.rmtree(PROJECTS_DIR / pid, ignore_errors=True)

def test_delete_project():
    r = client.post("/api/projects", json={"name": "To Delete"})
    pid = r.json()["project_id"]

    response = client.delete(f"/api/projects/{pid}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True

    # Verify gone
    response = client.get(f"/api/projects/{pid}")
    assert response.status_code == 404

def test_not_found():
    response = client.get("/api/projects/nonexist")
    assert response.status_code == 404

    response = client.delete("/api/projects/nonexist")
    assert response.status_code == 404
