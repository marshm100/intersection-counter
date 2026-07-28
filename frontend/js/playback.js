// v3 Phase 9 — playback verification view with inline correction.
//
// Engineer plays the video, sees AI-detected events as clickable circles
// at the end of each trajectory polyline. Clicking a circle rejects that
// event (post-process correction). Clicking empty area opens "Add missed
// vehicle" — pick origin leg + movement, the click's x/y becomes the
// vehicle's trajectory endpoint.
//
// Designed to read the v3 endpoints:
//   GET  /api/projects/{pid}/intersections/{iid}                    (cameras + videos)
//   GET  /api/projects/{pid}/cameras/{cid}/calibration              (legs for "Add missed" form)
//   GET  /api/projects/{pid}/intersections/{iid}/summary            (count panels)
//   GET  /api/projects/{pid}/review?... [filter by camera]          (events)
//   PATCH /api/projects/{pid}/review/{eid}                          (reject)

let _pbProject = null;
let _pbIntersection = null;
let _pbCameras = [];
let _pbActiveCameraId = null;
let _pbVideos = [];
let _pbActiveVideoIdx = 0;
let _pbEvents = [];
let _pbLegs = [];
let _pbDrawTimer = null;
let _pbLiveTimer = null;

const EVENT_TIME_WINDOW_SECONDS = 2.0;   // ± window around current time
const LIVE_POLL_INTERVAL_MS = 2000;

async function loadPlaybackPage() {
    const pid = AppState.currentProject;
    const iid = AppState.currentIntersectionId;
    if (!pid || !iid) {
        showPage('page-setup');
        return;
    }
    const section = document.getElementById('page-v3-playback');
    section.innerHTML = '<p class="empty-message">Loading dashboard...</p>';

    try {
        _pbProject = await API.get(`/api/projects/${pid}`);
        _pbIntersection = await API.get(`/api/projects/${pid}/intersections/${iid}`);
    } catch (e) {
        section.innerHTML = '<p class="empty-message">Could not load intersection.</p>';
        return;
    }
    _pbCameras = _pbIntersection.cameras || [];
    if (_pbCameras.length === 0) {
        section.innerHTML = '<p class="empty-message">No cameras at this intersection.</p>';
        return;
    }
    _pbActiveCameraId = _pbCameras[0].camera_id;
    _pbVideos = _pbCameras[0].videos || [];
    _pbActiveVideoIdx = 0;

    section.innerHTML = _playbackHtml();
    await _refreshCameraDataAndDraw();
    _bindVideoEvents();
    await _startLivePollingIfRunning();
}

function _playbackHtml() {
    const i = _pbIntersection.intersection;
    return `
        <div class="playback-header">
            <a href="#" class="back-link" onclick="backToProjectFromPlayback(); return false;">&larr; Back to project</a>
            <h2 class="playback-title">${escapeHtml(i.name)} <span class="playback-date">— ${escapeHtml(i.date)}</span></h2>
            <button class="btn-secondary" onclick="pbDownloadExcel()">Download Excel</button>
        </div>
        <div id="pb-live-banner" class="pb-live-banner hidden"></div>
        <div class="playback-camera-tabs">
            ${_pbCameras.map(c => `
                <button class="pb-cam-tab ${c.camera_id === _pbActiveCameraId ? 'active' : ''}"
                        onclick="pbSelectCamera(${c.camera_id})">${escapeHtml(c.label)}</button>
            `).join('')}
        </div>
        <div class="playback-main">
            <div class="playback-video-wrap">
                <video id="pb-video" controls preload="metadata"></video>
                <img id="pb-live-frame" class="hidden" alt="Live processing frame" />
                <canvas id="pb-overlay"></canvas>
                <div id="pb-add-form" class="pb-add-form hidden"></div>
            </div>
            <aside class="playback-sidebar">
                <h4>Counts</h4>
                <div id="pb-counts"><p class="helper-text">Loading...</p></div>
                <h4 style="margin-top:14px;">Active events <span id="pb-active-count" class="helper-text">(0)</span></h4>
                <div id="pb-active-events" class="pb-event-list"></div>
            </aside>
        </div>
        <p class="helper-text">Click a circle to reject that event. Click empty video area to add a missed vehicle.</p>`;
}

async function pbSelectCamera(camId) {
    _pbActiveCameraId = camId;
    const cam = _pbCameras.find(c => c.camera_id === camId);
    _pbVideos = (cam && cam.videos) || [];
    _pbActiveVideoIdx = 0;
    document.querySelectorAll('.pb-cam-tab').forEach(b => {
        b.classList.toggle('active', b.textContent === cam.label);
    });
    await _refreshCameraDataAndDraw();
    _bindVideoEvents();
}

