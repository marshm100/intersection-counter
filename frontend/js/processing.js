let _processingPollTimer = null;

async function loadProcessingPage() {
    const pid = AppState.currentProject;
    if (!pid) { showPage('page-projects'); loadProjectList(); return; }

    const section = document.getElementById('page-processing');
    section.innerHTML = '<p class="empty-message">Loading...</p>';

    let statusData;
    try {
        statusData = await API.get(`/api/projects/${pid}/processing/status`);
    } catch (e) {
        section.innerHTML = '<p class="empty-message">Could not load processing status.</p>';
        return;
    }

    _renderProcessingPage(section, statusData);

    if (statusData.status === 'processing') {
        _startPolling();
    }
}

function _renderProcessingPage(section, data) {
    const pid = AppState.currentProject;
    const status = data.status || 'idle';
    const progress = data.progress || null;
    const isRunning = data.is_running || false;
    const hasCheckpoint = data.has_checkpoint || false;
    const savedStart = data.count_start_time || '00:00';
    const savedEnd   = data.count_end_time   || '23:59';

    let html = '';

    // Header
    html += '<div class="processing-header">';
    html += '<a href="#" class="back-link" onclick="goBackFromProcessing(); return false;">&larr; Back to Setup</a>';
    html += '<h2>Processing</h2>';
    html += '</div>';

    // Status badge
    html += `<div class="processing-status-row">`;
    html += `<span class="status-badge status-${status}">${status.charAt(0).toUpperCase() + status.slice(1)}</span>`;
    html += '</div>';

    // Progress bar
    const pct = progress ? Math.min(100, progress.progress_pct || 0) : 0;
    html += '<div class="progress-container">';
    html += `<div class="progress-fill" id="proc-progress-fill" style="width:${pct.toFixed(2)}%"></div>`;
    html += '</div>';
    html += `<div class="progress-pct" id="proc-progress-pct">${pct.toFixed(1)}%</div>`;

    // Stats row
    html += '<div class="processing-stats" id="proc-stats">';
    if (progress) {
        html += _statsHtml(progress);
    }
    html += '</div>';

    // Live stream while processing; static last-frame while paused
    if (status === 'processing') {
        const streamUrl = `/api/projects/${pid}/processing/preview-stream?_t=${Date.now()}`;
        html += `<div class="proc-preview-wrap">
            <img id="proc-preview"
                 src="${streamUrl}"
                 alt=""
                 style="width:100%;border-radius:4px;border:1px solid #e5e7eb;" />
        </div>`;
    } else if (status === 'paused') {
        const frameUrl = `/api/projects/${pid}/processing/preview-frame?_t=${Date.now()}`;
        html += `<div class="proc-preview-wrap">
            <img id="proc-preview"
                 src="${frameUrl}"
                 alt=""
                 style="width:100%;border-radius:4px;border:1px solid #e5e7eb;opacity:0.7;" />
        </div>`;
    }

    // Count window — shown when idle/error/complete (not while running/paused)
    if (status === 'idle' || status === 'error' || status === 'complete') {
        html += '<div class="count-window-row">';
        html += '<span class="count-window-label">Count Window</span>';
        html += `<input type="time" id="proc-start-time" value="${savedStart}" />`;
        html += '<span class="count-window-sep">to</span>';
        html += `<input type="time" id="proc-end-time" value="${savedEnd}" />`;
        html += '<span class="count-window-hint">(HH:MM offset from video start)</span>';
        html += '</div>';
    }

    // Action buttons
    html += '<div class="processing-actions">';

    if (status === 'idle' || status === 'error') {
        html += `<button class="btn-proc btn-start" onclick="startProcessing()">Start Processing</button>`;
    }
    if (status === 'processing') {
        html += `<button class="btn-proc btn-pause" onclick="pauseProcessing()">Pause</button>`;
        html += `<button class="btn-proc btn-cancel" onclick="cancelProcessing()">Cancel</button>`;
    }
    if (status === 'paused') {
        html += `<button class="btn-proc btn-resume" onclick="resumeProcessing()">Resume</button>`;
        html += `<button class="btn-proc btn-cancel" onclick="cancelProcessing()">Cancel</button>`;
    }
    if (status === 'complete') {
        html += `<button class="btn-proc btn-start" onclick="showPage('page-dashboard'); loadDashboardPage()">View Results</button>`;
    }

    html += '</div>';

    section.innerHTML = html;
}

