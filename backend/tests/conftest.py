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
    import backend.routers.intersections  # v3 intersection-card router
    import backend.routers.qa            # Phase 3/4 conservation + spot-count QA
    import backend.routers.flags         # Phase B review flag queue
    import backend.routers.bank          # Phase 2a GT-free bank build
    import backend.services.bank_builder  # writes data/projects/<pid>/banks/
    import backend.routers.two_pass       # stage-3 two-pass endpoints

    backend.database.PROJECTS_DIR = tmp
    backend.routers.projects.PROJECTS_DIR = tmp
    backend.routers.video.PROJECTS_DIR = tmp
    backend.routers.videos.PROJECTS_DIR = tmp
    backend.routers.processing.PROJECTS_DIR = tmp
    backend.routers.calibration.PROJECTS_DIR = tmp
    backend.routers.two_pass.PROJECTS_DIR = tmp
    backend.routers.intersections.PROJECTS_DIR = tmp
    backend.routers.qa.PROJECTS_DIR = tmp
    backend.routers.flags.PROJECTS_DIR = tmp
    backend.routers.bank.PROJECTS_DIR = tmp
    backend.services.bank_builder.PROJECTS_DIR = tmp

    yield tmp

    # Restore originals so importing in non-test contexts isn't permanently patched
    backend.config.PROJECTS_DIR = original
    backend.database.PROJECTS_DIR = original
    backend.routers.projects.PROJECTS_DIR = original
    backend.routers.video.PROJECTS_DIR = original
    backend.routers.videos.PROJECTS_DIR = original
    backend.routers.processing.PROJECTS_DIR = original
    backend.routers.calibration.PROJECTS_DIR = original
    backend.routers.intersections.PROJECTS_DIR = original
    backend.routers.qa.PROJECTS_DIR = original
    backend.routers.flags.PROJECTS_DIR = original
    backend.routers.bank.PROJECTS_DIR = original
    backend.services.bank_builder.PROJECTS_DIR = original
