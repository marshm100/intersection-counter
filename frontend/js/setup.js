// v3 project page — three-tab layout (Videos | Intersections | Processing).
//
// Tab 1 (Videos):       bulk-upload + labeling table; save derives intersections.
// Tab 2 (Intersections): grid of cards (one per intersection-day);
//                        click a card to drill in (Phase 7 wires sub-tabs).
// Tab 3 (Processing):   in-flight jobs (Phase 8 wires real-time status).

let _v3ActiveTab = 'videos';
let _v3Project = null;
let _v3Videos = [];

// Intersection-detail drill-in state (Phase 7).
// When non-null, the Intersections tab shows the detail view instead of the grid.
let _v3OpenIntersectionId = null;
let _v3IntersectionDetail = null;
let _v3DetailSubTab = 'settings';

async function loadSetupPage() {
    const pid = AppState.currentProject;
    if (!pid) { showPage('page-projects'); loadProjectList(); return; }

    const section = document.getElementById('page-setup');
    section.innerHTML = '<p class="empty-message">Loading...</p>';

    try {
        _v3Project = await API.get(`/api/projects/${pid}`);
    } catch (e) {
        section.innerHTML = '<p class="empty-message">Could not load project.</p>';
        return;
    }

    section.innerHTML = _projectHeaderHtml() + _tabBarHtml() + '<div id="v3-tab-content"></div>';

    // Header name input binding
    const nameInput = document.getElementById('setup-project-name');
    if (nameInput) {
        nameInput.removeEventListener('blur', saveProjectName);
        nameInput.removeEventListener('keydown', _onSetupNameKeydown);
        nameInput.addEventListener('blur', saveProjectName);
        nameInput.addEventListener('keydown', _onSetupNameKeydown);
    }

    await _renderActiveTab();
}

function _projectHeaderHtml() {
    return `
        <div class="setup-header">
            <a href="#" class="back-link" onclick="backToProjects(); return false;">&larr; Back to Projects</a>
            <div class="setup-name-row">
                <input type="text" id="setup-project-name" class="setup-name-input"
                       value="${escapeAttr(_v3Project.project_name || '')}" />
            </div>
        </div>`;
}

function _tabBarHtml() {
    const tabs = [
        { id: 'videos',        label: 'Videos' },
        { id: 'intersections', label: 'Intersections' },
        { id: 'processing',    label: 'Processing' },
    ];
    return '<div class="v3-tabbar">' + tabs.map(t =>
        `<button class="v3-tab ${_v3ActiveTab === t.id ? 'active' : ''}"
                 onclick="v3SwitchTab('${t.id}')">${t.label}</button>`
    ).join('') + '</div>';
}

async function v3SwitchTab(tabId) {
    _v3ActiveTab = tabId;
    // Re-render only the tab bar buttons + content, not the header.
    const tabBar = document.querySelector('.v3-tabbar');
    if (tabBar) tabBar.outerHTML = _tabBarHtml();
    await _renderActiveTab();
}

async function _renderActiveTab() {
    const host = document.getElementById('v3-tab-content');
    if (!host) return;
    if (_v3ActiveTab === 'videos') {
        await _renderVideosTab(host);
    } else if (_v3ActiveTab === 'intersections') {
        await _renderIntersectionsTab(host);
    } else if (_v3ActiveTab === 'processing') {
        await _renderProcessingTab(host);
    }
}

// --- Videos tab --------------------------------------------------------

