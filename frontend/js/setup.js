// Setup page — multi-video edition.
//
// Loads the project, lists attached videos via the new /videos endpoint, and
// auto-migrates legacy single-video projects (those whose video lives in
// project_info.video_path but not yet in the videos table).

async function loadSetupPage() {
    const pid = AppState.currentProject;
    if (!pid) {
        showPage('page-projects');
        loadProjectList();
        return;
    }

    const section = document.getElementById('page-setup');
    let project = {};

    try {
        project = await API.get(`/api/projects/${pid}`);
    } catch (e) {
        section.innerHTML = '<p class="empty-message">Could not load project.</p>';
        return;
    }

    // Fetch multi-video list. If empty AND the legacy /video has a value,
    // migrate it into the videos table so the rest of the UI is one code path.
    let videos = [];
    try {
        videos = await API.get(`/api/projects/${pid}/videos`);
    } catch (e) {
        videos = [];
    }
    if (videos.length === 0) {
        let legacy = null;
        try { legacy = await API.get(`/api/projects/${pid}/video`); }
        catch (e) { legacy = null; }
        if (legacy && legacy.path) {
            try {
                await API.post(`/api/projects/${pid}/videos`, { path: legacy.path });
                videos = await API.get(`/api/projects/${pid}/videos`);
            } catch (e) { /* ignore — still show empty state */ }
        }
    }

    const projectName = project.project_name || '';
    const numLegs = project.num_legs || '4';

    let html = '';

    // Header
    html += '<div class="setup-header">';
    html += '<a href="#" class="back-link" onclick="backToProjects(); return false;">&larr; Back to Projects</a>';
    html += '<div class="setup-name-row">';
    html += `<input type="text" id="setup-project-name" class="setup-name-input" value="${escapeAttr(projectName)}" />`;
    html += '</div>';
    html += '</div>';

    // Videos section
    html += '<div class="setup-section">';
    html += '<h3>Videos</h3>';
    html += '<div class="video-actions">';
    html += '<button class="video-select-btn" onclick="addVideos()">+ Add Videos</button>';
    html += '<span class="helper-text">You can attach multiple recordings of the same intersection (e.g. morning + evening peak).</span>';
    html += '</div>';

    if (videos.length === 0) {
        html += '<p class="empty-message" style="margin-top:12px;">No videos attached yet. Click "Add Videos" to choose one or more files.</p>';
    } else {
        html += '<div class="video-list">';
        for (const v of videos) {
            html += _videoCardHtml(pid, v);
        }
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

    // Action buttons
    const disabled = videos.length === 0 ? ' disabled' : '';
    html += `<button class="btn-calibration"${disabled} onclick="startCalibration()">Start Calibration</button>`;
    html += `<button class="btn-proceed"${disabled} onclick="proceedToProcessing()">Proceed to Processing</button>`;
    if (videos.length === 0) {
        html += '<p style="font-size:12px;color:#9ca3af;margin-top:6px;">Attach at least one video to enable calibration.</p>';
    }

    section.innerHTML = html;

    // Name input bindings
    const nameInput = document.getElementById('setup-project-name');
    nameInput.removeEventListener('blur', saveProjectName);
    nameInput.removeEventListener('keydown', _onSetupNameKeydown);
    nameInput.addEventListener('blur', saveProjectName);
    nameInput.addEventListener('keydown', _onSetupNameKeydown);
}

function _videoCardHtml(pid, v) {
    // recording_start_time is stored UTC ISO; <input type=datetime-local> wants
    // "YYYY-MM-DDTHH:MM" without timezone, so slice the first 16 chars when present.
    const startTime = v.recording_start_time ? String(v.recording_start_time).substring(0, 16)
                    : v.creation_time ? String(v.creation_time).substring(0, 16)
                    : '';
    const durationMin = v.duration_seconds ? (v.duration_seconds / 60).toFixed(1) : '?';
    const sizeMb = v.file_size_bytes ? (v.file_size_bytes / (1024 * 1024)).toFixed(1) : '?';

    return `
    <div class="video-card" data-video-id="${v.video_id}">
        <img class="video-thumbnail"
             src="/api/projects/${pid}/videos/${v.video_id}/frame?seconds=0"
             alt="Video thumbnail" />
        <div class="video-card-body">
            <div class="video-card-title">${escapeHtml(v.filename)}</div>
            <div class="video-card-meta">
                ${durationMin} min &middot;
                ${v.width}&times;${v.height} &middot;
                ${v.fps} fps &middot;
                ${sizeMb} MB
            </div>
            <div class="video-card-controls">
                <label class="video-start-label">Recording start:</label>
                <input type="datetime-local"
                       value="${escapeAttr(startTime)}"
                       onchange="saveVideoStartTime(${v.video_id}, this.value)" />
                <button class="btn-remove-video"
                        onclick="removeVideo(${v.video_id}, '${escapeAttr(v.filename)}')">Remove</button>
            </div>
        </div>
    </div>`;
}

function _onSetupNameKeydown(e) {
    if (e.key === 'Enter') { e.target.blur(); }
}

async function addVideos() {
    const pid = AppState.currentProject;

    // Open multi-file dialog. If only one file is chosen, that's fine — the
    // result is just a 1-element list.
    let browse;
    try {
        browse = await API.post(`/api/projects/${pid}/videos/browse-multi`);
    } catch (e) {
        alert('Could not open file browser. Please try again.');
        return;
    }
    const paths = (browse && browse.paths) ? browse.paths : [];
    if (paths.length === 0) return;

    // Attach each in turn. Errors per-file are surfaced but don't stop the batch.
    const errors = [];
    for (const path of paths) {
        try {
            await API.post(`/api/projects/${pid}/videos`, { path });
        } catch (e) {
            errors.push(`${path}: ${e.message || e}`);
        }
    }
    if (errors.length > 0) {
        alert(`Some files could not be attached:\n\n${errors.join('\n')}`);
    }
    await loadSetupPage();
}

async function removeVideo(videoId, filename) {
    const pid = AppState.currentProject;
    if (!window.confirm(`Remove "${filename}" from this project?`)) return;

    // First call (no confirm) — backend returns a warning if there are events.
    let result;
    try {
        result = await API.del(`/api/projects/${pid}/videos/${videoId}`);
    } catch (e) {
        alert(`Failed to remove video: ${e.message || e}`);
        return;
    }
    if (result && result.confirm_required) {
        if (!window.confirm(result.warning + '\n\nProceed?')) return;
        try {
            await API.del(`/api/projects/${pid}/videos/${videoId}?confirm=true`);
        } catch (e) {
            alert(`Failed to remove video: ${e.message || e}`);
            return;
        }
    }
    await loadSetupPage();
}

async function saveVideoStartTime(videoId, value) {
    const pid = AppState.currentProject;
    try {
        await API.put(`/api/projects/${pid}/videos/${videoId}/start_time`,
                      { recording_start_time: value || null });
    } catch (e) {
        // Non-fatal — value just doesn't persist
        console.error('Failed to save start time:', e);
    }
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
    const settings = {};
    if (numLegsEl) settings.num_legs = parseInt(numLegsEl.value, 10);
    await API.put(`/api/projects/${pid}/settings`, settings);
}

async function startCalibration() {
    await saveSetupSettings();
    const pid = AppState.currentProject;
    await API.put(`/api/projects/${pid}/name`,
                  { name: document.getElementById('setup-project-name').value.trim() });
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
