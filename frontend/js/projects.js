let _batchPollTimer = null;

async function loadProjectList() {
    const section = document.getElementById('page-projects');
    let projects = [];
    try {
        projects = await API.get('/api/projects');
    } catch (e) {
        section.innerHTML = '<p class="empty-message">Could not connect to backend.</p>';
        return;
    }

    let html = '<h2>Projects</h2>';

    html += '<div class="project-controls">';
    html += '<input type="text" id="new-project-name" placeholder="New project name..." />';
    html += '<button onclick="createProject()">Create</button>';
    html += '<button class="btn-bulk-import" onclick="bulkImportVideos()">Bulk Import Videos</button>';
    html += '</div>';

    if (projects.length === 0) {
        html += '<p class="empty-message">No projects yet</p>';
    } else {
        // "Start All" button if any project is ready (has video + legs, idle status)
        const ready = projects.filter(p => p.has_video && p.has_legs && !['processing', 'complete', 'queued'].includes(p.status));
        if (ready.length > 0) {
            html += `<div class="batch-controls">`;
            html += `<button class="btn-start-all" onclick="startAllCalibrated()">Start All Calibrated (${ready.length})</button>`;
            html += '</div>';
        }

        html += '<div class="project-list">';
        for (const p of projects) {
            const created = p.created_at ? new Date(p.created_at).toLocaleString() : '';
            const statusClass = 'status-' + (p.status || 'idle');
            html += `<div class="project-card" id="pcard-${p.project_id}">`;
            html += '<div class="project-info">';
            html += `<div class="project-name">${escapeHtml(p.name || '(Untitled)')}</div>`;
            html += `<div class="project-meta">`;
            html += `<span class="status-badge ${statusClass}">${escapeHtml(p.status || 'idle')}</span>`;
            if (!p.has_video) html += ' <span class="setup-hint">needs video</span>';
            else if (!p.has_legs) html += ' <span class="setup-hint">needs calibration</span>';
            html += ` &middot; Created: ${escapeHtml(created)}`;
            html += '</div>';
            html += `<div class="project-progress-bar-container"><div class="project-progress-bar" id="ppbar-${p.project_id}" style="width:0%"></div></div>`;
            html += '</div>';
            html += '<div class="project-actions">';
            html += `<button class="btn-open" onclick="openProject('${p.project_id}')">Open</button>`;
            html += `<button class="btn-delete" onclick="deleteProject('${p.project_id}', '${escapeHtml(p.name)}')">Delete</button>`;
            html += '</div>';
            html += '</div>';
        }
        html += '</div>';
    }

    section.innerHTML = html;

    const input = document.getElementById('new-project-name');
    input.removeEventListener('keydown', _onNewProjectKeydown);
    input.addEventListener('keydown', _onNewProjectKeydown);

    // Start polling if any project is processing or queued
    const hasActive = projects.some(p => ['processing', 'queued'].includes(p.status));
    if (hasActive) {
        _startBatchPolling();
    } else {
        _stopBatchPolling();
    }
}

function _onNewProjectKeydown(e) {
    if (e.key === 'Enter') createProject();
}

async function createProject() {
    const input = document.getElementById('new-project-name');
    const name = input.value.trim();
    if (!name) return;
    await API.post('/api/projects', { name });
    input.value = '';
    await loadProjectList();
}

async function deleteProject(projectId, projectName) {
    if (!window.confirm(`Delete project '${projectName}'? This cannot be undone.`)) return;
    await API.del(`/api/projects/${projectId}`);
    await loadProjectList();
}

function openProject(projectId) {
    AppState.currentProject = projectId;
    showPage('page-setup');
    loadSetupPage();
}

async function bulkImportVideos() {
    let paths;
    try {
        const res = await API.post('/api/video/browse-multi');
        paths = res.paths;
    } catch (e) {
        alert('Could not open file dialog: ' + e.message);
        return;
    }
    if (!paths || paths.length === 0) return;

    try {
        const res = await API.post('/api/projects/bulk-import', { paths });
        let msg = `Created ${res.created.length} project(s)`;
        if (res.errors.length > 0) {
            msg += `\n${res.errors.length} file(s) failed:`;
            for (const err of res.errors) {
                msg += `\n  - ${err.path}: ${err.error}`;
            }
        }
        alert(msg);
    } catch (e) {
        alert('Bulk import failed: ' + e.message);
    }
    await loadProjectList();
}

async function startAllCalibrated() {
    let projects;
    try {
        projects = await API.get('/api/projects');
    } catch (e) {
        alert('Could not load projects: ' + e.message);
        return;
    }

    const readyIds = projects
        .filter(p => p.has_video && p.has_legs && !['processing', 'complete', 'queued'].includes(p.status))
        .map(p => p.project_id);

    if (readyIds.length === 0) {
        alert('No calibrated projects ready to process.');
        return;
    }

    try {
        const res = await API.post('/api/processing/batch-start', { project_ids: readyIds });
        let msg = `Started: ${res.started.length}, Queued: ${res.queued.length}`;
        if (res.skipped.length > 0) {
            msg += `\nSkipped ${res.skipped.length}:`;
            for (const s of res.skipped) msg += `\n  - ${s.reason}`;
        }
        alert(msg);
    } catch (e) {
        alert('Batch start failed: ' + e.message);
    }
    await loadProjectList();
}

// --- Batch status polling ---

function _startBatchPolling() {
    if (_batchPollTimer !== null) return;
    _batchPollTimer = setInterval(_pollBatchStatus, 2000);
    _pollBatchStatus(); // immediate first poll
}

function _stopBatchPolling() {
    if (_batchPollTimer !== null) {
        clearInterval(_batchPollTimer);
        _batchPollTimer = null;
    }
}

async function _pollBatchStatus() {
    let data;
    try {
        data = await API.get('/api/processing/batch-status');
    } catch (e) {
        return;
    }

    let anyActive = false;
    for (const p of data.projects) {
        if (['processing', 'queued'].includes(p.status)) anyActive = true;

        // Update progress bar in-place
        const bar = document.getElementById(`ppbar-${p.project_id}`);
        if (bar) {
            bar.style.width = (p.progress_pct || 0).toFixed(1) + '%';
        }

        // Update status badge in-place
        const card = document.getElementById(`pcard-${p.project_id}`);
        if (card) {
            const badge = card.querySelector('.status-badge');
            if (badge) {
                badge.textContent = p.status;
                badge.className = 'status-badge status-' + p.status;
            }
        }
    }

    if (!anyActive) {
        _stopBatchPolling();
        // Reload to update button visibility
        await loadProjectList();
    }
}

registerTeardown('page-projects', _stopBatchPolling);
