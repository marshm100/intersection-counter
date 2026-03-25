async function loadSetupPage() {
    const pid = AppState.currentProject;
    if (!pid) {
        showPage('page-projects');
        loadProjectList();
        return;
    }

    const section = document.getElementById('page-setup');
    let project = {};
    let videoInfo = null;

    try {
        project = await API.get(`/api/projects/${pid}`);
    } catch (e) {
        section.innerHTML = '<p class="empty-message">Could not load project.</p>';
        return;
    }

    try {
        videoInfo = await API.get(`/api/projects/${pid}/video`);
    } catch (e) {
        videoInfo = null;
    }

    const projectName = project.project_name || '';
    const numLegs = project.num_legs || '4';
    const videoStartTime = project.video_start_time || '';

    let html = '';

    // Header with back button and project name
    html += '<div class="setup-header">';
    html += '<a href="#" class="back-link" onclick="backToProjects(); return false;">&larr; Back to Projects</a>';
    html += '<div class="setup-name-row">';
    html += `<input type="text" id="setup-project-name" class="setup-name-input" value="${escapeAttr(projectName)}" />`;
    html += '</div>';
    html += '</div>';

    // Video section
    html += '<div class="setup-section">';
    html += '<h3>Video</h3>';
    html += `<button class="video-select-btn" onclick="selectVideo()">Select Video File</button>`;

    if (videoInfo) {
        // Auto-populate start time from creation_time if we don't have one saved yet
        let defaultStartTime = videoStartTime;
        if (!defaultStartTime && videoInfo.creation_time) {
            defaultStartTime = videoInfo.creation_time.substring(0, 16);
        }

        html += '<div class="video-info-panel">';
        html += `<img class="video-thumbnail" src="/api/projects/${pid}/video/frame?seconds=0" alt="Video thumbnail" />`;
        html += '<div class="metadata-grid">';
        html += `<div class="meta-row"><span class="meta-label">Filename</span><span class="meta-value">${escapeHtml(videoInfo.filename)}</span></div>`;
        html += `<div class="meta-row"><span class="meta-label">Duration</span><span class="meta-value">${escapeHtml(videoInfo.duration_formatted)}</span></div>`;
        html += `<div class="meta-row"><span class="meta-label">Resolution</span><span class="meta-value">${videoInfo.width} x ${videoInfo.height}</span></div>`;
        html += `<div class="meta-row"><span class="meta-label">FPS</span><span class="meta-value">${videoInfo.fps}</span></div>`;
        html += `<div class="meta-row"><span class="meta-label">File Size</span><span class="meta-value">${escapeHtml(videoInfo.file_size_formatted)}</span></div>`;
        html += `<div class="meta-row"><span class="meta-label">Codec</span><span class="meta-value">${escapeHtml(videoInfo.codec)}</span></div>`;
        html += '</div>';
        html += '</div>';

        // Settings that depend on video
        html += '<div class="settings-row">';
        html += '<label for="setup-start-time">Recording Start Time</label>';
        html += '<span class="helper-text">(When did the camera start recording?)</span>';
        html += `<input type="datetime-local" id="setup-start-time" value="${escapeAttr(defaultStartTime)}" onchange="saveSetupSettings()" />`;
        html += '</div>';
    }

    html += '</div>';

    // Intersection config
    html += '<div class="setup-section">';
    html += '<h3>Intersection Configuration</h3>';
    html += '<div class="settings-row">';
    html += '<label for="setup-num-legs">Number of Intersection Legs</label>';
    html += '<select id="setup-num-legs" onchange="saveSetupSettings()">';
    for (const n of [2, 3, 4]) {
        const sel = String(n) === String(numLegs) ? ' selected' : '';
        html += `<option value="${n}"${sel}>${n}</option>`;
    }
    html += '</select>';
    html += '</div>';
    html += '</div>';

    // Start calibration button
    const disabled = videoInfo ? '' : ' disabled';
    html += `<button class="btn-calibration"${disabled} onclick="startCalibration()">Start Calibration</button>`;
    html += `<button class="btn-proceed"${disabled} onclick="proceedToProcessing()">Proceed to Processing</button>`;
    if (!videoInfo) {
        html += '<p style="font-size:12px;color:#9ca3af;margin-top:6px;">Select a video file to enable calibration.</p>';
    }

    section.innerHTML = html;

    // Bind name input events
    const nameInput = document.getElementById('setup-project-name');
    nameInput.removeEventListener('blur', saveProjectName);
    nameInput.removeEventListener('keydown', _onSetupNameKeydown);
    nameInput.addEventListener('blur', saveProjectName);
    nameInput.addEventListener('keydown', _onSetupNameKeydown);
}

function _onSetupNameKeydown(e) {
    if (e.key === 'Enter') { e.target.blur(); }
}

async function selectVideo() {
    const pid = AppState.currentProject;

    let browse;
    try {
        browse = await API.post(`/api/projects/${pid}/video/browse`);
    } catch (e) {
        alert('Could not open file browser. Please try again.');
        return;
    }
    if (!browse.path) return;

    let result;
    try {
        result = await API.post(`/api/projects/${pid}/video`, { path: browse.path, confirm: false });
    } catch (e) {
        alert(`Could not load video file.\n\nPath: ${browse.path}\n\nError: ${e.message}\n\nMake sure the file is accessible and is a valid MP4.`);
        return;
    }

    if (result.confirm_required) {
        if (!window.confirm(result.warning)) return;
        try {
            result = await API.post(`/api/projects/${pid}/video`, { path: browse.path, confirm: true });
        } catch (e) {
            alert(`Failed to update video: ${e.message}`);
            return;
        }
    }

    await loadSetupPage();
}

async function saveProjectName() {
    const pid = AppState.currentProject;
    const name = document.getElementById('setup-project-name').value.trim();
    if (!name) return;
    await API.put(`/api/projects/${pid}/name`, { name });
}

async function saveSetupSettings() {
    const pid = AppState.currentProject;
    const numLegsEl = document.getElementById('setup-num-legs');
    const startTimeEl = document.getElementById('setup-start-time');
    const settings = {};
    if (numLegsEl) settings.num_legs = parseInt(numLegsEl.value, 10);
    if (startTimeEl) settings.video_start_time = startTimeEl.value;
    await API.put(`/api/projects/${pid}/settings`, settings);
}

async function startCalibration() {
    await saveSetupSettings();
    const pid = AppState.currentProject;
    await API.put(`/api/projects/${pid}/settings`, { num_legs: parseInt(document.getElementById('setup-num-legs').value, 10) });
    // Update project status
    await API.put(`/api/projects/${pid}/name`, { name: document.getElementById('setup-project-name').value.trim() });
    // Set status to configured via a direct project_info update (reuse settings or a separate call)
    // We'll save status through a simple approach - POST to settings doesn't cover status,
    // so we rely on the backend project_info. For now, use a workaround:
    // The calibration page will handle status update. Just navigate.
    showPage('page-calibration');
    loadCalibrationPage();
}

async function proceedToProcessing() {
    await saveSetupSettings();
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
