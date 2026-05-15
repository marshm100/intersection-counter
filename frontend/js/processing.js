let _processingPollTimer = null;
let _scrubDebounceTimer = null;
let _videoFps = 30;
let _videoDuration = 0;
let _videoTotalFrames = 0;
let _followProcessing = true;

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

    // Fetch v2 video metadata for the scrubber. v3 projects don't have a
    // single project-level video (videos live in the videos table scoped
    // per-camera), so probe project info first and skip the /video call
    // when there's nothing to fetch — otherwise the browser logs a 404
    // for every v3 project that lands on this legacy page.
    _videoFps = 30;
    _videoDuration = 0;
    _videoTotalFrames = 0;
    let hasV2Video = false;
    try {
        const info = await API.get(`/api/projects/${pid}`);
        hasV2Video = !!info.video_path;
    } catch (_) { /* keep defaults */ }
    if (hasV2Video) {
        try {
            const videoInfo = await API.get(`/api/projects/${pid}/video`);
            _videoFps = videoInfo.fps || 30;
            _videoDuration = videoInfo.duration_seconds || 0;
            _videoTotalFrames = videoInfo.total_frames || 0;
        } catch (_) { /* keep defaults */ }
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
    const savedEnd   = data.count_end_time   || '';

    let html = '';

    // Header
    html += '<div class="processing-header">';
    html += '<a href="#" class="back-link" onclick="goHomeFromProcessing(); return false;">&larr; Home</a>';
    html += ' &middot; ';
    html += '<a href="#" class="back-link" onclick="goBackFromProcessing(); return false;">Back to Setup</a>';
    html += '<h2>Processing</h2>';
    html += '</div>';

    // Status badge
    html += `<div class="processing-status-row">`;
    html += `<span class="status-badge status-${status}">${status.charAt(0).toUpperCase() + status.slice(1)}</span>`;
    html += '</div>';

    // Multi-video label: "Video 2 of 3 — filename.mp4"
    if (progress && progress.total_videos && progress.total_videos > 1) {
        const idx = (progress.video_index || 0) + 1;
        const total = progress.total_videos;
        const fname = progress.video_filename ? ' — ' + escapeHtml(progress.video_filename) : '';
        html += `<div class="video-progress-label">Video ${idx} of ${total}${fname}</div>`;
    }

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

    // Video scrubber — shown whenever we have video metadata
    if (_videoDuration > 0) {
        const maxSeconds = Math.floor(_videoDuration);
        const isComplete = status === 'complete';
        const isActive = status === 'processing' || status === 'paused';
        html += `<div class="review-panel">
            <div class="proc-preview-wrap">
                <img id="proc-scrub-preview" src="" alt="Video frame"
                     style="width:100%;border-radius:4px;border:1px solid #e5e7eb;" />
            </div>
            <div class="review-controls">
                <input type="range" id="proc-scrubber" class="review-slider"
                       min="0" max="${maxSeconds}" value="0" step="1" />
                <div class="review-time-row">
                    <span id="proc-scrub-time" class="review-time">0:00 / ${_formatVideoTime(_videoDuration)}</span>
                    <span style="display:flex;gap:12px;align-items:center;">`;
        if (isActive) {
            html += `<label class="review-toggle-label">
                        <input type="checkbox" id="proc-follow-toggle" ${_followProcessing ? 'checked' : ''} />
                        Follow processing
                     </label>`;
        }
        if (isComplete) {
            html += `<label class="review-toggle-label">
                        <input type="checkbox" id="proc-traj-toggle" checked />
                        Show trajectories
                     </label>`;
        }
        html += `   </span>
                </div>
            </div>
        </div>`;
    }

    // Prerequisites check — guide user if project isn't ready
    if (status === 'created') {
        html += '<div class="alert-info" style="background:#eff6ff;border:1px solid #93c5fd;padding:12px 16px;border-radius:6px;margin-bottom:12px;color:#1e40af;">';
        html += 'Set up a video file and calibrate the intersection before processing. ';
        html += '<a href="#" onclick="goBackFromProcessing(); return false;">Go to Setup &rarr;</a>';
        html += '</div>';
    }

    // Interrupted message
    if (status === 'interrupted') {
        html += '<div class="alert-info" style="background:#fef3c7;border:1px solid #f59e0b;padding:12px 16px;border-radius:6px;margin-bottom:12px;color:#92400e;">';
        html += 'Processing was interrupted (server restarted). You can resume from the checkpoint or reprocess from the start with the latest algorithms.';
        html += '</div>';
    }

    if (status === 'idle' || status === 'error' || status === 'complete' || status === 'interrupted') {
        html += '<div class="count-window-row">';
        html += '<span class="count-window-label">Count Window</span>';
        html += `<input type="time" id="proc-start-time" value="${savedStart}" />`;
        html += '<span class="count-window-sep">to</span>';
        html += `<input type="time" id="proc-end-time" value="${savedEnd}" />`;
        html += '<span class="count-window-hint">(HH:MM offset from video start)</span>';
        html += '</div>';
        html += '<div class="count-window-row">';
        html += '<span class="count-window-label">Preview Skip</span>';
        html += `<select id="proc-frame-skip">
            <option value="1">1 (every frame)</option>
            <option value="2">2 (every 2nd)</option>
            <option value="3" selected>3 (every 3rd)</option>
            <option value="5">5 (every 5th)</option>
        </select>`;
        html += '<span class="count-window-hint">(higher = fewer preview updates)</span>';
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
    if (status === 'interrupted') {
        html += `<button class="btn-proc btn-resume" onclick="resumeProcessing()">Resume from Checkpoint</button>`;
        html += `<button class="btn-proc btn-start" onclick="reprocessFromStart()">Reprocess from Start</button>`;
    }
    if (status === 'complete') {
        html += `<button class="btn-proc btn-start" onclick="showPage('page-dashboard'); loadDashboardPage()">View Results</button>`;
        html += `<button class="btn-proc btn-resume" onclick="reprocessFromStart()">Reprocess from Start</button>`;
    }

    html += '</div>';

    section.innerHTML = html;

    // Wire up scrubber
    _initScrubber(status);
}

function _initScrubber(status) {
    const scrubber = document.getElementById('proc-scrubber');
    if (!scrubber) return;

    // Fetch initial frame
    _fetchScrubFrame(0);

    scrubber.addEventListener('input', () => {
        // Manual scrub disables follow mode
        const followToggle = document.getElementById('proc-follow-toggle');
        if (followToggle && followToggle.checked) {
            followToggle.checked = false;
            _followProcessing = false;
        }
        if (_scrubDebounceTimer) clearTimeout(_scrubDebounceTimer);
        _scrubDebounceTimer = setTimeout(() => {
            _fetchScrubFrame(parseInt(scrubber.value));
        }, 100);
    });

    // Follow toggle
    const followToggle = document.getElementById('proc-follow-toggle');
    if (followToggle) {
        followToggle.addEventListener('change', () => {
            _followProcessing = followToggle.checked;
        });
    }

    // Trajectory toggle (only present when complete)
    const trajToggle = document.getElementById('proc-traj-toggle');
    if (trajToggle) {
        trajToggle.addEventListener('change', () => {
            _fetchScrubFrame(parseInt(scrubber.value));
        });
    }
}

async function _fetchScrubFrame(seconds) {
    const pid = AppState.currentProject;
    if (!pid) return;
    const img = document.getElementById('proc-scrub-preview');
    if (!img) return;

    const trajToggle = document.getElementById('proc-traj-toggle');
    const showTraj = trajToggle ? trajToggle.checked : false;

    let url;
    if (showTraj) {
        // Use review-frame endpoint with frame number for trajectory overlay
        const frameNum = Math.round(seconds * _videoFps);
        url = `/api/projects/${pid}/review-frame?frame=${frameNum}&show_trajectories=true`;
    } else {
        url = `/api/projects/${pid}/video/frame?seconds=${seconds}&_t=${Date.now()}`;
    }

    try {
        const resp = await fetch(url);
        if (!resp.ok) return;
        const blob = await resp.blob();
        const blobUrl = URL.createObjectURL(blob);
        const old = img.src;
        img.src = blobUrl;
        if (old && old.startsWith('blob:')) URL.revokeObjectURL(old);
    } catch (_) {}

    // Update time display
    const timeEl = document.getElementById('proc-scrub-time');
    if (timeEl) {
        timeEl.textContent = `${_formatVideoTime(seconds)} / ${_formatVideoTime(_videoDuration)}`;
    }
}

function _formatVideoTime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
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

        // Follow mode: auto-advance scrubber to current processing position
        if (_followProcessing && progress.current_frame != null && _videoFps > 0) {
            const currentSec = Math.floor(progress.current_frame / _videoFps);
            const scrubber = document.getElementById('proc-scrubber');
            if (scrubber && parseInt(scrubber.value) !== currentSec) {
                scrubber.value = currentSec;
                _fetchScrubFrame(currentSec);
            }
        }
    }

    // Update badge
    const badge = document.querySelector('.status-badge');
    if (badge) {
        badge.className = `status-badge status-${status}`;
        badge.textContent = status.charAt(0).toUpperCase() + status.slice(1);
    }

    if (status !== 'processing') {
        _stopPolling();
        // Update action buttons in-place to avoid full DOM churn
        const actionsDiv = document.querySelector('.processing-actions');
        if (actionsDiv) {
            let btns = '';
            if (status === 'paused') {
                btns = `<button class="btn-proc btn-resume" onclick="resumeProcessing()">Resume</button>
                        <button class="btn-proc btn-cancel" onclick="cancelProcessing()">Cancel</button>`;
            } else if (status === 'complete') {
                btns = `<button class="btn-proc btn-start" onclick="showPage('page-dashboard'); loadDashboardPage()">View Results</button>
                        <button class="btn-proc btn-resume" onclick="reprocessFromStart()">Reprocess from Start</button>`;
            } else if (status === 'interrupted') {
                btns = `<button class="btn-proc btn-resume" onclick="resumeProcessing()">Resume from Checkpoint</button>
                        <button class="btn-proc btn-start" onclick="reprocessFromStart()">Reprocess from Start</button>`;
            } else if (status === 'error') {
                btns = `<button class="btn-proc btn-start" onclick="startProcessing()">Start Processing</button>`;
            }
            actionsDiv.innerHTML = btns;
        }
        // When complete, reload to show trajectory toggle
        if (status === 'complete') {
            await loadProcessingPage();
        }
    }
}

async function startProcessing() {
    const pid = AppState.currentProject;
    const startTime = document.getElementById('proc-start-time')?.value || null;
    const endTime   = document.getElementById('proc-end-time')?.value   || null;
    const frameSkipEl = document.getElementById('proc-frame-skip');
    const frameSkip = frameSkipEl ? parseInt(frameSkipEl.value, 10) : null;
    _followProcessing = true;
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

async function reprocessFromStart() {
    if (!window.confirm('Clear all results and reprocess from the beginning?')) return;
    const pid = AppState.currentProject;
    try {
        await API.post(`/api/projects/${pid}/processing/reprocess`);
    } catch (e) {
        alert('Failed to clear results: ' + (e.message || e));
        return;
    }
    // Now start fresh
    await startProcessing();
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

function goHomeFromProcessing() {
    _stopPolling();
    AppState.currentProject = null;
    showPage('page-projects');
    loadProjectList();
}

function goBackFromProcessing() {
    _stopPolling();
    showPage('page-setup');
    loadSetupPage();
}

function _stopAllProcessingTimers() {
    _stopPolling();
}

registerTeardown('page-processing', _stopAllProcessingTimers);