async function _refreshCameraDataAndDraw() {
    const pid = AppState.currentProject;
    // Load legs for the Add-Missed form
    try {
        const cal = await API.get(`/api/projects/${pid}/cameras/${_pbActiveCameraId}/calibration`);
        _pbLegs = cal.legs || [];
    } catch (e) {
        _pbLegs = [];
    }
    // Load events for this camera (all pages — typically small)
    _pbEvents = await _fetchAllEvents(pid, _pbActiveCameraId);
    // Set the video source — the F3 range-capable stream endpoint
    // (plan_f3_playback_studio_2026-07-28; the browser handles seeking
    // via HTTP Range requests).
    const video = document.getElementById('pb-video');
    if (video && _pbVideos[_pbActiveVideoIdx]) {
        const v = _pbVideos[_pbActiveVideoIdx];
        video.src = `/api/projects/${pid}/videos/${v.video_id}/stream`;
        video.poster = `/api/projects/${pid}/videos/${v.video_id}/frame?seconds=0`;
    }
    await _refreshCountsPanel();
    _drawOverlay();
}

async function _fetchAllEvents(pid, camId) {
    // The review endpoint returns paginated events; pull them all here.
    let all = [];
    let page = 1;
    while (true) {
        const resp = await API.get(`/api/projects/${pid}/review?page=${page}&page_size=200`);
        // Filter by camera client-side (the review endpoint isn't camera-aware yet)
        const events = (resp.events || []).filter(e => {
            // Need to join to a camera. The review router currently doesn't
            // expose camera_id directly; events from this camera will share
            // the legs that belong to camera_id == camId. So we keep events
            // whose origin_leg matches one of the active camera's legs.
            return _pbLegs.some(l => l.leg_id === e.origin_leg_id);
        });
        all = all.concat(events);
        if (resp.page >= resp.pages || (resp.events || []).length === 0) break;
        page += 1;
    }
    return all;
}

async function _refreshCountsPanel() {
    const pid = AppState.currentProject;
    const iid = _pbIntersection.intersection.intersection_id;
    let summary;
    try {
        summary = await API.get(`/api/projects/${pid}/intersections/${iid}/summary`);
    } catch (e) {
        document.getElementById('pb-counts').innerHTML = '<p class="helper-text">Could not load counts.</p>';
        return;
    }
    let html = `<div class="pb-total">${summary.totals.vehicles} vehicles total</div>`;
    html += '<table class="pb-counts-table"><thead><tr><th>Leg</th><th>T</th><th>L</th><th>R</th><th>U</th></tr></thead><tbody>';
    for (const row of summary.tmc_matrix) {
        html += `<tr><td>${escapeHtml(row.leg_label)}</td>
            <td>${row.through}</td><td>${row.left}</td>
            <td>${row.right}</td><td>${row.u_turn}</td></tr>`;
    }
    html += '</tbody></table>';
    if (summary.dedup_summary && summary.dedup_summary.merged) {
        html += `<p class="helper-text">${summary.dedup_summary.merged} duplicates collapsed across cameras.</p>`;
    }
    document.getElementById('pb-counts').innerHTML = html;
}

function _bindVideoEvents() {
    const video = document.getElementById('pb-video');
    const canvas = document.getElementById('pb-overlay');
    if (!video || !canvas) return;
    // Re-sync canvas size to video natural dimensions when metadata loads
    video.addEventListener('loadedmetadata', () => {
        canvas.width = video.videoWidth || 640;
        canvas.height = video.videoHeight || 360;
    });
    video.addEventListener('timeupdate', _drawOverlay);
    video.addEventListener('seeked', _drawOverlay);
    // Click-to-reject / click-to-add
    canvas.addEventListener('click', _onCanvasClick);
}