async function _renderVideosTab(host) {
    const pid = AppState.currentProject;
    host.innerHTML = '<p class="empty-message">Loading videos...</p>';

    try {
        _v3Videos = await API.get(`/api/projects/${pid}/videos`);
    } catch (e) {
        host.innerHTML = '<p class="empty-message">Could not load videos.</p>';
        return;
    }

    let html = `
        <div class="videos-tab-actions">
            <button class="video-select-btn" onclick="v3PickVideos()">+ Upload videos</button>
            <span class="helper-text">Drag and drop multiple files; the system auto-fills camera, date, and start time from the filename.</span>
            <button class="btn-save-labels" onclick="v3SaveLabels()" ${_v3Videos.length === 0 ? 'disabled' : ''}>
                Save labels &amp; build intersections
            </button>
        </div>`;

    if (_v3Videos.length === 0) {
        html += '<p class="empty-message">No videos uploaded yet. Click "Upload videos" to attach files.</p>';
        host.innerHTML = html;
        return;
    }

    html += '<table class="videos-table">';
    html += '<thead><tr>';
    html += '<th>File</th><th>Camera</th><th>Date</th><th>Start time</th><th>Intersection</th><th>Duration</th><th>Confidence</th><th>Actions</th>';
    html += '</tr></thead><tbody>';
    for (const v of _v3Videos) {
        html += _videosTableRowHtml(v);
    }
    html += '</tbody></table>';
    host.innerHTML = html;
}

function _videosTableRowHtml(v) {
    const dt = v.recording_start_datetime ? String(v.recording_start_datetime).substring(0, 16) : '';
    const datePart = dt ? dt.substring(0, 10) : '';
    const timePart = dt ? dt.substring(11, 16) : '';
    const conf = (v.parse_confidence != null) ? v.parse_confidence : 1.0;
    const lowConf = conf < 0.5;
    const durMin = v.duration_seconds ? (v.duration_seconds / 60).toFixed(1) + ' min' : '?';
    return `
        <tr class="${lowConf ? 'video-row-low-conf' : ''}" data-video-id="${v.video_id}">
            <td class="videos-filename" title="${escapeAttr(v.path)}">${escapeHtml(v.filename)}</td>
            <td>
                <input type="text" class="cell-input" value="${escapeAttr(v.camera_label_parsed || '')}"
                    onchange="v3PatchLabel(${v.video_id}, 'camera_label', this.value)" />
            </td>
            <td>
                <input type="date" class="cell-input" value="${escapeAttr(datePart)}"
                    onchange="v3PatchDateTime(${v.video_id}, this.value, null)" />
            </td>
            <td>
                <input type="time" step="1" class="cell-input"
                    value="${escapeAttr(timePart ? timePart + ':00' : '')}"
                    onchange="v3PatchDateTime(${v.video_id}, null, this.value)" />
            </td>
            <td>
                <input type="text" class="cell-input cell-input-wide"
                    value="${escapeAttr(v.intersection_name_label || '')}"
                    placeholder="Required"
                    onchange="v3PatchLabel(${v.video_id}, 'intersection_name', this.value)" />
            </td>
            <td>${durMin}</td>
            <td class="${lowConf ? 'confidence-low' : ''}">
                ${(conf * 100).toFixed(0)}%${lowConf ? ' ⚠' : ''}
            </td>
            <td>
                <button class="btn-remove-video" onclick="v3RemoveVideo(${v.video_id}, '${escapeAttr(v.filename)}')">Remove</button>
            </td>
        </tr>`;
}

async function v3PickVideos() {
    const pid = AppState.currentProject;
    let browse;
    try {
        browse = await API.post(`/api/projects/${pid}/videos/browse-multi`);
    } catch (e) {
        alert('Could not open file browser.');
        return;
    }
    const paths = (browse && browse.paths) ? browse.paths : [];
    if (paths.length === 0) return;

    let resp;
    try {
        resp = await API.post(`/api/projects/${pid}/videos/bulk`, { paths });
    } catch (e) {
        alert(`Failed to attach videos: ${e.message || e}`);
        return;
    }
    const errors = (resp.results || []).filter(r => r.error);
    if (errors.length > 0) {
        alert(`Some files could not be attached:\n\n` +
              errors.map(e => `${e.path}: ${e.error}`).join('\n'));
    }
    await _renderVideosTab(document.getElementById('v3-tab-content'));
}

async function v3PatchLabel(videoId, field, value) {
    const pid = AppState.currentProject;
    const body = {};
    if (field === 'camera_label') body.camera_label = value;
    if (field === 'intersection_name') body.intersection_name = value;
    try {
        await API.patch(`/api/projects/${pid}/videos/${videoId}/labels`, body);
    } catch (e) {
        alert(`Failed to save: ${e.message || e}`);
    }
}

