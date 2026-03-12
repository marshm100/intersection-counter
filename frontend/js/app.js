const AppState = { currentProject: null, currentPage: 'page-projects' };

const _pageTeardowns = {};

function registerTeardown(pageId, fn) {
    _pageTeardowns[pageId] = fn;
}

function showPage(pageId) {
    const teardown = _pageTeardowns[AppState.currentPage];
    if (teardown) teardown();
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const page = document.getElementById(pageId);
    if (page) page.classList.add('active');
    AppState.currentPage = pageId;
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function saveLastProject(projectId) {
    localStorage.setItem('lastProjectId', projectId);
}

async function maybeRestoreLastProject() {
    const lastId = localStorage.getItem('lastProjectId');
    if (!lastId) { loadProjectList(); return; }
    try {
        const res = await fetch(`/api/projects/${lastId}/processing/status`);
        if (!res.ok) { localStorage.removeItem('lastProjectId'); loadProjectList(); return; }
        AppState.currentProject = lastId;
        showPage('page-processing');
        loadProcessingPage();
    } catch {
        localStorage.removeItem('lastProjectId');
        loadProjectList();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    showPage('page-projects');
    maybeRestoreLastProject();
});
