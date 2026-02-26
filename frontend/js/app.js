const AppState = { currentProject: null, currentPage: 'projects' };

function showPage(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const page = document.getElementById(pageId);
    if (page) page.classList.add('active');
    AppState.currentPage = pageId;
}

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const health = await API.get('/api/health');
        document.getElementById('status').textContent = 'Backend: ' + health.status;
    } catch (e) {
        document.getElementById('status').textContent = 'Backend: not connected';
    }
});
