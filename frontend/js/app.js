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

// ---------------------------------------------------------------------------
// Global background processing banner
// ---------------------------------------------------------------------------

let _bgPollTimer = null;
let _bgLastStatus = null;
let _bgCompleteTimeout = null;

function _startBackgroundPoll() {
    if (_bgPollTimer) return;
    _bgPollTimer = setInterval(_bgPollStatus, 3000);
}

function _stopBackgroundPoll() {
    if (_bgPollTimer) { clearInterval(_bgPollTimer); _bgPollTimer = null; }
}

function _showBanner(progress) {
    const el = document.getElementById('processing-banner');
    if (!el) return;
    const pct = Math.min(100, progress.progress_pct || 0);
    el.className = 'processing-banner';
    el.innerHTML =
        '<span class="banner-label">Processing...</span>' +
        '<div class="banner-progress"><div class="banner-fill" style="width:' + pct.toFixed(1) + '%"></div></div>' +
        '<span class="banner-pct">' + pct.toFixed(1) + '%</span>' +
        '<span class="banner-action">View</span>';
    el.onclick = function() {
        showPage('page-processing');
        if (typeof loadProcessingPage === 'function') loadProcessingPage();
    };
}

function _showCompleteBanner() {
    const el = document.getElementById('processing-banner');
    if (!el) return;
    el.className = 'processing-banner complete';
    el.innerHTML =
        '<span class="banner-label">Processing complete</span>' +
        '<span class="banner-action">View Results</span>';
    el.onclick = function() {
        _hideBanner();
        showPage('page-dashboard');
        if (typeof loadDashboardPage === 'function') loadDashboardPage();
    };
}

function _hideBanner() {
    const el = document.getElementById('processing-banner');
    if (!el) return;
    el.className = 'processing-banner hidden';
    el.onclick = null;
}

async function _bgPollStatus() {
    const pid = AppState.currentProject;
    if (!pid) { _hideBanner(); return; }
    if (AppState.currentPage === 'page-processing') { _hideBanner(); return; }

    try {
        const data = await fetch(`/api/projects/${pid}/processing/status`);
        if (!data.ok) return;
        const json = await data.json();
        const status = json.status || 'idle';

        if (status === 'processing' && json.progress) {
            if (_bgCompleteTimeout) { clearTimeout(_bgCompleteTimeout); _bgCompleteTimeout = null; }
            _showBanner(json.progress);
        } else if (_bgLastStatus === 'processing' && status === 'complete') {
            _showCompleteBanner();
            _bgCompleteTimeout = setTimeout(_hideBanner, 8000);
        } else {
            _hideBanner();
        }
        _bgLastStatus = status;
    } catch { /* ignore network errors */ }
}

document.addEventListener('DOMContentLoaded', () => {
    restoreAppState();
    _startBackgroundPoll();
});