async function v3PatchDateTime(videoId, datePart, timePart) {
    // Combine date + time into ISO format. Fetch the current value to fill
    // in whichever part wasn't supplied by this edit.
    const pid = AppState.currentProject;
    const v = _v3Videos.find(x => x.video_id === videoId);
    const existing = v && v.recording_start_datetime ? String(v.recording_start_datetime) : '';
    const existingDate = existing.substring(0, 10);
    const existingTime = existing.substring(11, 19);
    const finalDate = datePart != null ? datePart : existingDate;
    const finalTime = timePart != null ? timePart : existingTime;
    if (!finalDate || !finalTime) return;
    const iso = `${finalDate}T${finalTime.length === 5 ? finalTime + ':00' : finalTime}`;
    try {
        const updated = await API.patch(
            `/api/projects/${pid}/videos/${videoId}/labels`,
            { recording_start_datetime: iso },
        );
        // Update local cache so the next partial edit sees the new full value
        if (v) v.recording_start_datetime = updated.recording_start_datetime;
    } catch (e) {
        alert(`Failed to save: ${e.message || e}`);
    }
}

async function v3RemoveVideo(videoId, filename) {
    const pid = AppState.currentProject;
    if (!window.confirm(`Remove "${filename}" from this project?`)) return;
    try {
        const result = await API.del(`/api/projects/${pid}/videos/${videoId}`);
        if (result && result.confirm_required) {
            if (!window.confirm(result.warning + '\n\nProceed?')) return;
            await API.del(`/api/projects/${pid}/videos/${videoId}?confirm=true`);
        }
    } catch (e) {
        alert(`Failed to remove: ${e.message || e}`);
        return;
    }
    await _renderVideosTab(document.getElementById('v3-tab-content'));
}

async function v3SaveLabels() {
    const pid = AppState.currentProject;
    let resp;
    try {
        resp = await API.post(`/api/projects/${pid}/videos/save-labels`);
    } catch (e) {
        alert(`Save failed: ${e.message || e}`);
        return;
    }
    const summary = `Built ${resp.intersections.length} intersection-day card(s).\n` +
                    `Attached: ${resp.videos_attached}\n` +
                    (resp.videos_skipped ? `Skipped (missing intersection name): ${resp.videos_skipped}` : '');
    alert(summary);
    // Auto-switch to the Intersections tab so the user sees their cards
    await v3SwitchTab('intersections');
}

// --- Intersections tab (Phase 7 fleshes out) --------------------------

async function _renderIntersectionsTab(host) {
    // When a card is opened, switch into the detail view.
    if (_v3OpenIntersectionId !== null) {
        await _renderIntersectionDetail(host);
        return;
    }

    const pid = AppState.currentProject;
    host.innerHTML = '<p class="empty-message">Loading intersections...</p>';
    let intersections;
    try {
        intersections = await API.get(`/api/projects/${pid}/intersections`);
    } catch (e) {
        host.innerHTML = '<p class="empty-message">Could not load intersections.</p>';
        return;
    }
    if (intersections.length === 0) {
        host.innerHTML = `
            <p class="empty-message">
                No intersections yet. Upload videos in the Videos tab, label each
                with its intersection name, and click "Save labels &amp; build intersections."
            </p>`;
        return;
    }
    let html = '<div class="intersection-grid">';
    for (const i of intersections) {
        html += `
            <div class="intersection-card">
                <h3>${escapeHtml(i.name)}</h3>
                <div class="intersection-card-meta">
                    <span>Date: ${escapeHtml(i.date)}</span>
                    <span>Legs: ${i.leg_count}</span>
                </div>
                <div class="intersection-card-actions">
                    <button onclick="v3OpenIntersection(${i.intersection_id})">Open</button>
                </div>
            </div>`;
    }
    html += '</div>';
    host.innerHTML = html;
}

async function v3OpenIntersection(iid) {
    _v3OpenIntersectionId = iid;
    _v3DetailSubTab = 'settings';
    await _renderIntersectionsTab(document.getElementById('v3-tab-content'));
}