function _drawOverlay() {
    const video = document.getElementById('pb-video');
    const canvas = document.getElementById('pb-overlay');
    if (!canvas || !video) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const t = video.currentTime || 0;
    const active = _pbEvents.filter(e =>
        Math.abs((e.timestamp_video || 0) - t) <= EVENT_TIME_WINDOW_SECONDS
        && !e.rejected
    );
    // Update active-events panel
    const panel = document.getElementById('pb-active-events');
    const count = document.getElementById('pb-active-count');
    if (count) count.textContent = `(${active.length})`;
    if (panel) {
        panel.innerHTML = active.map(e => `
            <div class="pb-active-event">
                <span><strong>${escapeHtml(e.leg_label)}</strong> ${escapeHtml(e.movement)}</span>
                <button class="btn-secondary" onclick="pbRejectEvent(${e.event_id})">Reject</button>
            </div>`).join('') || '<p class="helper-text">No events in this window.</p>';
    }

    // Draw trajectory polylines + clickable end-circles for active events.
    // We don't have bbox-per-frame; we use the event's trajectory_data and
    // mark the end point as the clickable target.
    for (const e of active) {
        const traj = _safeParseJson(e.trajectory_data) || [];
        if (traj.length >= 2) {
            ctx.strokeStyle = 'rgba(0, 200, 255, 0.85)';
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.moveTo(traj[0][0], traj[0][1]);
            for (let i = 1; i < traj.length; i++) {
                ctx.lineTo(traj[i][0], traj[i][1]);
            }
            ctx.stroke();
        }
        if (traj.length >= 1) {
            const last = traj[traj.length - 1];
            ctx.fillStyle = 'rgba(255, 0, 0, 0.85)';
            ctx.beginPath();
            ctx.arc(last[0], last[1], 10, 0, Math.PI * 2);
            ctx.fill();
            // Stash for hit-testing
            e._click_x = last[0];
            e._click_y = last[1];
        }
    }
}

function _safeParseJson(s) {
    try { return JSON.parse(s); } catch (_) { return null; }
}

function _onCanvasClick(ev) {
    const canvas = document.getElementById('pb-overlay');
    const video = document.getElementById('pb-video');
    const rect = canvas.getBoundingClientRect();
    // Map the click from CSS pixels to canvas internal pixels
    const x = (ev.clientX - rect.left) * (canvas.width / rect.width);
    const y = (ev.clientY - rect.top) * (canvas.height / rect.height);
    // Hit-test against active event circles (10px radius)
    const t = video.currentTime || 0;
    const active = _pbEvents.filter(e =>
        Math.abs((e.timestamp_video || 0) - t) <= EVENT_TIME_WINDOW_SECONDS && !e.rejected
    );
    for (const e of active) {
        if (e._click_x !== undefined) {
            const dx = e._click_x - x, dy = e._click_y - y;
            if (dx * dx + dy * dy <= 15 * 15) {
                pbRejectEvent(e.event_id);
                return;
            }
        }
    }
    // Empty area → open add-missed form positioned at the click
    _openAddMissedForm(x, y, t);
}

function _openAddMissedForm(x, y, timestamp) {
    const form = document.getElementById('pb-add-form');
    if (!form) return;
    const legOptions = _pbLegs.map(l =>
        `<option value="${l.leg_id}">${escapeHtml(l.label)} (${escapeHtml(l.cardinal_direction)})</option>`
    ).join('');
    form.innerHTML = `
        <h4>Add missed vehicle</h4>
        <div>Position: (${x.toFixed(0)}, ${y.toFixed(0)}) at ${timestamp.toFixed(1)}s</div>
        <label>Origin leg
            <select id="pb-add-leg">${legOptions}</select>
        </label>
        <label>Movement
            <select id="pb-add-mov">
                <option value="through">Through</option>
                <option value="left">Left</option>
                <option value="right">Right</option>
                <option value="u_turn">U-turn</option>
            </select>
        </label>
        <div class="pb-add-actions">
            <button onclick="pbConfirmAddMissed(${x}, ${y}, ${timestamp})">Add</button>
            <button class="btn-secondary" onclick="pbCancelAddMissed()">Cancel</button>
        </div>`;
    form.classList.remove('hidden');
}

async function pbConfirmAddMissed(x, y, timestamp) {
    const pid = AppState.currentProject;
    const legSel = document.getElementById('pb-add-leg');
    const movSel = document.getElementById('pb-add-mov');
    if (!legSel || !movSel) return;
    const v = _pbVideos[_pbActiveVideoIdx];

    let ev;
    try {
        ev = await API.post(`/api/projects/${pid}/review`, {
            origin_leg_id: Number(legSel.value),
            movement: movSel.value,
            timestamp_video: timestamp,
            video_id: v ? v.video_id : null,
            x, y,
        });
    } catch (e) {
        alert(`Failed to add vehicle: ${e.message || e}`);
        return;
    }
    // Add to local state so it draws immediately and counts update live.
    _pbEvents.push(ev);
    await _refreshCountsPanel();
    _drawOverlay();
    pbCancelAddMissed();
}

function pbCancelAddMissed() {
    const form = document.getElementById('pb-add-form');
    if (form) form.classList.add('hidden');
}

