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
        _startPreviewPolling(pid);
    } else if (statusData.status === 'paused') {
        _startPreviewPolling(pid);
    }
}

function _renderProcessingPage(section, data) {
    const pid = AppState.currentProject;
    const status = data.status || 'idle';
    const progress = data.progress || null;
    const isRunning = data.is_running || false;
    const hasCheckpoint = data.has_checkpoint || false;
    const savedStart = data.count_start_time || '00:00';
    const savedEnd   = data.count_end_time   || '';

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

    // Preview image — polled via setInterval for both processing and paused states
    if (status === 'processing' || status === 'paused') {
        const opacity = status === 'paused' ? '0.7' : '1';
        html += `<div class="proc-preview-wrap">
            <img id="proc-preview"
                 src=""
                 alt=""
                 style="width:100%;border-radius:4px;border:1px solid #e5e7eb;opacity:${opacity};" />
        </div>`;
    }

    // Review panel — shown when processing is complete
    if (status === 'complete' && progress) {
        const totalFrames = progress.total_frames || 0;
        const fps = progress.fps_processing || 30;
        const videoDuration = totalFrames > 0 ? totalFrames / 30 : 0;  // approximate
        html += `<div class="review-panel">
            <h3>Video Review</h3>
            <div class="proc-preview-wrap">
                <img id="review-preview" src="" alt="Review frame"
                     style="width:100%;border-radius:4px;border:1px solid #e5e7eb;" />
            </div>
            <div class="review-controls">
                <input type="range" id="review-slider" class="review-slider"
                       min="0" max="${totalFrames}" value="0" step="1" />
                <div class="review-time-row">
                    <span id="review-time" class="review-time">0:00 / ${_formatVideoTime(videoDuration)}</span>
                    <label class="review-toggle-label">
                        <input type="checkbox" id="review-traj-toggle" checked />
                        Show trajectories
                    </label>
                </div>
            </div>
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
        html += '<div class="count-window-row">';
        html += '<span class="count-window-label">Frame Skip</span>';
        html += `<select id="proc-frame-skip">
            <option value="1">1 (every frame)</option>
            <option value="2">2 (every 2nd)</option>
            <option value="3" selected>3 (every 3rd)</option>
            <option value="5">5 (every 5th)</option>
        </select>`;
        html += '<span class="count-window-hint">(higher = faster but less precise)</span>';
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
        html += `<button class="btn-proc btn-resume" onclick="startProcessing()">Re-process</button>`;
    }

    html += '</div>';

    section.innerHTML = html;

    // Wire up review panel if present
    if (status === 'complete' && progress) {
        _initReviewPanel();
    }
}

let _reviewDebounceTimer = null;

function _initReviewPanel() {
    const slider = document.getElementById('review-slider');
    const toggle = document.getElementById('review-traj-toggle');
    if (!slider) return;

    // Fetch initial frame
    _fetchReviewFrame(0);

    slider.addEventListener('input', () => {
        if (_reviewDebounceTimer) clearTimeout(_reviewDebounceTimer);
        _reviewDebounceTimer = setTimeout(() => {
            _fetchReviewFrame(parseInt(slider.value));
        }, 100);
    });

    if (toggle) {
        toggle.addEventListener('change', () => {
            _fetchReviewFrame(parseInt(slider.value));
        });
    }
}

async function _fetchReviewFrame(frameNum) {
    const pid = AppState.currentProject;
    if (!pid) return;
    const img = document.getElementById('review-preview');
    if (!img) return;
    const toggle = document.getElementById('review-traj-toggle');
    const showTraj = toggle ? toggle.checked : true;
    const slider = document.getElementById('review-slider');
    const totalFrames = slider ? parseInt(slider.max) : 0;

    try {
        const resp = await fetch(
            `/api/projects/${pid}/review-frame?frame=${frameNum}&show_trajectories=${showTraj}`
        );
        if (!resp.ok) return;
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const old = img.src;
        img.src = url;
        if (old && old.startsWith('blob:')) URL.revokeObjectURL(old);
    } catch (_) {}

    // Update time display
    const timeEl = document.getElementById('review-time');
    if (timeEl && totalFrames > 0) {
        const currentSec = frameNum / 30;  // approximate fps
        const totalSec = totalFrames / 30;
        timeEl.textContent = `${_formatVideoTime(currentSec)} / ${_formatVideoTime(totalSec)}`;
    }
}

function _formatVideoTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function _statsHtml(progress) {
    const eta = progress.eta_seconds > 0
        ? _formatEta(progress.eta_seconds)
        : '—';
    const tc = progress.turn_counts || {};

    // General stats row
    let html = `
        <div class="stat-item"><span class="stat-label">Vehicles</span><span class="stat-value">${progress.vehicle_count}</span></div>
        <div class="stat-item"><span class="stat-label">FPS</span><span class="stat-value">${(progress.fps_processing || 0).toFixed(1)}</span></div>
        <div class="stat-item"><span class="stat-label">Errors</span><span class="stat-value">${progress.error_count}</span></div>
        <div class="stat-item"><span class="stat-label">ETA</span><span class="stat-value">${eta}</span></div>
        <div class="stat-item"><span class="stat-label">Tracked</span><span class="stat-value">${progress.n_tracks_total||0}</span></div>
        <div class="stat-item"><span class="stat-label">Assigned</span><span class="stat-value">${progress.n_crossed_enter||0}</span></div>
        <div class="stat-item"><span class="stat-label">Unmatched</span><span class="stat-value">${progress.n_crossed_exit||0}</span></div>
        <div class="stat-item"><span class="stat-label">Too short</span><span class="stat-value">${progress.n_insufficient_data||0}</span></div>
    `;

    // Per-leg turn counts
    const legIds = Object.keys(tc);
    // Guard: skip if keys look like movement names (old flat format)
    const isNewFormat = legIds.length > 0 && typeof tc[legIds[0]] === 'object' && tc[legIds[0]] !== null;
    if (isNewFormat) {
        html += '<div class="leg-counts-grid">';
        for (const legId of legIds) {
            const leg = tc[legId];
            const c = leg.counts || {};
            html += `<div class="leg-counts-card">
                <div class="leg-counts-title">${escapeHtml(leg.label || leg.cardinal || legId)}</div>
                <div class="leg-counts-row">
                    <span class="lc-item"><span class="lc-label">L</span>${c.left||0}</span>
                    <span class="lc-item"><span class="lc-label">T</span>${c.through||0}</span>
                    <span class="lc-item"><span class="lc-label">R</span>${c.right||0}</span>
                    <span class="lc-item"><span class="lc-label">U</span>${c.uturn||0}</span>
                </div>
            </div>`;
        }
        html += '</div>';
    }

    return html;
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

function _startPreviewPolling(pid) {
    _stopPreviewPolling();
    const img = document.getElementById('proc-preview');
    if (img) {
        img.src = `/api/projects/${pid}/processing/preview-stream`;
    }
}

function _stopPreviewPolling() {
    const img = document.getElementById('proc-preview');
    if (img) {
        img.src = '';
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
        _stopPreviewPolling();
        // Update action buttons in-place to avoid full DOM churn
        const actionsDiv = document.querySelector('.processing-actions');
        if (actionsDiv) {
            let btns = '';
            if (status === 'paused') {
                btns = `<button class="btn-proc btn-resume" onclick="resumeProcessing()">Resume</button>
                        <button class="btn-proc btn-cancel" onclick="cancelProcessing()">Cancel</button>`;
                _startPreviewPolling(AppState.currentProject);
            } else if (status === 'complete') {
                btns = `<button class="btn-proc btn-start" onclick="showPage('page-dashboard'); loadDashboardPage()">View Results</button>
                        <button class="btn-proc btn-resume" onclick="startProcessing()">Re-process</button>`;
            } else if (status === 'error') {
                btns = `<button class="btn-proc btn-start" onclick="startProcessing()">Start Processing</button>`;
            }
            actionsDiv.innerHTML = btns;
        }
    }
}

async function startProcessing() {
    const pid = AppState.currentProject;
    const startTime = document.getElementById('proc-start-time')?.value || null;
    const endTime   = document.getElementById('proc-end-time')?.value   || null;
    const frameSkipEl = document.getElementById('proc-frame-skip');
    const frameSkip = frameSkipEl ? parseInt(frameSkipEl.value, 10) : null;
    try {
        await API.post(`/api/projects/${pid}/processing/start`, {
            count_start_time: startTime || null,
            count_end_time:   endTime   || null,
            frame_skip: frameSkip,
        });
    } catch (e) {
        alert('Failed to start processing: ' + (e.message || e));
        return;
    }
    await loadProcessingPage();
    _startPolling();
    _startPreviewPolling(pid);
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
    _stopPreviewPolling();
    await loadProcessingPage();
    _startPreviewPolling(pid);
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
    _startPreviewPolling(pid);
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
    _stopPreviewPolling();
    await loadProcessingPage();
}

function goBackFromProcessing() {
    _stopPolling();
    _stopPreviewPolling();
    showPage('page-setup');
    loadSetupPage();
}

function _stopAllProcessingTimers() {
    _stopPolling();
    _stopPreviewPolling();
}

registerTeardown('page-processing', _stopAllProcessingTimers);
