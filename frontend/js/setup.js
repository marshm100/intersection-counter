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

// Calibration drill-in state: when non-null, the Cameras sub-tab shows the
// camera-scoped calibration view instead of the camera list.
let _v3CalibratingCameraId = null;

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
    // Kill the Processing-tab poll immediately when switching away — the
    // poll's internal "is tab still active?" guard only runs on the next
    // tick, which can be up to 2 s away. Without this, a Configure click
    // taken between ticks lets the next tick stomp the new view.
    if (tabId !== 'processing' && _v3ProcessingPollTimer) {
        clearInterval(_v3ProcessingPollTimer);
        _v3ProcessingPollTimer = null;
    }
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

    let intersections = [];
    try {
        [_v3Videos, intersections] = await Promise.all([
            API.get(`/api/projects/${pid}/videos`),
            API.get(`/api/projects/${pid}/intersections`).catch(() => []),
        ]);
    } catch (e) {
        host.innerHTML = '<p class="empty-message">Could not load videos.</p>';
        return;
    }

    // Build-state awareness: when intersections already exist, the green
    // primary CTA was misleading (looked like 'click me to make them').
    // Show a built-status line and downgrade the button to a secondary
    // 'Re-sync' style. Backend is idempotent (upsert by name+date), so
    // re-syncing is safe — but the UI shouldn't pretend it's the same
    // action as a first build.
    const alreadyBuilt = intersections.length > 0;
    const builtStatus = alreadyBuilt
        ? `<div class="videos-built-status">${intersections.length} intersection${intersections.length === 1 ? '' : 's'} already built. Re-sync to pick up label edits.</div>`
        : '';
    const labelBtnText = alreadyBuilt
        ? 'Re-sync labels'
        : 'Save labels & build intersections';
    const labelBtnClass = alreadyBuilt
        ? 'btn-save-labels btn-secondary'
        : 'btn-save-labels';

    let html = `
        <div class="videos-tab-actions">
            <button class="video-select-btn" onclick="v3PickVideos()">+ Upload videos</button>
            <span class="helper-text">Drag and drop multiple files; the system auto-fills camera, date, and start time from the filename.</span>
            <button class="${labelBtnClass}" onclick="v3SaveLabels()" ${_v3Videos.length === 0 ? 'disabled' : ''}>
                ${labelBtnText}
            </button>
        </div>
        ${builtStatus}`;

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
    const dt = v.recording_start_datetime ? String(v.recording_start_datetime).substring(0, 19) : '';
    const datePart = dt ? dt.substring(0, 10) : '';
    const timePart = dt ? dt.substring(11, 19) : '';
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
                    value="${escapeAttr(timePart)}"
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
    const newI = resp.intersections_created || 0;
    const keptI = resp.intersections_existed || 0;
    const newC = resp.cameras_created || 0;
    const keptC = resp.cameras_existed || 0;
    // Distinguish first-build from re-sync in the toast so re-clicking
    // doesn't leave the user wondering whether the action duplicated
    // anything. Backend is idempotent — the message makes that visible.
    let summary;
    if (newI === 0 && newC === 0 && (keptI > 0 || keptC > 0)) {
        summary = `No changes — all ${keptI} intersection${keptI === 1 ? '' : 's'} and ${keptC} camera${keptC === 1 ? '' : 's'} already exist.`;
    } else if (keptI > 0 || keptC > 0) {
        summary = `Built ${newI} new intersection${newI === 1 ? '' : 's'} and ${newC} new camera${newC === 1 ? '' : 's'}.\n` +
                  `Kept ${keptI} existing intersection${keptI === 1 ? '' : 's'} and ${keptC} existing camera${keptC === 1 ? '' : 's'}.`;
    } else {
        summary = `Built ${newI} intersection${newI === 1 ? '' : 's'} and ${newC} camera${newC === 1 ? '' : 's'}.`;
    }
    summary += `\n\nAttached ${resp.videos_attached} video${resp.videos_attached === 1 ? '' : 's'}.`;
    if (resp.videos_skipped) {
        summary += `\nSkipped ${resp.videos_skipped} (missing intersection name or recording date).`;
    }
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
    // Force the active tab to Intersections. Otherwise opening an intersection
    // from a Processing-tab chip (Configure / Restart / Open) leaves
    // _v3ActiveTab='processing' so the 2-second processing-chips poll keeps
    // overwriting the detail view with the chip grid every couple seconds —
    // the user perceives this as "can't get into the configuration menu".
    if (_v3ActiveTab !== 'intersections') {
        await v3SwitchTab('intersections');
    } else {
        await _renderIntersectionsTab(document.getElementById('v3-tab-content'));
    }
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
        { id: 'qa',       label: 'QA' },
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
    html += `<div id="v3-twopass-plan"></div>`;
    html += `<div class="isect-detail-footer">
        <button class="btn-confirm-process" onclick="v3ConfirmProcess()">Confirm &amp; process</button>
        <button class="btn-secondary" onclick="v3CloseIntersection()">Done</button>
    </div>`;
    host.innerHTML = html;

    await _renderDetailSubTab();
    _renderTwoPassPlan();   // fire-and-forget; empty when the flag is off
}