function _statsHtml(progress) {
    const eta = progress.eta_seconds > 0
        ? _formatEta(progress.eta_seconds)
        : '—';
    const tc = progress.turn_counts || {};
    return `
        <div class="stat-item"><span class="stat-label">Vehicles</span><span class="stat-value" id="proc-vehicles">${progress.vehicle_count}</span></div>
        <div class="stat-item"><span class="stat-label">Peds</span><span class="stat-value" id="proc-pedestrians">${progress.pedestrian_count}</span></div>
        <div class="stat-item"><span class="stat-label">FPS</span><span class="stat-value" id="proc-fps">${(progress.fps_processing || 0).toFixed(1)}</span></div>
        <div class="stat-item"><span class="stat-label">Errors</span><span class="stat-value" id="proc-errors">${progress.error_count}</span></div>
        <div class="stat-item"><span class="stat-label">ETA</span><span class="stat-value" id="proc-eta">${eta}</span></div>
        <div class="stat-item stat-through"><span class="stat-label">Through</span><span class="stat-value">${tc.through || 0}</span></div>
        <div class="stat-item stat-left"><span class="stat-label">Left</span><span class="stat-value">${tc.left || 0}</span></div>
        <div class="stat-item stat-right"><span class="stat-label">Right</span><span class="stat-value">${tc.right || 0}</span></div>
        <div class="stat-item stat-uturn"><span class="stat-label">U-Turn</span><span class="stat-value">${tc.uturn || 0}</span></div>
        <div class="stat-item"><span class="stat-label">Tracked</span><span class="stat-value">${progress.n_tracks_total||0}</span></div>
        <div class="stat-item"><span class="stat-label">Assigned</span><span class="stat-value">${progress.n_crossed_enter||0}</span></div>
        <div class="stat-item"><span class="stat-label">Unmatched</span><span class="stat-value">${progress.n_crossed_exit||0}</span></div>
        <div class="stat-item"><span class="stat-label">Too short</span><span class="stat-value">${progress.n_insufficient_data||0}</span></div>
    `;
}

function _formatEta(seconds) {
    if (seconds <= 0) return '—';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

function _startPolling() {
    _stopPolling();
    _processingPollTimer = setInterval(_pollStatus, 1000);
}

function _stopPolling() {
    if (_processingPollTimer !== null) {
        clearInterval(_processingPollTimer);
        _processingPollTimer = null;
    }
}

async function _pollStatus() {
    const pid = AppState.currentProject;
    if (!pid) { _stopPolling(); return; }

    let data;
    try {
        data = await API.get(`/api/projects/${pid}/processing/status`);
    } catch (e) {
        return;
    }

    const status = data.status || 'idle';
    const progress = data.progress || null;

    // Update progress bar in-place
    if (progress) {
        const pct = Math.min(100, progress.progress_pct || 0);
        const fill = document.getElementById('proc-progress-fill');
        const pctEl = document.getElementById('proc-progress-pct');
        const statsEl = document.getElementById('proc-stats');
        if (fill) fill.style.width = pct.toFixed(2) + '%';
        if (pctEl) pctEl.textContent = pct.toFixed(1) + '%';
        if (statsEl) statsEl.innerHTML = _statsHtml(progress);
    }

    // Update badge
    const badge = document.querySelector('.status-badge');
    if (badge) {
        badge.className = `status-badge status-${status}`;
        badge.textContent = status.charAt(0).toUpperCase() + status.slice(1);
    }

    if (status !== 'processing') {
        _stopPolling();
        // Re-render buttons for new state
        const section = document.getElementById('page-processing');
        if (section) {
            _renderProcessingPage(section, data);
        }
    }
}

async function startProcessing() {
    const pid = AppState.currentProject;
    const startTime = document.getElementById('proc-start-time')?.value || null;
    const endTime   = document.getElementById('proc-end-time')?.value   || null;
    try {
        await API.post(`/api/projects/${pid}/processing/start`, {
            count_start_time: startTime,
            count_end_time:   endTime,
        });
    } catch (e) {
        alert('Failed to start processing: ' + (e.message || e));
        return;
    }
    await loadProcessingPage();
    _startPolling();
}

async function pauseProcessing() {
    const pid = AppState.currentProject;
    try {
        await API.post(`/api/projects/${pid}/processing/pause`);
    } catch (e) {
        alert('Failed to pause: ' + (e.message || e));
        return;
    }
    _stopPolling();
    await loadProcessingPage();
}

async function resumeProcessing() {
    const pid = AppState.currentProject;
    try {
        await API.post(`/api/projects/${pid}/processing/resume`);
    } catch (e) {
        alert('Failed to resume: ' + (e.message || e));
        return;
    }
    await loadProcessingPage();
    _startPolling();
}

async function cancelProcessing() {
    if (!window.confirm('Cancel processing? The checkpoint will be cleared.')) return;
    const pid = AppState.currentProject;
    try {
        await API.post(`/api/projects/${pid}/processing/cancel`);
    } catch (e) {
        alert('Failed to cancel: ' + (e.message || e));
        return;
    }
    _stopPolling();
    await loadProcessingPage();
}

function goBackFromProcessing() {
    _stopPolling();
    showPage('page-setup');
    loadSetupPage();
}

registerTeardown('page-processing', _stopPolling);