function v3CloseIntersection() {
    _v3OpenIntersectionId = null;
    _v3IntersectionDetail = null;
    _renderIntersectionsTab(document.getElementById('v3-tab-content'));
}

async function _renderIntersectionDetail(host) {
    const pid = AppState.currentProject;
    const iid = _v3OpenIntersectionId;
    host.innerHTML = '<p class="empty-message">Loading intersection...</p>';

    try {
        _v3IntersectionDetail = await API.get(`/api/projects/${pid}/intersections/${iid}`);
    } catch (e) {
        host.innerHTML = '<p class="empty-message">Could not load intersection.</p>';
        return;
    }

    const i = _v3IntersectionDetail.intersection;
    const subTabs = [
        { id: 'settings', label: 'Intersection settings' },
        { id: 'cameras',  label: 'Cameras' },
        { id: 'trims',    label: 'Clip trim' },
    ];

    let html = '';
    html += `<div class="isect-detail-header">`;
    html += `<a href="#" class="back-link" onclick="v3CloseIntersection(); return false;">&larr; Back to intersections</a>`;
    html += `<h2 class="isect-detail-title">${escapeHtml(i.name)} <span class="isect-detail-date">— ${escapeHtml(i.date)}</span></h2>`;
    html += `</div>`;

    html += '<div class="v3-subtabbar">' + subTabs.map(t =>
        `<button class="v3-subtab ${_v3DetailSubTab === t.id ? 'active' : ''}"
                 onclick="v3SwitchDetailSubTab('${t.id}')">${t.label}</button>`
    ).join('') + '</div>';

    html += `<div id="v3-detail-subcontent"></div>`;
    html += `<div class="isect-detail-footer">
        <button class="btn-confirm-process" onclick="v3ConfirmProcess()">Confirm &amp; process</button>
        <button class="btn-secondary" onclick="v3CloseIntersection()">Done</button>
    </div>`;
    host.innerHTML = html;

    await _renderDetailSubTab();
}

async function v3SwitchDetailSubTab(tabId) {
    _v3DetailSubTab = tabId;
    const bar = document.querySelector('.v3-subtabbar');
    if (bar) {
        bar.querySelectorAll('.v3-subtab').forEach(b => {
            b.classList.toggle('active', b.textContent.toLowerCase().startsWith(_subTabHeader(tabId)));
        });
    }
    await _renderDetailSubTab();
}

function _subTabHeader(tabId) {
    return ({ settings: 'intersection', cameras: 'cameras', trims: 'clip' })[tabId] || tabId;
}

async function _renderDetailSubTab() {
    const host = document.getElementById('v3-detail-subcontent');
    if (!host) return;
    if (_v3DetailSubTab === 'settings') {
        await _renderSettingsSubTab(host);
    } else if (_v3DetailSubTab === 'cameras') {
        await _renderCamerasSubTab(host);
    } else if (_v3DetailSubTab === 'trims') {
        await _renderTrimsSubTab(host);
    }
}

// --- Sub-tab: Intersection settings -----------------------------------

async function _renderSettingsSubTab(host) {
    const i = _v3IntersectionDetail.intersection;
    host.innerHTML = `
        <div class="settings-pane">
            <div class="settings-row">
                <label for="isect-name">Intersection name</label>
                <input type="text" id="isect-name" value="${escapeAttr(i.name)}"
                       onchange="v3PatchIntersection({name: this.value})" />
            </div>
            <div class="settings-row">
                <label for="isect-leg-count">Number of legs</label>
                <input type="number" id="isect-leg-count" min="2" max="8" value="${i.leg_count}"
                       onchange="v3PatchIntersection({leg_count: parseInt(this.value, 10)})" />
                <span class="helper-text">Default 4. T-junctions use 3; complex intersections may have 5+.</span>
            </div>
            <div class="settings-row">
                <label>Cameras</label>
                <span>${_v3IntersectionDetail.cameras.length} configured</span>
            </div>
            <div class="settings-row">
                <label>Trims</label>
                <span>${_v3IntersectionDetail.trims.length} defined</span>
            </div>
        </div>`;
}