// --- Two-pass readiness (stage 3.4) -------------------------------------
//
// The plan endpoint 404s when TWO_PASS_ENABLED is off — that 404 is the
// feature probe, so the legacy surface stays bit-for-bit untouched.

function _tpBadge(txt, kind) {
    const c = ({ ok: ['#166534', '#dcfce7'], warn: ['#92400e', '#fef3c7'],
                 bad: ['#991b1b', '#fee2e2'], dim: ['#475569', '#f1f5f9'] })[kind]
              || ['#475569', '#f1f5f9'];
    return `<span style="display:inline-block;padding:0 7px;border-radius:8px;
        font-size:11px;font-weight:700;color:${c[0]};background:${c[1]};">${txt}</span>`;
}

function _tpDumpBadge(w) {
    const s = (w.dump && w.dump.status) || 'missing';
    if (s === 'ready') return _tpBadge('pass-1 ready', 'ok');
    if (s === 'partial') return _tpBadge('pass-1 partial — will resume', 'warn');
    if (s === 'mismatch') return _tpBadge('dump/trim mismatch', 'bad');
    return w.cache === 'ready'
        ? _tpBadge('pass-1 needed (from cache)', 'warn')
        : _tpBadge('pass-1 needed (detect at ingest)', 'warn');
}

function _tpPass2Badge(w) {
    if (w.pass2 === 'current') return _tpBadge('pass-2 current', 'ok');
    if (w.pass2 === 'stale') return _tpBadge('pass-2 stale — will re-run', 'dim');
    return _tpBadge('pass-2 pending', 'dim');
}

async function _renderTwoPassPlan() {
    const host = document.getElementById('v3-twopass-plan');
    if (!host) return;
    const pid = AppState.currentProject;
    const iid = _v3OpenIntersectionId;
    let plan;
    try {
        plan = await API.get(`/api/projects/${pid}/intersections/${iid}/two-pass/plan`);
    } catch (e) {
        return;   // flag off (404) or transient error — show nothing
    }
    const wins = plan.windows || [];
    if (!wins.length) {
        host.innerHTML = `<p class="helper-text" style="margin:8px 0 0;">
            Two-pass: no processing windows yet — add the study periods in the
            Clip trim tab; they become the count windows.</p>`;
        return;
    }
    let html = `<div style="margin:10px 0 0;padding:8px 12px;border:1px solid #e2e8f0;
        border-radius:6px;">
        <div style="font-size:12px;font-weight:700;margin-bottom:4px;">Two-pass readiness</div>`;
    for (const w of wins) {
        html += `<div style="display:flex;gap:8px;align-items:center;font-size:12px;
            padding:2px 0;">
            <span style="min-width:220px;">Camera ${w.camera_id} · ${escapeHtml(w.variant)}
                (${escapeHtml(w.start_wallclock)}–${escapeHtml(w.end_wallclock)})</span>
            ${_tpDumpBadge(w)} ${_tpPass2Badge(w)}
        </div>`;
    }
    html += `</div>`;
    host.innerHTML = html;
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
    return ({ settings: 'intersection', cameras: 'cameras', trims: 'clip', qa: 'qa' })[tabId] || tabId;
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
    } else if (_v3DetailSubTab === 'qa') {
        await _renderQaSubTab(host);
    }
}

// --- Sub-tab: Conservation QA (Phase 3) --------------------------------
//
// Zero-ground-truth sanity checks: corridor flow-conservation across the
// project's intersections (the same vehicles counted twice minutes apart —
// valid at any window length, the primary new-site check) and
// reverse-movement balance for THIS intersection (informational at short
// windows: peak-hour directional imbalance is real traffic, not error).

const _QA_BADGE = {
    ok:   ['#16a34a', '#dcfce7', 'OK'],
    warn: ['#b45309', '#fef3c7', 'WARN'],
    fail: ['#b91c1c', '#fee2e2', 'FAIL'],
    info: ['#475569', '#f1f5f9', 'INFO'],
};

function _qaBadge(verdict) {
    const [fg, bg, label] = _QA_BADGE[verdict] || _QA_BADGE.info;
    return `<span style="display:inline-block;padding:1px 8px;border-radius:9px;
        font-size:11px;font-weight:700;color:${fg};background:${bg};">${label}</span>`;
}

let _qaSpotWindow = null;     // proposed spot window {camera_id, start_seconds, duration_seconds}

const _QA_OVERALL = {
    ship:   ['#166534', '#dcfce7', 'READY TO EXPORT', 'All checks green.'],
    review: ['#92400e', '#fef3c7', 'NEEDS REVIEW', 'Resolve the items below, then re-check.'],
    fail:   ['#991b1b', '#fee2e2', 'CHECKS FAILING', 'A hard failure below needs investigation before export.'],
};

