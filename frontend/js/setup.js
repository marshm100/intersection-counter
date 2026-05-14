// v3 project page — three-tab layout (Videos | Intersections | Processing).
//
// Tab 1 (Videos):       bulk-upload + labeling table; save derives intersections.
// Tab 2 (Intersections): grid of cards (one per intersection-day);
//                        click a card to drill in (Phase 7 wires sub-tabs).
// Tab 3 (Processing):   in-flight jobs (Phase 8 wires real-time status).

let _v3ActiveTab = 'videos';
let _v3Project = null;
let _v3Videos = [];

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
    html += '<p class="helper-text" style="margin-top:12px;">Detailed intersection configuration (calibration, trims, processing) lands in Phase 7. For now, "Open" is a placeholder.</p>';
    host.innerHTML = html;
}

function v3OpenIntersection(iid) {
    // Phase 7 will replace this with a real sub-tab view.
    alert(`Intersection ${iid} detail panel is coming in Phase 7.`);
}

// --- Processing tab (Phase 8 fleshes out) -----------------------------

async function _renderProcessingTab(host) {
    host.innerHTML = `
        <p class="empty-message">
            Real-time per-intersection processing status, ETA, and "view live" links
            land in Phase 8.
        </p>`;
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