async function v3PatchIntersection(body) {
    const pid = AppState.currentProject;
    const iid = _v3OpenIntersectionId;
    try {
        const updated = await API.patch(`/api/projects/${pid}/intersections/${iid}`, body);
        if (_v3IntersectionDetail) _v3IntersectionDetail.intersection = updated;
    } catch (e) {
        alert(`Failed to save: ${e.message || e}`);
    }
}

// --- Sub-tab: Cameras --------------------------------------------------

async function _renderCamerasSubTab(host) {
    const pid = AppState.currentProject;
    const iid = _v3OpenIntersectionId;
    host.innerHTML = '<p class="empty-message">Loading cameras...</p>';

    let cameras;
    try {
        cameras = await API.get(`/api/projects/${pid}/intersections/${iid}/cameras`);
    } catch (e) {
        host.innerHTML = '<p class="empty-message">Could not load cameras.</p>';
        return;
    }

    // For each camera, query its calibration so we can show "configured / not yet"
    const calibrated = {};
    for (const c of cameras) {
        try {
            const r = await API.get(`/api/projects/${pid}/cameras/${c.camera_id}/calibration`);
            calibrated[c.camera_id] = r.legs.length > 0;
        } catch (e) {
            calibrated[c.camera_id] = false;
        }
    }

    if (cameras.length === 0) {
        host.innerHTML = '<p class="empty-message">No cameras for this intersection. Attach videos with this intersection name in the Videos tab.</p>';
        return;
    }

    let html = '<table class="cameras-table">';
    html += '<thead><tr><th>Camera label</th><th>Videos</th><th>Calibration</th><th>Actions</th></tr></thead><tbody>';
    for (const c of cameras) {
        const isCalibrated = calibrated[c.camera_id];
        html += `<tr>
            <td>
                <input type="text" class="cell-input" value="${escapeAttr(c.label)}"
                    onchange="v3RenameCamera(${c.camera_id}, this.value)" />
            </td>
            <td>${(c.videos || []).length}</td>
            <td>${isCalibrated ? '<span class="status-ok">✓ Configured</span>' : '<span class="status-warn">Not configured</span>'}</td>
            <td>
                <button onclick="v3CalibrateCamera(${c.camera_id})">${isCalibrated ? 'Recalibrate' : 'Calibrate'}</button>
                <button class="btn-remove-video" onclick="v3DeleteCamera(${c.camera_id}, '${escapeAttr(c.label)}')">Remove</button>
            </td>
        </tr>`;
    }
    html += '</tbody></table>';
    host.innerHTML = html;
}

async function v3RenameCamera(camId, label) {
    const pid = AppState.currentProject;
    const iid = _v3OpenIntersectionId;
    try {
        await API.patch(
            `/api/projects/${pid}/intersections/${iid}/cameras/${camId}`,
            { label },
        );
    } catch (e) {
        alert(`Failed to rename: ${e.message || e}`);
    }
}

async function v3DeleteCamera(camId, label) {
    if (!window.confirm(`Remove camera "${label}"? Its calibration and events will be deleted.`)) return;
    const pid = AppState.currentProject;
    const iid = _v3OpenIntersectionId;
    try {
        await API.del(`/api/projects/${pid}/intersections/${iid}/cameras/${camId}`);
    } catch (e) {
        alert(`Failed to delete: ${e.message || e}`);
        return;
    }
    await _renderCamerasSubTab(document.getElementById('v3-detail-subcontent'));
}

function v3CalibrateCamera(camId) {
    // Stash the camera_id in AppState so the existing calibration page can
    // detect v3 camera-scoped mode. Full camera-aware calibration UI lives
    // in Phase 10's polish pass; for now we navigate to the calibration
    // page and the user works with the camera-scoped endpoints.
    AppState.currentCameraId = camId;
    showPage('page-calibration');
    if (typeof loadCalibrationPage === 'function') {
        loadCalibrationPage();
    }
}

// --- Sub-tab: Clip trim -----------------------------------------------

