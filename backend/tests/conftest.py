"""Session-scoped fixture that redirects PROJECTS_DIR to a temp directory.

This prevents tests from reading, writing, or deleting real user project data
under data/projects/.
"""

import pytest


@pytest.fixture(autouse=True, scope="session")
def isolate_projects_dir(tmp_path_factory):
    """Redirect PROJECTS_DIR to a temp directory so tests never touch real data."""
    tmp = tmp_path_factory.mktemp("test_projects")

    import backend.config

    original = backend.config.PROJECTS_DIR

    # Patch the canonical config module
    backend.config.PROJECTS_DIR = tmp

    # Patch every module that imported PROJECTS_DIR at the module level
    import backend.database
    import backend.routers.projects
    import backend.routers.video
    import backend.routers.videos      # v3 plural router
    import backend.routers.processing
    import backend.routers.calibration  # v3 reads videos table via list_videos

    backend.database.PROJECTS_DIR = tmp
    backend.routers.projects.PROJECTS_DIR = tmp
    backend.routers.video.PROJECTS_DIR = tmp
    backend.routers.videos.PROJECTS_DIR = tmp
    backend.routers.processing.PROJECTS_DIR = tmp
    backend.routers.calibration.PROJECTS_DIR = tmp

    yield tmp

    # Restore originals so importing in non-test contexts isn't permanently patched
    backend.config.PROJECTS_DIR = original
    backend.database.PROJECTS_DIR = original
    backend.routers.projects.PROJECTS_DIR = original
    backend.routers.video.PROJECTS_DIR = original
    backend.routers.videos.PROJECTS_DIR = original
    backend.routers.processing.PROJECTS_DIR = original
    backend.routers.calibration.PROJECTS_DIR = original
