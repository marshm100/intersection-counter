import pytest
import os
import shutil
from backend.database import (
    get_connection, get_project_dir, get_db_path,
    set_project_info, get_project_info, get_all_project_info
)

TEST_PROJECT = "test_db_step11"

@pytest.fixture(autouse=True)
def cleanup():
    """Clean up test project before and after each test."""
    project_dir = get_project_dir(TEST_PROJECT)
    if project_dir.exists():
        shutil.rmtree(project_dir)
    yield
    if project_dir.exists():
        shutil.rmtree(project_dir)

def test_create_database():
    conn = get_connection(TEST_PROJECT)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    assert 'project_info' in tables
    assert 'legs' in tables
    assert 'vehicle_events' in tables
    assert 'checkpoint' in tables
    assert 'low_confidence_segments' in tables
    # pedestrian_events removed (pedestrians out of scope for v2)
    assert len(tables) == 5

def test_wal_mode():
    conn = get_connection(TEST_PROJECT)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()
    assert mode == 'wal'

def test_project_info_crud():
    set_project_info(TEST_PROJECT, "project_name", "Test Intersection")
    assert get_project_info(TEST_PROJECT, "project_name") == "Test Intersection"

    set_project_info(TEST_PROJECT, "project_name", "Updated Name")
    assert get_project_info(TEST_PROJECT, "project_name") == "Updated Name"

    assert get_project_info(TEST_PROJECT, "nonexistent") is None

def test_project_info_all():
    set_project_info(TEST_PROJECT, "name", "Test")
    set_project_info(TEST_PROJECT, "status", "created")
    all_info = get_all_project_info(TEST_PROJECT)
    assert all_info["name"] == "Test"
    assert all_info["status"] == "created"

def test_persistence():
    set_project_info(TEST_PROJECT, "key1", "value1")
    result = get_project_info(TEST_PROJECT, "key1")
    assert result == "value1"

def test_db_file_location():
    get_connection(TEST_PROJECT).close()
    assert get_db_path(TEST_PROJECT).exists()