async function _renderTrimsSubTab(host) {
    const pid = AppState.currentProject;
    const iid = _v3OpenIntersectionId;
    host.innerHTML = '<p class="empty-message">Loading trims...</p>';

    let trims, report;
    try {
        [trims, report] = await Promise.all([
            API.get(`/api/projects/${pid}/intersections/${iid}/trims`),
            API.get(`/api/projects/${pid}/intersections/${iid}/coverage-report`),
        ]);
    } catch (e) {
        host.innerHTML = '<p class="empty-message">Could not load trims.</p>';
        return;
    }

    let html = `<div class="trims-actions">
        <button onclick="v3AddTrim()">+ Add trim</button>
        <span class="helper-text">Each trim is a wall-clock window (HH:MM:SS) processed across all cameras at this intersection.</span>
    </div>`;

    if (trims.length === 0) {
        html += '<p class="empty-message">No trims defined. Add at least one to enable processing.</p>';
        host.innerHTML = html;
        return;
    }

    html += '<table class="trims-table">';
    html += '<thead><tr><th>Start</th><th>End</th><th>Coverage</th><th>Actions</th></tr></thead><tbody>';
    const reportByTrim = {};
    for (const r of (report.per_trim || [])) reportByTrim[r.trim_id] = r;
    for (const t of trims) {
        const r = reportByTrim[t.trim_id];
        const status = r
            ? (r.is_fully_covered
                ? '<span class="status-ok">Fully covered</span>'
                : `<span class="status-error">Gaps: ${r.gaps.length}</span>`)
            : '—';
        html += `<tr>
            <td>
                <input type="time" step="1" class="cell-input"
                    value="${escapeAttr(t.start_wallclock)}"
                    onchange="v3PatchTrim(${t.trim_id}, {start_wallclock: this.value + (this.value.length===5?':00':'')})" />
            </td>
            <td>
                <input type="time" step="1" class="cell-input"
                    value="${escapeAttr(t.end_wallclock)}"
                    onchange="v3PatchTrim(${t.trim_id}, {end_wallclock: this.value + (this.value.length===5?':00':'')})" />
            </td>
            <td>${status}</td>
            <td>
                <button class="btn-remove-video" onclick="v3DeleteTrim(${t.trim_id})">Remove</button>
            </td>
        </tr>`;
    }
    html += '</tbody></table>';

    // Coverage visualizer (text-mode for Phase 7; richer Gantt comes in Phase 10)
    html += '<h4 style="margin-top:16px;">Per-camera coverage</h4>';
    if (!report.per_camera || report.per_camera.length === 0) {
        html += '<p class="helper-text">No cameras with usable video metadata yet.</p>';
    } else {
        html += '<ul class="coverage-list">';
        for (const cam of report.per_camera) {
            html += `<li>Camera ${cam.camera_id}: ` + cam.intervals.map(iv => {
                const s = iv.start.substring(11, 19);
                const e = iv.end.substring(11, 19);
                return `${s}–${e}`;
            }).join(', ') + '</li>';
        }
        html += '</ul>';
    }

    host.innerHTML = html;
}

async function v3AddTrim() {
    const start = prompt('Trim start (HH:MM:SS)', '07:00:00');
    if (!start) return;
    const end = prompt('Trim end (HH:MM:SS)', '09:00:00');
    if (!end) return;
    const pid = AppState.currentProject;
    const iid = _v3OpenIntersectionId;
    try {
        await API.post(
            `/api/projects/${pid}/intersections/${iid}/trims`,
            { start_wallclock: start, end_wallclock: end },
        );
    } catch (e) {
        alert(`Failed to add trim: ${e.message || e}`);
        return;
    }
    await _renderTrimsSubTab(document.getElementById('v3-detail-subcontent'));
}

async function v3PatchTrim(tid, body) {
    const pid = AppState.currentProject;
    const iid = _v3OpenIntersectionId;
    try {
        await API.patch(
            `/api/projects/${pid}/intersections/${iid}/trims/${tid}`,
            body,
        );
        // Re-render so coverage status updates
        await _renderTrimsSubTab(document.getElementById('v3-detail-subcontent'));
    } catch (e) {
        alert(`Failed to save trim: ${e.message || e}`);
    }
}

