const AppState = { currentProject: null, currentPage: null };

const _pageTeardowns = {};

function registerTeardown(pageId, fn) {
    _pageTeardowns[pageId] = fn;
}

function saveAppState() {
    if (AppState.currentPage) {
        localStorage.setItem('lastPageId', AppState.currentPage);
    }
    if (AppState.currentProject) {
        localStorage.setItem('lastProjectId', AppState.currentProject);
    } else {
        localStorage.removeItem('lastProjectId');
    }
}

function showPage(pageId) {
    if (AppState.currentPage === pageId) return;
    const teardown = _pageTeardowns[AppState.currentPage];
    if (teardown) teardown();
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const page = document.getElementById(pageId);
    if (page) page.classList.add('active');
    AppState.currentPage = pageId;
    saveAppState();
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function saveLastProject(projectId) {
    AppState.currentProject = projectId;
    saveAppState();
}

async function restoreAppState() {
    const lastId = localStorage.getItem('lastProjectId');
    const lastPage = localStorage.getItem('lastPageId');
    
    if (!lastId || !lastPage || lastPage === 'page-projects') {
        AppState.currentProject = null;
        showPage('page-projects');
        if (typeof loadProjectList === 'function') loadProjectList();
        return;
    }
    
    try {
        const res = await fetch(`/api/projects/${lastId}/processing/status`);
        if (!res.ok) { 
            throw new Error('Project not found');
        }
        AppState.currentProject = lastId;
        showPage(lastPage);
        
        switch(lastPage) {
            case 'page-setup':
                if (typeof loadSetupPage === 'function') loadSetupPage();
                break;
            case 'page-calibration':
                if (typeof loadCalibrationPage === 'function') loadCalibrationPage();
                break;
            case 'page-processing':
                if (typeof loadProcessingPage === 'function') loadProcessingPage();
                break;
            case 'page-dashboard':
                if (typeof loadDashboardPage === 'function') loadDashboardPage();
                break;
            case 'page-export':
                if (typeof loadExportPage === 'function') loadExportPage();
                break;
            case 'page-review':
                if (typeof loadReviewPage === 'function') loadReviewPage();
                break;
            default:
                AppState.currentProject = null;
                showPage('page-projects');
                if (typeof loadProjectList === 'function') loadProjectList();
        }
    } catch {
        AppState.currentProject = null;
        showPage('page-projects');
        if (typeof loadProjectList === 'function') loadProjectList();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    restoreAppState();
});