async function pbRejectEvent(eventId) {
    if (!window.confirm('Reject this detection?')) return;
    const pid = AppState.currentProject;
    try {
        await API.patch(`/api/projects/${pid}/review/${eventId}`, { rejected: true });
    } catch (e) {
        alert(`Failed: ${e.message || e}`);
        return;
    }
    // Update local state and re-draw
    const ev = _pbEvents.find(e => e.event_id === eventId);
    if (ev) ev.rejected = 1;
    await _refreshCountsPanel();
    _drawOverlay();
}

function pbDownloadExcel() {
    const pid = AppState.currentProject;
    const iid = _pbIntersection.intersection.intersection_id;
    window.location.href = `/api/projects/${pid}/intersections/${iid}/export/xlsx`;
}

function backToProjectFromPlayback() {
    _stopLivePolling();
    _setLivePreviewActive(false);
    AppState.currentIntersectionId = null;
    showPage('page-setup');
    if (typeof loadSetupPage === 'function') loadSetupPage();
}

// --- Live polling while the orchestrator is running -----------------------

async function _startLivePollingIfRunning() {
    _stopLivePolling();
    const status = await _fetchLiveStatus();
    if (!status || status.status !== 'running') {
        _updateLiveBanner(status);
        _setLivePreviewActive(false);
        return;
    }
    _updateLiveBanner(status);
    _setLivePreviewActive(true);
    _pbLiveTimer = setInterval(_liveTick, LIVE_POLL_INTERVAL_MS);
}

function _setLivePreviewActive(active) {
    const video = document.getElementById('pb-video');
    const liveImg = document.getElementById('pb-live-frame');
    if (!video || !liveImg) return;
    if (active) {
        const pid = AppState.currentProject;
        const iid = _pbIntersection?.intersection?.intersection_id;
        if (!pid || !iid) return;
        liveImg.src = `/api/projects/${pid}/intersections/${iid}/processing/preview-stream?_t=${Date.now()}`;
        liveImg.classList.remove('hidden');
        video.classList.add('hidden');
    } else {
        if (liveImg.src) liveImg.src = '';  // close the MJPEG connection
        liveImg.classList.add('hidden');
        video.classList.remove('hidden');
    }
}

function _stopLivePolling() {
    if (_pbLiveTimer) {
        clearInterval(_pbLiveTimer);
        _pbLiveTimer = null;
    }
}

async function _fetchLiveStatus() {
    const pid = AppState.currentProject;
    const iid = _pbIntersection?.intersection?.intersection_id;
    if (!pid || !iid) return null;
    try {
        return await API.get(`/api/projects/${pid}/intersections/${iid}/processing/status`);
    } catch (_) {
        return null;
    }
}

async function _liveTick() {
    const status = await _fetchLiveStatus();
    _updateLiveBanner(status);
    if (!status || status.status !== 'running') {
        _stopLivePolling();
        _setLivePreviewActive(false);
    }
    const pid = AppState.currentProject;
    await _refreshCountsPanel();
    try {
        _pbEvents = await _fetchAllEvents(pid, _pbActiveCameraId);
    } catch (_) { /* keep stale events */ }
    _drawOverlay();
}

function _updateLiveBanner(status) {
    const el = document.getElementById('pb-live-banner');
    if (!el) return;
    if (!status || status.status !== 'running') {
        el.classList.add('hidden');
        el.innerHTML = '';
        return;
    }
    const segCount = status.segment_count || 0;
    const cur = (status.current_segment_index || 0) + 1;
    const cancelling = status.cancel_requested ? ' — cancelling…' : '';
    el.classList.remove('hidden');
    el.innerHTML = `
        <span class="pb-live-dot"></span>
        <span style="flex:1;">Processing live — segment ${cur} of ${segCount}${cancelling}.
            Counts refresh every ${LIVE_POLL_INTERVAL_MS / 1000}s.</span>
        <button class="btn-secondary pb-live-cancel"
                onclick="pbCancelLive()" ${status.cancel_requested ? 'disabled' : ''}>
            Cancel
        </button>`;
}

window.pbCancelLive = async function () {
    if (!window.confirm('Stop processing this intersection now? Counts already finalized will be kept.')) return;
    const pid = AppState.currentProject;
    const iid = _pbIntersection?.intersection?.intersection_id;
    if (!pid || !iid) return;
    try {
        await API.post(`/api/projects/${pid}/intersections/${iid}/processing/cancel`, {});
    } catch (e) {
        alert(`Cancel failed: ${e.message || e}`);
        return;
    }
    // Refresh the banner immediately so the user sees the cancelling state
    // without waiting for the next poll tick.
    const status = await _fetchLiveStatus();
    _updateLiveBanner(status);
};

if (typeof registerTeardown === 'function') {
    registerTeardown('page-v3-playback', _stopLivePolling);
}