function _qaFmtHms(totalSec) {
    const s = Math.round(totalSec);
    return `${String(Math.floor(s/3600)).padStart(2,'0')}:${String(Math.floor(s%3600/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;
}

async function _renderQaSubTab(host) {
    host.innerHTML = '<p class="empty-message">Running conservation checks…</p>';
    const iid = _v3OpenIntersectionId;
    let rb = null, cc = null, gate = null, cams = [], spots = [], err = null;
    try {
        rb = await API.get(`/api/projects/${_v3Project.project_id}/intersections/${iid}/qa/conservation`);
        cc = await API.get(`/api/projects/${_v3Project.project_id}/qa/corridor`);
        gate = await API.get(`/api/projects/${_v3Project.project_id}/intersections/${iid}/qa/acceptance`);
        cams = await API.get(`/api/projects/${_v3Project.project_id}/intersections/${iid}/cameras`);
        if (cams.length) {
            const r = await API.get(`/api/projects/${_v3Project.project_id}/cameras/${cams[0].camera_id}/qa/spot-counts`);
            spots = r.spot_counts || [];
        }
    } catch (e) { err = e.message || String(e); }
    if (err) {
        host.innerHTML = `<p class="empty-message">QA checks failed: ${escapeHtml(err)}</p>`;
        return;
    }

    let html = `<div style="max-width:760px;">`;

    // -- acceptance gate banner (Phase 4.2) --
    const [gfg, gbg, glabel, gsub] = _QA_OVERALL[gate.overall] || _QA_OVERALL.review;
    const rfItem = (gate.items || []).find(i => i.item === 'review_flags');
    const openFlags = rfItem ? (rfItem.detail.open || 0) : 0;
    html += `<div style="padding:10px 14px;border-radius:6px;background:${gbg};margin-bottom:14px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div style="font-size:14px;font-weight:700;color:${gfg};">${glabel}</div>
            <button onclick="openWorklist(${iid})" style="font-size:12px;">
                Review flags${openFlags ? ` (${openFlags})` : ''} &rarr;</button>
        </div>
        <div style="font-size:12px;color:${gfg};">${gsub}
            ${gate.items.map(i => `${escapeHtml(i.item.replace(/_/g, ' '))}: ${i.verdict.toUpperCase()}`).join(' · ')}
        </div>
    </div>`;

    // -- corridor consistency (primary) --
    html += `<h4 style="margin:6px 0 4px;">Corridor flow conservation</h4>
        <p style="font-size:12px;color:#6b7280;margin:0 0 8px;">
            Vehicles leaving one intersection toward the next should arrive there.
            Gaps implicate counting at one end (or heavy mid-block access on that
            link). Valid at any window length. Bold rows involve this intersection.</p>`;
    const links = (cc.links || []);
    if (!links.length) {
        html += `<p style="font-size:12px;color:#9ca3af;">${escapeHtml(cc.note || 'No links to check.')}</p>`;
    } else {
        html += `<table style="width:100%;font-size:12px;border-collapse:collapse;">
            <tr style="text-align:left;color:#6b7280;">
                <th style="padding:3px 6px;">Link</th><th>Sent</th><th>Received</th><th>Gap</th><th></th></tr>`;
        for (const l of links) {
            const mine = l.link.startsWith(`${iid}->`) || l.link.indexOf(`->${iid} `) >= 0;
            html += `<tr style="border-top:1px solid #f3f4f6;${mine ? 'font-weight:600;' : ''}">
                <td style="padding:3px 6px;">${escapeHtml(l.link)}</td>
                <td>${l.sent}</td><td>${l.received}</td>
                <td>${(l.gap * 100).toFixed(0)}%</td><td>${_qaBadge(l.verdict)}</td></tr>`;
        }
        html += `</table>`;
    }

    // -- reverse balance (secondary / investigative) --
    html += `<h4 style="margin:18px 0 4px;">Reverse-movement balance</h4>
        <p style="font-size:12px;color:#6b7280;margin:0 0 8px;">
            Over a full day each movement roughly equals its geometric reverse.
            ${rb.applicable ? '' : `<b>${escapeHtml(rb.note || '')}</b> `}
            An imbalance is a prompt to review those cells, not proof of error
            (one-way demand patterns are real).</p>`;
    if (!(rb.pairs || []).length) {
        html += `<p style="font-size:12px;color:#9ca3af;">No movement pairs above the volume floor.</p>`;
    } else {
        html += `<table style="width:100%;font-size:12px;border-collapse:collapse;">
            <tr style="text-align:left;color:#6b7280;">
                <th style="padding:3px 6px;">Movement</th><th>Count</th>
                <th>Reverse</th><th>Count</th><th>Imbalance</th><th></th></tr>`;
        for (const p of rb.pairs) {
            html += `<tr style="border-top:1px solid #f3f4f6;">
                <td style="padding:3px 6px;">${escapeHtml(p.movement)}</td>
                <td>${p.cells[0].count}</td>
                <td>${escapeHtml(p.reverse)}</td>
                <td>${p.cells[1].count}</td>
                <td>${(p.imbalance * 100).toFixed(0)}%</td>
                <td>${_qaBadge(p.verdict)}</td></tr>`;
        }
        html += `</table>`;
    }
    // -- spot count (Phase 4.1) --
    const cam = cams[0];
    html += `<h4 style="margin:18px 0 4px;">Manual spot count</h4>
        <p style="font-size:12px;color:#6b7280;margin:0 0 8px;">
            Hand-count a window of the raw video and compare against the system —
            the zero-ground-truth accuracy estimate. Certifying the &plusmn;10% CI
            needs roughly <b>850 total vehicles</b> in the window (20&ndash;40 min
            at a busy site); shorter counts report as "review" with guidance.</p>`;
    if (!cam) {
        html += `<p style="font-size:12px;color:#9ca3af;">No cameras on this intersection.</p>`;
    } else {
        // Stratified coverage (MASTER_PLAN §5): a multi-segment run (e.g. AM + PM
        // trims) must be spot-checked in EACH segment — an all-easy-window sample
        // can't certify a run whose hardest (low-sun) window was bad.
        const scItem = (gate.items || []).find(i => i.item === 'spot_count');
        const scDet = scItem && scItem.detail && scItem.detail[0];
        if (scDet && scDet.segments > 1) {
            const short = scDet.covered < scDet.segments;
            html += `<p style="font-size:12px;margin:0 0 8px;color:${short ? '#b45309' : '#059669'};">
                <b>Coverage: ${scDet.covered}/${scDet.segments} time segments spot-checked.</b>
                ${short ? escapeHtml(scDet.note) : 'The run’s range of conditions is sampled.'}</p>`;
        }
        for (const s of spots.slice(0, 3)) {
            const rep = s.report;
            html += `<div style="display:flex;align-items:center;gap:8px;font-size:12px;padding:4px 6px;
                        margin-bottom:3px;border:1px solid #e5e7eb;border-radius:4px;">
                <span style="flex:1;">${_qaFmtHms(s.start_seconds)} +${Math.round(s.duration_seconds/60)}min
                    — manual ${rep.total.manual} vs system ${rep.total.system}
                    <span style="color:#6b7280;">(${escapeHtml(rep.note)})</span></span>
                ${_qaBadge(rep.verdict === 'pass' ? 'ok' : rep.verdict === 'fail' ? 'fail' : 'warn')}
            </div>`;
        }
        if (_qaSpotWindow && _qaSpotWindow.camera_id === cam.camera_id) {
            const w = _qaSpotWindow;
            const cards = [...new Set((_v3IntersectionDetail.legs_by_camera &&
                _v3IntersectionDetail.legs_by_camera[cam.camera_id] || []).map(l => l.cardinal_direction))];
            const useCards = cards.length ? cards : ['N', 'S', 'E', 'W'];
            html += `<div style="margin-top:8px;padding:10px;background:#f0f9ff;border:1px solid #0ea5e9;border-radius:4px;font-size:12px;">
                <div style="font-weight:600;margin-bottom:4px;">
                    Count window: ${_qaFmtHms(w.start_seconds)} &ndash; ${_qaFmtHms(w.start_seconds + w.duration_seconds)}
                    (video time)${w._nseg > 1 ? ` &middot; segment ${w._seg + 1} of ${w._nseg}` : ''}</div>
                <p style="margin:0 0 8px;color:#0c4a6e;">Watch this window in the source video and
                    count vehicles per approach &times; movement. Leave cells you did not observe at 0
                    — only non-zero cells are compared.</p>
                <table style="font-size:12px;border-collapse:collapse;">
                    <tr><th style="padding:2px 6px;"></th>
                        <th>through</th><th>left</th><th>right</th><th>u_turn</th></tr>
                    ${useCards.map(c => `<tr>
                        <td style="padding:2px 6px;font-weight:600;">${_v3Bound(c)}B</td>
                        ${['through','left','right','u_turn'].map(m =>
                            `<td><input type="number" min="0" value="0" style="width:64px;font-size:12px;"
                                 id="v3-spot-${escapeHtml(c)}-${m}"></td>`).join('')}
                    </tr>`).join('')}
                </table>
                <div style="margin-top:8px;">
                    <button onclick="v3QaSaveSpotCount(${cam.camera_id})"
                        style="font-size:12px;padding:4px 10px;margin-right:6px;background:#0ea5e9;color:white;border:none;border-radius:3px;cursor:pointer;">
                        Save spot count
                    </button>
                    <button onclick="v3QaCancelSpot()"
                        style="font-size:12px;padding:4px 10px;background:white;color:#6b7280;border:1px solid #d1d5db;border-radius:3px;cursor:pointer;">
                        Cancel
                    </button>
                </div>
            </div>`;
        } else {
            html += `<div style="margin-top:6px;">
                <button onclick="v3QaProposeSpot(${cam.camera_id}, 30)"
                    style="font-size:12px;padding:4px 10px;background:white;color:#0ea5e9;border:1px solid #0ea5e9;border-radius:3px;cursor:pointer;">
                    Propose a 30-min spot window
                </button>
            </div>`;
        }
    }

    html += `<p style="font-size:11px;color:#9ca3af;margin-top:10px;">
        Investigate flagged cells in the Review screen (filter by the implicated
        approach + movement).</p></div>`;
    host.innerHTML = html;
}

window.v3QaProposeSpot = async function (cameraId, minutes) {
    try {
        // Stratified: fetch one window per processed segment and steer the
        // operator to the first segment not yet spot-checked (so a multi-trim run
        // gets the hard PM window sampled, not another easy AM one — §5).
        const pw = await API.get(
            `/api/projects/${_v3Project.project_id}/cameras/${cameraId}/qa/spot-windows?minutes=${minutes}`);
        const windows = pw.windows || [];
        if (!windows.length) { alert(pw.error || 'No processed footage to sample yet.'); return; }
        let spots = [];
        try {
            const r = await API.get(
                `/api/projects/${_v3Project.project_id}/cameras/${cameraId}/qa/spot-counts`);
            spots = r.spot_counts || [];
        } catch (e) { /* no prior counts */ }
        const covered = new Set();
        (pw.processed_segments || []).forEach((seg, i) => {
            if (spots.some(s => {
                const m = s.start_seconds + s.duration_seconds / 2;
                return m >= seg[0] && m < seg[1];
            })) covered.add(i);
        });
        const pick = windows.find(w => !covered.has(w.segment_index)) || windows[0];
        _qaSpotWindow = {
            camera_id: cameraId, start_seconds: pick.start_seconds,
            duration_seconds: pick.duration_seconds,
            _seg: pick.segment_index, _nseg: pw.n_segments,
        };
    } catch (e) {
        alert('Could not propose a window: ' + (e.message || String(e)));
        return;
    }
    await _renderDetailSubTab();
};

window.v3QaCancelSpot = async function () {
    _qaSpotWindow = null;
    await _renderDetailSubTab();
};

// Approach (bound) = opposite of the leg's cardinal POSITION
// (see backend/services/cardinals.py). A SE-corner leg is a NW-bound approach.
const V3_BOUND_OF = { N: 'S', S: 'N', E: 'W', W: 'E', NE: 'SW', SW: 'NE', NW: 'SE', SE: 'NW' };
const _v3Bound = c => V3_BOUND_OF[c] || c;

window.v3QaSaveSpotCount = async function (cameraId) {
    if (!_qaSpotWindow) return;
    const counts = {};
    const legs = (_v3IntersectionDetail.legs_by_camera
        && _v3IntersectionDetail.legs_by_camera[cameraId]) || [];
    const cards = [...new Set(legs.map(l => l.cardinal_direction))];
    const useCards = cards.length ? cards : ['N', 'S', 'E', 'W'];
    for (const c of useCards) {
        for (const m of ['through', 'left', 'right', 'u_turn']) {
            const el = document.getElementById(`v3-spot-${c}-${m}`);
            if (!el) continue;
            const v = parseInt(el.value, 10) || 0;
            if (v > 0) counts[`${_v3Bound(c)} ${m}`] = v;  // key by bound approach
        }
    }
    if (!Object.keys(counts).length) {
        alert('Enter at least one non-zero count.');
        return;
    }
    try {
        await API.post(
            `/api/projects/${_v3Project.project_id}/cameras/${cameraId}/qa/spot-counts`,
            { start_seconds: _qaSpotWindow.start_seconds,
              duration_seconds: _qaSpotWindow.duration_seconds,
              manual_counts: counts });
    } catch (e) {
        alert('Save failed: ' + (e.message || String(e)));
        return;
    }
    _qaSpotWindow = null;
    await _renderDetailSubTab();
};

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

    if (_v3CalibratingCameraId != null) {
        await _renderCameraCalibration(host, _v3CalibratingCameraId);
        return;
    }

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

async function v3CalibrateCamera(camId) {
    _v3CalibratingCameraId = camId;
    await _renderCamerasSubTab(document.getElementById('v3-detail-subcontent'));
}

async function _renderCameraCalibration(host, camId) {
    const pid = AppState.currentProject;
    const iid = _v3OpenIntersectionId;

    const camera = (_v3IntersectionDetail?.cameras || []).find(c => c.camera_id === camId);
    if (!camera) {
        host.innerHTML = '<p class="empty-message">Camera not found.</p>';
        return;
    }
    const firstVideo = (camera.videos || [])[0] || null;
    const legCount = _v3IntersectionDetail?.intersection?.leg_count || 4;

    window.v3RenderCalibration(host, pid, camId, {
        intersectionId: iid,
        legCount,
        videoId: firstVideo ? firstVideo.video_id : null,
        videoDuration: firstVideo ? firstVideo.duration_seconds : 0,
        cameraLabel: camera.label,
        onClose: async () => {
            _v3CalibratingCameraId = null;
            // Re-fetch the intersection detail so calibration-status flags refresh
            try {
                _v3IntersectionDetail = await API.get(
                    `/api/projects/${pid}/intersections/${iid}`,
                );
            } catch (e) { /* keep stale detail */ }
            await _renderCamerasSubTab(document.getElementById('v3-detail-subcontent'));
        },
    });
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
        const camLabels = {};
        for (const c of (_v3IntersectionDetail?.cameras || [])) {
            camLabels[c.camera_id] = c.label;
        }
        html += '<ul class="coverage-list">';
        for (const cam of report.per_camera) {
            const label = camLabels[cam.camera_id] || `Camera ${cam.camera_id}`;
            html += `<li>${escapeHtml(label)}: ` + cam.intervals.map(_formatCoverageInterval).join(', ') + '</li>';
        }
        html += '</ul>';
    }

    host.innerHTML = html;
}

function _formatCoverageInterval(iv) {
    const sDate = iv.start.substring(0, 10);
    const eDate = iv.end.substring(0, 10);
    const sTime = iv.start.substring(11, 19);
    const eTime = iv.end.substring(11, 19);
    const dayDelta = Math.round(
        (Date.parse(eDate) - Date.parse(sDate)) / 86400000
    );
    const eDisplay = dayDelta > 0 ? `${eTime} (+${dayDelta}d)` : eTime;
    const durSec = Math.max(0, (Date.parse(iv.end) - Date.parse(iv.start)) / 1000);
    const h = Math.floor(durSec / 3600);
    const m = Math.floor((durSec % 3600) / 60);
    const s = Math.floor(durSec % 60);
    const durStr = `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
    return `${sTime}–${eDisplay} <span class="helper-text">(${durStr})</span>`;
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

    // Two-pass flow (stage 3.4) when the flag is on — the plan endpoint's
    // 404 is the probe; on it, fall through to the legacy path unchanged.
    let tpPlan = null;
    try {
        tpPlan = await API.get(`/api/projects/${pid}/intersections/${iid}/two-pass/plan`);
    } catch (e) { tpPlan = null; }
    if (tpPlan) {
        await _v3ConfirmProcessTwoPass(pid, iid, tpPlan.windows || []);
        return;
    }

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
    const warnBlock = (preflight.warnings && preflight.warnings.length)
        ? '\n⚠ Warnings (you can still proceed):\n' +
          preflight.warnings.map(w => '  • ' + w).join('\n') + '\n'
        : '';
    const msg = `Ready to process this intersection.\n\n` +
                `Segments: ${preflight.segment_count}\n` +
                `Cameras used: ${preflight.cameras_used.length}\n` +
                `Trims: ${preflight.trims_used.length}\n` +
                warnBlock +
                `\nStart processing now?`;
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

async function _v3ConfirmProcessTwoPass(pid, iid, wins) {
    if (!wins.length) {
        alert('Nothing to process yet — add the study periods in the Clip trim '
              + 'tab first; they define the count windows.');
        return;
    }
    const mism = wins.filter(w => w.dump && w.dump.status === 'mismatch');
    if (mism.length) {
        alert('Cannot process — an existing pass-1 dump does not cover its trim window:\n\n'
              + mism.map(w => `  • Camera ${w.camera_id} ${w.variant}`).join('\n')
              + '\n\nDelete the dump or fix the trim, then retry.');
        return;
    }
    const lines = wins.map(w => {
        const d = (w.dump && w.dump.status) || 'missing';
        let step;
        if (d === 'ready') {
            step = w.pass2 === 'current'
                ? 'pass 2 — cached result, re-apply (fast)'
                : 'pass 2 — count from the existing dump (~minutes)';
        } else if (w.cache === 'ready') {
            step = 'pass 1 (track from cache) then pass 2';
        } else {
            step = 'pass 1 (DETECT + cache + track — can take hours) then pass 2';
        }
        return `  • Camera ${w.camera_id} — ${w.start_wallclock}–${w.end_wallclock}: ${step}`;
    });
    const msg = 'Two-pass processing plan:\n\n' + lines.join('\n')
        + '\n\nCounts apply with a backup of the project database; the flag '
        + 'queue rebuilds after each camera.\n\nStart now?';
    if (!window.confirm(msg)) return;
    try {
        await API.post(`/api/projects/${pid}/intersections/${iid}/two-pass/process`, {});
    } catch (e) {
        alert(`Start failed: ${e.message || e}`);
        return;
    }
    alert('Two-pass processing started. Track progress on the Processing tab.');
    if (_v3OpenIntersectionId !== null) v3CloseIntersection();
    await v3SwitchTab('processing');
}

// --- Processing tab (Phase 8 fleshes out) -----------------------------

let _v3ProcessingPollTimer = null;

async function _renderProcessingTab(host) {
    // Two regions: a stable header (mode selector, never re-rendered on
    // poll so the dropdown doesn't reset mid-interaction) and a chips
    // container (refreshed every 2s with status data).
    host.innerHTML = `
        <div class="processing-tab-header" id="v3-processing-header"></div>
        <div id="v3-processing-chips-host"></div>
    `;
    const header = document.getElementById('v3-processing-header');
    const chipsHost = document.getElementById('v3-processing-chips-host');

    await _renderProcessingModeSelector(header);
    await _refreshProcessingChips(chipsHost);

    // Start polling so status updates without manual refresh.
    if (_v3ProcessingPollTimer) clearInterval(_v3ProcessingPollTimer);
    _v3ProcessingPollTimer = setInterval(() => {
        // Only poll while the Processing tab is the active tab.
        if (_v3ActiveTab === 'processing') {
            _refreshProcessingChips(chipsHost);
        } else {
            clearInterval(_v3ProcessingPollTimer);
            _v3ProcessingPollTimer = null;
        }
    }, 2000);
}


async function _renderProcessingModeSelector(host) {
    const pid = AppState.currentProject;
    let modes, project;
    try {
        [modes, project] = await Promise.all([
            API.get('/api/processing-modes'),
            API.get(`/api/projects/${pid}`),
        ]);
    } catch (e) {
        host.innerHTML = '';   // fail quiet — selector is convenience, not critical
        return;
    }

    const current = project.processing_mode || modes.default;
    const currentCfg = modes.modes.find(m => m.key === current)
                    || modes.modes.find(m => m.key === modes.default);

    const optionsHtml = modes.modes.map(m => `
        <option value="${m.key}" ${m.key === current ? 'selected' : ''}>
            ${escapeHtml(m.label)}
        </option>
    `).join('');

    host.innerHTML = `
        <div class="processing-mode-selector">
            <label for="v3-processing-mode-select">Processing mode:</label>
            <select id="v3-processing-mode-select" onchange="v3SetProcessingMode(this.value)">
                ${optionsHtml}
            </select>
            <span class="processing-mode-description" id="v3-processing-mode-desc">${escapeHtml(currentCfg?.description || '')}</span>
        </div>`;

    // Stash modes for the description update on change
    host._v3Modes = modes;
}


async function v3SetProcessingMode(mode) {
    const pid = AppState.currentProject;
    try {
        await API.put(`/api/projects/${pid}/settings`, { processing_mode: mode });
    } catch (e) {
        alert(`Could not save processing mode: ${e.message || e}`);
        return;
    }
    // Update the description in place so the user sees the change took.
    const header = document.getElementById('v3-processing-header');
    const desc = document.getElementById('v3-processing-mode-desc');
    const modes = header?._v3Modes;
    if (desc && modes) {
        const cfg = modes.modes.find(m => m.key === mode);
        if (cfg) desc.textContent = cfg.description;
    }
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

function _formatEta(seconds) {
    // ETA from the pipeline can be very large (full-day video) or tiny.
    // Show H:MM:SS over 1h, M:SS under, and a placeholder when unknown.
    if (typeof seconds !== 'number' || !isFinite(seconds) || seconds < 0) return '';
    const s = Math.round(seconds);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
    return `${m}:${String(sec).padStart(2, '0')}`;
}


function _processingChipHtml(intersection, status) {
    const segCount = status.segment_count || 0;
    const currentIdx = status.current_segment_index || 0;
    // Combined progress = whole-segments + intra-segment fraction. Falls
    // back to segment-boundary-only progress when frame_progress hasn't
    // arrived yet (very first poll, or paused).
    const intraPct = (status.frame_progress?.progress_pct || 0) / 100;
    const combinedFrac = segCount > 0
        ? Math.min(1, (currentIdx + intraPct) / segCount)
        : 0;
    const pct = Math.round(combinedFrac * 100);

    let statusBadge = '';
    let actionsHtml = '';
    let detailHtml = '';

    switch (status.status) {
        case 'idle':
            // Split: not-yet-configured shows Configure; configured-but-not-started
            // shows Ready + Start so the user knows their setup work persisted.
            if (status.configured) {
                statusBadge = '<span class="chip-badge chip-ready">Ready</span>';
                detailHtml = '<div class="chip-detail">Configured and ready to process.</div>';
                actionsHtml = `
                    <button onclick="v3StartProcessing(${intersection.intersection_id})">Start</button>
                    <button class="btn-secondary" onclick="v3OpenIntersection(${intersection.intersection_id})">Configure</button>`;
            } else {
                statusBadge = '<span class="chip-badge chip-idle">Idle</span>';
                detailHtml = '<div class="chip-detail">Add cameras, legs, and trims before processing.</div>';
                actionsHtml = `
                    <button onclick="v3OpenIntersection(${intersection.intersection_id})">Configure</button>`;
            }
            break;
        case 'queued':
            statusBadge = '<span class="chip-badge chip-queued">Queued</span>';
            detailHtml = `<div class="chip-detail">${segCount} segments queued</div>`;
            break;
        case 'running': {
            const fp = status.frame_progress || {};
            const etaTxt = _formatEta(fp.eta_seconds);
            const fpsTxt = fp.fps_processing
                ? `${Number(fp.fps_processing).toFixed(1)} fps`
                : '';
            const vehiclesTxt = (typeof fp.vehicle_count === 'number')
                ? `${fp.vehicle_count} vehicles counted` : '';
            // data-frame on the badge gives the DOM a per-frame token that
            // changes every poll while running — used by CSS to retrigger
            // a brief flash so the user can SEE liveness, not just trust it.
            statusBadge = `<span class="chip-badge chip-running chip-running-anim" data-frame="${fp.frame_number ?? 0}"><span class="chip-pulse-dot"></span>Processing…</span>`;
            const subline = [
                `Segment ${currentIdx + 1} of ${segCount}`,
                etaTxt && `ETA ${etaTxt}`,
                fpsTxt,
                vehiclesTxt,
            ].filter(Boolean).join(' · ');
            detailHtml = `
                <div class="chip-detail">${escapeHtml(subline)}</div>
                <div class="chip-progress">
                    <div class="chip-progress-fill" style="width:${pct}%"></div>
                </div>`;
            actionsHtml = `
                <button onclick="v3ViewLive(${intersection.intersection_id})">View live</button>
                <button class="btn-secondary" onclick="v3CancelProcessing(${intersection.intersection_id})">Cancel</button>`;
            break;
        }
        case 'complete':
            statusBadge = '<span class="chip-badge chip-complete">Complete</span>';
            actionsHtml = `
                <button onclick="v3OpenSummary(${intersection.intersection_id})">Open dashboard</button>
                <button class="btn-secondary" onclick="v3DownloadExcel(${intersection.intersection_id})">Excel</button>`;
            break;
        case 'interrupted':
            statusBadge = '<span class="chip-badge chip-warn">Interrupted</span>';
            detailHtml = '<div class="chip-detail">Processing was interrupted (app closed mid-run). Continue from the last checkpoint, or restart from the beginning.</div>';
            actionsHtml = `
                <button onclick="v3ContinueProcessing(${intersection.intersection_id})">Continue</button>
                <button class="btn-secondary" onclick="v3ReprocessFromStart(${intersection.intersection_id})">Restart from beginning</button>`;
            break;
        case 'cancelled':
            statusBadge = '<span class="chip-badge chip-warn">Cancelled</span>';
            actionsHtml = `
                <button onclick="v3OpenIntersection(${intersection.intersection_id})">Restart</button>
                <button class="btn-secondary" onclick="v3ReprocessFromStart(${intersection.intersection_id})">Restart from beginning</button>`;
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

async function v3StartProcessing(iid) {
    // Start an already-configured intersection straight from the chip,
    // without bouncing through the configure page. Reuses the same
    // preflight + confirm flow as v3ConfirmProcess so the user still
    // sees segment/camera/trim counts before committing.
    const pid = AppState.currentProject;

    // Same two-pass probe as v3ConfirmProcess (404 = flag off -> legacy).
    let tpPlan = null;
    try {
        tpPlan = await API.get(`/api/projects/${pid}/intersections/${iid}/two-pass/plan`);
    } catch (e) { tpPlan = null; }
    if (tpPlan) {
        await _v3ConfirmProcessTwoPass(pid, iid, tpPlan.windows || []);
        return;
    }

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
    const warnBlock = (preflight.warnings && preflight.warnings.length)
        ? '\n⚠ Warnings (you can still proceed):\n' +
          preflight.warnings.map(w => '  • ' + w).join('\n') + '\n'
        : '';
    const msg = `Ready to process this intersection.\n\n` +
                `Segments: ${preflight.segment_count}\n` +
                `Cameras used: ${preflight.cameras_used.length}\n` +
                `Trims: ${preflight.trims_used.length}\n` +
                warnBlock +
                `\nStart processing now?`;
    if (!window.confirm(msg)) return;
    try {
        await API.post(`/api/projects/${pid}/intersections/${iid}/processing/start`, {});
    } catch (e) {
        alert(`Start failed: ${e.message || e}`);
        return;
    }
    // Refresh chips so status flips from Ready → Queued/Running.
    const host = document.querySelector('.processing-grid')?.parentElement;
    if (host) await _refreshProcessingChips(host);
}

async function v3ContinueProcessing(iid) {
    const pid = AppState.currentProject;
    try {
        await API.post(`/api/projects/${pid}/intersections/${iid}/processing/resume`, {});
    } catch (e) {
        // The 422 "no matching segment" response carries a structured detail
        // that explains why; surface its message if present.
        const detail = e && e.detail;
        const msg = (detail && detail.message) || e.message || e;
        alert(`Continue failed: ${msg}`);
        return;
    }
    // Refresh chips so status flips from Interrupted → Running.
    const host = document.getElementById('v3-detail-subcontent')?.closest('.v3-tab-content')
              || document.querySelector('.processing-grid')?.parentElement;
    if (host) await _refreshProcessingChips(host);
}

async function v3ReprocessFromStart(iid) {
    if (!window.confirm(
        'Discard all counted vehicles for this intersection and start over?\n\n' +
        'This cannot be undone.'
    )) return;
    const pid = AppState.currentProject;
    try {
        await API.post(`/api/projects/${pid}/intersections/${iid}/processing/reprocess`, {});
    } catch (e) {
        alert(`Reset failed: ${e.message || e}`);
        return;
    }
    // After wiping, drop the user into the intersection card so they can
    // configure (if needed) and hit Start fresh.
    v3OpenIntersection(iid);
}

function v3ViewLive(iid) {
    // Live view = the same playback dashboard as v3OpenSummary; the page
    // detects an in-progress intersection and polls /summary so the count
    // panels fill in as the orchestrator advances through segments.
    AppState.currentIntersectionId = iid;
    showPage('page-v3-playback');
    if (typeof loadPlaybackPage === 'function') {
        loadPlaybackPage();
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
