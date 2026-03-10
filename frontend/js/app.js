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

document.addEventListener('DOMContentLoaded', () => {
    showPage('page-projects');
    loadProjectList();
});