async function v3DeleteTrim(tid) {
    if (!window.confirm('Remove this trim?')) return;
    const pid = AppState.currentProject;
    const iid = _v3OpenIntersectionId;
    try {
        await API.del(`/api/projects/${pid}/intersections/${iid}/trims/${tid}`);
    } catch (e) {
        alert(`Failed to delete: ${e.message || e}`);
        return;
    }
    await _renderTrimsSubTab(document.getElementById('v3-detail-subcontent'));
}

// --- Confirm & process popup ------------------------------------------

async function v3ConfirmProcess() {
    const pid = AppState.currentProject;
    const iid = _v3OpenIntersectionId;
    let preflight;
    try {
        preflight = await API.post(
            `/api/projects/${pid}/intersections/${iid}/processing/preflight`,
            {},
        );
    } catch (e) {
        alert(`Preflight failed: ${e.message || e}`);
        return;
    }
    if (!preflight.ok) {
        alert('Cannot process — please fix these first:\n\n' + preflight.errors.join('\n'));
        return;
    }
    const msg = `Ready to process this intersection.\n\n` +
                `Segments: ${preflight.segment_count}\n` +
                `Cameras used: ${preflight.cameras_used.length}\n` +
                `Trims: ${preflight.trims_used.length}\n\n` +
                `Start processing now?`;
    if (!window.confirm(msg)) return;
    try {
        await API.post(`/api/projects/${pid}/intersections/${iid}/processing/start`, {});
    } catch (e) {
        alert(`Start failed: ${e.message || e}`);
        return;
    }
    alert('Processing started. Switch to the Processing tab to monitor progress.');
    v3CloseIntersection();
    await v3SwitchTab('processing');
}

// --- Processing tab (Phase 8 fleshes out) -----------------------------

let _v3ProcessingPollTimer = null;

async function _renderProcessingTab(host) {
    await _refreshProcessingChips(host);
    // Start polling so status updates without manual refresh.
    if (_v3ProcessingPollTimer) clearInterval(_v3ProcessingPollTimer);
    _v3ProcessingPollTimer = setInterval(() => {
        // Only poll while the Processing tab is the active tab.
        if (_v3ActiveTab === 'processing') {
            _refreshProcessingChips(host);
        } else {
            clearInterval(_v3ProcessingPollTimer);
            _v3ProcessingPollTimer = null;
        }
    }, 2000);
}

async function _refreshProcessingChips(host) {
    const pid = AppState.currentProject;
    let intersections;
    try {
        intersections = await API.get(`/api/projects/${pid}/intersections`);
    } catch (e) {
        host.innerHTML = '<p class="empty-message">Could not load intersections.</p>';
        return;
    }
    if (intersections.length === 0) {
        host.innerHTML = '<p class="empty-message">No intersections to process yet. Go to the Videos tab to upload and label.</p>';
        return;
    }

    // Fetch status for each intersection in parallel.
    const statuses = await Promise.all(intersections.map(i =>
        API.get(`/api/projects/${pid}/intersections/${i.intersection_id}/processing/status`)
            .catch(() => ({ status: 'idle' }))
    ));

    let html = '<div class="processing-grid">';
    for (let idx = 0; idx < intersections.length; idx++) {
        const i = intersections[idx];
        const s = statuses[idx];
        html += _processingChipHtml(i, s);
    }
    html += '</div>';

    // Auto-refresh hint
    html += '<p class="helper-text" style="margin-top:14px;">Status auto-refreshes every 2 seconds while this tab is open.</p>';

    host.innerHTML = html;
}

function _processingChipHtml(intersection, status) {
    const segCount = status.segment_count || 0;
    const currentIdx = status.current_segment_index || 0;
    const pct = segCount > 0 ? Math.round((currentIdx / segCount) * 100) : 0;

    let statusBadge = '';
    let actionsHtml = '';
    let detailHtml = '';

    switch (status.status) {
        case 'idle':
            statusBadge = '<span class="chip-badge chip-idle">Idle</span>';
            actionsHtml = `
                <button onclick="v3OpenIntersection(${intersection.intersection_id})">Configure</button>`;
            break;
        case 'queued':
            statusBadge = '<span class="chip-badge chip-queued">Queued</span>';
            detailHtml = `<div class="chip-detail">${segCount} segments queued</div>`;
            break;
        case 'running':
            statusBadge = '<span class="chip-badge chip-running">Processing…</span>';
            detailHtml = `
                <div class="chip-detail">Segment ${currentIdx + 1} of ${segCount}</div>
                <div class="chip-progress">
                    <div class="chip-progress-fill" style="width:${pct}%"></div>
                </div>`;
            actionsHtml = `
                <button onclick="v3ViewLive(${intersection.intersection_id})">View live</button>
                <button class="btn-secondary" onclick="v3CancelProcessing(${intersection.intersection_id})">Cancel</button>`;
            break;
        case 'complete':
            statusBadge = '<span class="chip-badge chip-complete">Complete</span>';
            actionsHtml = `
                <button onclick="v3OpenSummary(${intersection.intersection_id})">Open dashboard</button>
                <button class="btn-secondary" onclick="v3DownloadExcel(${intersection.intersection_id})">Excel</button>`;
            break;
        case 'cancelled':
            statusBadge = '<span class="chip-badge chip-warn">Cancelled</span>';
            actionsHtml = `
                <button onclick="v3OpenIntersection(${intersection.intersection_id})">Restart</button>`;
            break;
        case 'error':
            statusBadge = '<span class="chip-badge chip-error">Error</span>';
            detailHtml = `<div class="chip-detail">${escapeHtml(status.error || '')}</div>`;
            actionsHtml = `
                <button onclick="v3OpenIntersection(${intersection.intersection_id})">Open</button>`;
            break;
        default:
            statusBadge = `<span class="chip-badge">${escapeHtml(status.status || '?')}</span>`;
    }

    return `
        <div class="processing-chip">
            <div class="chip-header">
                <h3>${escapeHtml(intersection.name)}</h3>
                <span class="chip-date">${escapeHtml(intersection.date)}</span>
            </div>
            ${statusBadge}
            ${detailHtml}
            <div class="chip-actions">${actionsHtml}</div>
        </div>`;
}

async function v3CancelProcessing(iid) {
    if (!window.confirm('Cancel processing for this intersection?')) return;
    const pid = AppState.currentProject;
    try {
        await API.post(`/api/projects/${pid}/intersections/${iid}/processing/cancel`, {});
    } catch (e) {
        alert(`Cancel failed: ${e.message || e}`);
    }
}

function v3ViewLive(iid) {
    // For now route to the existing processing preview page. Phase 9 builds
    // the proper per-camera live view scoped to the intersection.
    AppState.currentIntersectionId = iid;
    showPage('page-processing');
    if (typeof loadProcessingPage === 'function') {
        loadProcessingPage();
    }
}

function v3OpenSummary(iid) {
    AppState.currentIntersectionId = iid;
    showPage('page-v3-playback');
    if (typeof loadPlaybackPage === 'function') {
        loadPlaybackPage();
    }
}

function v3DownloadExcel(iid) {
    const pid = AppState.currentProject;
    // Direct download via a hidden anchor click
    window.location.href = `/api/projects/${pid}/intersections/${iid}/export/xlsx`;
}

// --- Shared helpers ---------------------------------------------------

function _onSetupNameKeydown(e) {
    if (e.key === 'Enter') { e.target.blur(); }
}

async function saveProjectName() {
    const pid = AppState.currentProject;
    const name = document.getElementById('setup-project-name').value.trim();
    if (!name) return;
    await API.put(`/api/projects/${pid}/name`, { name });
}

async function startCalibration() {
    // Backward-compat hook used by older projects-page flows.
    showPage('page-calibration');
    loadCalibrationPage();
}

async function proceedToProcessing() {
    const pid = AppState.currentProject;
    saveLastProject(pid);
    showPage('page-processing');
    loadProcessingPage();
}

function backToProjects() {
    localStorage.removeItem('lastProjectId');
    AppState.currentProject = null;
    showPage('page-projects');
    loadProjectList();
}

function escapeAttr(text) {
    if (!text) return '';
    return text.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
