// Phase C — keyboard-driven review worklist over the Phase B flag queue.
//
// One flagged item per screen, one keystroke, auto-advance. The system is the
// source of truth: every edit goes through the /review endpoints (which write
// vehicle_events); the Excel/PDF is GENERATED from that, never hand-edited.
//
// Cursor model: fetch the OPEN flag list (impact-ordered) for ordering + skip,
// and GET /flags/{id} per displayed item for the enriched clip/event. A
// terminal action (resolve/dismiss/reject) drops the flag from the open list,
// so we refetch and stay put; skip just advances the cursor.

let _wlPid = null, _wlIid = null;
let _wlList = [], _wlPos = 0;
let _wlFlag = null;          // current enriched flag
let _wlSummary = null, _wlGate = null, _wlTotal = 0;
let _wlLegs = [];            // origin legs for the gap add-missed form
let _wlAddMode = false;
let _wlSeconds = 0;          // current scrub position (video seconds)
let _wlBusy = false;

const _WL_MOVE = { '1': 'through', '2': 'left', '3': 'right', '4': 'u_turn' };

function openWorklist(iid) {
    AppState.currentIntersectionId = iid;
    _wlIid = iid;
    showPage('page-worklist');
    loadWorklistPage();
}

async function loadWorklistPage() {
    _wlPid = AppState.currentProject;
    _wlIid = _wlIid || AppState.currentIntersectionId;
    if (!_wlPid || !_wlIid) { showPage('page-setup'); return; }
    const sec = document.getElementById('page-worklist');
    sec.innerHTML = `<p class="empty-message">Finding flags…</p>`;
    try {
        await API.post(`/api/projects/${_wlPid}/intersections/${_wlIid}/flags/rebuild`, {});
    } catch (e) { /* stale-but-present queue is still workable */ }
    _wlBindKeys();
    _wlPos = 0;
    await _wlRefreshList();
    await _wlShow();
}

async function _wlRefreshList() {
    const r = await API.get(`/api/projects/${_wlPid}/intersections/${_wlIid}/flags?status=open`);
    _wlList = r.flags || [];
    _wlSummary = r.summary || _wlSummary;
    try {
        _wlGate = await API.get(`/api/projects/${_wlPid}/intersections/${_wlIid}/qa/acceptance`);
    } catch (e) { _wlGate = null; }
    try {
        const sum = await API.get(`/api/projects/${_wlPid}/intersections/${_wlIid}/summary`);
        _wlTotal = (sum.totals && sum.totals.vehicles) || 0;
    } catch (e) { /* keep last total */ }
    if (_wlPos >= _wlList.length) _wlPos = Math.max(0, _wlList.length - 1);
}

async function _wlShow() {
    _wlAddMode = false;
    if (!_wlList.length) { _wlFlag = null; _wlRender(); return; }
    const id = _wlList[_wlPos].flag_id;
    try {
        _wlFlag = await API.get(`/api/projects/${_wlPid}/flags/${id}`);
    } catch (e) { _wlFlag = _wlList[_wlPos]; }
    _wlLegs = [];
    if (_wlFlag.kind === 'suspected_gap' && _wlFlag.camera_id) {
        try {
            const cal = await API.get(`/api/projects/${_wlPid}/cameras/${_wlFlag.camera_id}/calibration`);
            _wlLegs = cal.legs || [];
        } catch (e) { _wlLegs = []; }
    }
    _wlSeconds = (_wlFlag.clip && _wlFlag.clip.center_seconds) || 0;
    _wlRender();
}

// --- rendering --------------------------------------------------------------

function _wlRender() {
    const sec = document.getElementById('page-worklist');
    sec.innerHTML = `
        <div class="processing-header">
            <a href="#" class="back-link" onclick="_wlBackToQa();return false;">&larr; Back to QA</a>
            <h2 style="margin:4px 0;">Review worklist</h2>
        </div>
        ${_wlBannerHtml()}
        <div style="display:flex;gap:18px;align-items:flex-start;">
            <div style="flex:1;min-width:0;">${_wlMainHtml()}</div>
            <aside style="width:280px;flex:none;">${_wlSideHtml()}</aside>
        </div>`;
    if (_wlFlag && _wlFlag.clip) _wlMountFrame();
}

function _wlBannerHtml() {
    if (!_wlGate) return '';
    if (_wlGate.overall === 'ship') {
        return `<div style="margin:8px 0;padding:10px 14px;border-radius:6px;background:#dcfce7;
            color:#166534;font-weight:700;">✓ Ready to export — within the ±5% bar.
            <span style="font-weight:400;">Remaining flags are optional polish.</span></div>`;
    }
    return '';
}

function _wlGroupSize() {
    if (!_wlFlag || !_wlFlag.batch_key) return 0;
    return _wlList.filter(f => f.batch_key === _wlFlag.batch_key).length;
}

function _wlMainHtml() {
    if (!_wlFlag) {
        const ready = _wlGate && _wlGate.overall === 'ship';
        return `<div style="padding:24px;border:1px solid #e5e7eb;border-radius:8px;text-align:center;">
            <div style="font-size:18px;font-weight:700;color:${ready ? '#16a34a' : '#b45309'};">
                ${ready ? '✓ Queue clear — ready to export' : 'Queue clear'}</div>
            <p class="helper-text">No open flags. ${ready ? '' : 'Check the QA gate below before exporting.'}</p>
            <button class="btn-secondary" onclick="loadWorklistPage()">Re-scan</button>
        </div>`;
    }
    const f = _wlFlag;
    const approach = f.approach ? `${escapeHtml(f.approach)}B` : '';
    const head = `<div style="display:flex;justify-content:space-between;align-items:baseline;">
            <div style="font-weight:700;">${approach} ${escapeHtml((f.subtype || '').replace(/_/g, ' '))}</div>
            <div class="helper-text">item ${_wlPos + 1} of ${_wlList.length} open</div>
        </div>
        <div style="font-size:13px;color:#374151;margin:4px 0 8px;">${escapeHtml(f.reason || '')}</div>`;
    const frame = `<div style="position:relative;background:#111;border-radius:6px;overflow:hidden;">
            <img id="wl-frame" style="display:block;width:100%;" />
            <canvas id="wl-canvas" style="position:absolute;left:0;top:0;width:100%;height:100%;"></canvas>
        </div>`;
    return `<div style="border:1px solid #e5e7eb;border-radius:8px;padding:12px;">
        ${head}${frame}
        ${f.kind === 'uncertain_event' ? _wlUncertainHtml(f) : _wlGapHtml(f)}
    </div>`;
}

function _wlUncertainHtml(f) {
    const ev = f.event || {};
    const pct = v => (v == null ? '—' : `${(v * 100).toFixed(0)}%`);
    let top2 = '';
    if (f.evidence && f.evidence.top2 && f.evidence.top2.length === 2) {
        top2 = `<div class="helper-text">candidates: ${f.evidence.top2.map(t =>
            `${escapeHtml(t.label)} ${(t.p * 100).toFixed(0)}%`).join(' vs ')}</div>`;
    }
    return `
        <div style="margin-top:8px;font-size:13px;">
            <b>System guess:</b> ${escapeHtml(ev.leg_label || '')} ·
            ${escapeHtml(ev.movement || '?')} · ${escapeHtml(ev.vehicle_class || '?')}
            <span class="helper-text"> (det ${pct(ev.detection_confidence)} ·
            traj ${pct(ev.trajectory_confidence)} · dest ${pct(ev.destination_confidence)})</span>
        </div>${top2}
        <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:6px;">
            <button onclick="_wlAccept()"><b>Enter</b> Accept</button>
            <button onclick="_wlSetMovement('through')"><b>1</b> Through</button>
            <button onclick="_wlSetMovement('left')"><b>2</b> Left</button>
            <button onclick="_wlSetMovement('right')"><b>3</b> Right</button>
            <button onclick="_wlSetMovement('u_turn')"><b>4</b> U-turn</button>
            <button onclick="_wlReject()"><b>Del</b> Reject phantom</button>
            <button class="btn-secondary" onclick="_wlDismiss()"><b>D</b> Dismiss</button>
            <button class="btn-secondary" onclick="_wlSkip()"><b>&rarr;</b> Skip</button>
        </div>
        ${_wlGroupSize() > 1 ? `<div style="margin-top:6px;padding-top:6px;border-top:1px dashed #e5e7eb;">
            <button onclick="_wlBatch('resolved')"><b>B</b> Resolve all ${_wlGroupSize()} like this</button>
            <span class="helper-text"> or all as:</span>
            <button class="btn-secondary" onclick="_wlBatchMove('through')">T</button>
            <button class="btn-secondary" onclick="_wlBatchMove('left')">L</button>
            <button class="btn-secondary" onclick="_wlBatchMove('right')">R</button>
            <button class="btn-secondary" onclick="_wlBatchMove('u_turn')">U</button>
        </div>` : ''}`;
}

function _wlGapHtml(f) {
    const c = f.clip || {};
    return `
        <div style="margin-top:8px;font-size:13px;">
            <b>Interval review.</b> Scrub the window and add any vehicles the system missed
            on the ${escapeHtml(f.approach || '')}B approach.
        </div>
        <div style="margin-top:6px;display:flex;align-items:center;gap:8px;">
            <input id="wl-scrub" type="range" min="${Math.floor(c.start_seconds || 0)}"
                max="${Math.ceil(c.end_seconds || (c.start_seconds || 0) + 900)}"
                value="${Math.floor(_wlSeconds)}" step="1" style="flex:1;"
                oninput="_wlScrub(this.value)" />
            <span id="wl-scrub-label" class="helper-text">${_wlFmt(_wlSeconds)}</span>
        </div>
        <div id="wl-add-form"></div>
        <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:6px;">
            <button onclick="_wlToggleAdd()"><b>A</b> Add missed</button>
            <button onclick="_wlResolveGap()"><b>Enter</b> Done — looks counted</button>
            <button class="btn-secondary" onclick="_wlDismiss()"><b>D</b> Dismiss (real low volume)</button>
            <button class="btn-secondary" onclick="_wlSkip()"><b>&rarr;</b> Skip</button>
        </div>`;
}

function _wlSideHtml() {
    const s = _wlSummary || {};
    const gapImpact = (s.open_impact_by_kind && s.open_impact_by_kind.suspected_gap) || 0;
    const uncertain = (s.by_kind && s.by_kind.uncertain_event) || 0;
    let gate = '';
    if (_wlGate) {
        const rf = (_wlGate.items || []).find(i => i.item === 'review_flags');
        const ov = _wlGate.overall;
        const col = ov === 'ship' ? '#16a34a' : ov === 'fail' ? '#b91c1c' : '#b45309';
        gate = `<div style="margin-top:12px;padding:10px;border-radius:6px;background:#f8fafc;">
            <div style="font-weight:700;color:${col};">Gate: ${ov.toUpperCase()}</div>
            ${rf ? `<div class="helper-text">${escapeHtml(rf.detail.note || '')}</div>` : ''}
            ${ov === 'ship' ? `<div style="color:#16a34a;font-weight:600;margin-top:4px;">✓ Ready to export</div>` : ''}
        </div>`;
    }
    return `<div style="border:1px solid #e5e7eb;border-radius:8px;padding:12px;font-size:13px;">
        <div style="font-weight:700;margin-bottom:6px;">Live count</div>
        <div>Running total: <b>${(_wlTotal || 0).toLocaleString()}</b> veh</div>
        <div style="font-weight:700;margin:8px 0 6px;">Remaining work</div>
        <div>Open flags: <b>${s.open || 0}</b></div>
        <div>Est. missed (gaps): <b>${Math.round(gapImpact)}</b></div>
        <div>Uncertain to confirm: <b>${uncertain}</b></div>
        ${gate}
        <button class="btn-secondary" style="margin-top:10px;" onclick="loadWorklistPage()">Re-scan queue</button>
        <p class="helper-text" style="margin-top:10px;">Keys: Enter accept · 1–4 movement · Del reject ·
            A add-missed · D dismiss · → skip</p>
    </div>`;
}

function _wlMountFrame() {
    const img = document.getElementById('wl-frame');
    const canvas = document.getElementById('wl-canvas');
    if (!img || !canvas) return;
    img.onload = () => {
        canvas.width = img.naturalWidth || 1280;
        canvas.height = img.naturalHeight || 720;
        _wlDrawOverlay();
    };
    img.src = `/api/projects/${_wlPid}/videos/${_wlFlag.clip.video_id}/frame?seconds=${_wlSeconds}`;
    if (_wlFlag.kind === 'suspected_gap') canvas.onclick = _wlCanvasClick;
    else canvas.onclick = null;
}

function _wlDrawOverlay() {
    const canvas = document.getElementById('wl-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const ev = _wlFlag.event;
    if (!ev || !ev.trajectory_data) return;
    let traj; try { traj = JSON.parse(ev.trajectory_data); } catch (e) { return; }
    if (!traj || traj.length < 1) return;
    ctx.strokeStyle = 'rgba(0,200,255,0.9)'; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(traj[0][0], traj[0][1]);
    for (let i = 1; i < traj.length; i++) ctx.lineTo(traj[i][0], traj[i][1]);
    ctx.stroke();
    const last = traj[traj.length - 1];
    ctx.fillStyle = 'rgba(255,60,60,0.95)';
    ctx.beginPath(); ctx.arc(last[0], last[1], 9, 0, Math.PI * 2); ctx.fill();
}

// --- actions ----------------------------------------------------------------

async function _wlPatchFlag(status) {
    await API.patch(`/api/projects/${_wlPid}/flags/${_wlFlag.flag_id}`, { status });
}

async function _wlAfterTerminal() {
    await _wlRefreshList();   // the resolved flag left the open list; stay at _wlPos
    await _wlShow();
}

async function _wlAccept() { await _wlGuard(async () => { await _wlPatchFlag('resolved'); await _wlAfterTerminal(); }); }
async function _wlDismiss() { await _wlGuard(async () => { await _wlPatchFlag('dismissed'); await _wlAfterTerminal(); }); }
async function _wlResolveGap() { await _wlGuard(async () => { await _wlPatchFlag('resolved'); await _wlAfterTerminal(); }); }

async function _wlSetMovement(m) {
    await _wlGuard(async () => {
        if (_wlFlag.event) {
            await API.patch(`/api/projects/${_wlPid}/review/${_wlFlag.event.event_id}`, { movement: m });
        }
        await _wlPatchFlag('resolved');
        await _wlAfterTerminal();
    });
}

async function _wlReject() {
    await _wlGuard(async () => {
        if (_wlFlag.event) {
            await API.patch(`/api/projects/${_wlPid}/review/${_wlFlag.event.event_id}`, { rejected: true });
        }
        await _wlPatchFlag('resolved');
        await _wlAfterTerminal();
    });
}

async function _wlSkip() {
    if (_wlBusy) return;
    _wlPos = (_wlPos + 1) % Math.max(1, _wlList.length);
    await _wlShow();
}

async function _wlBatch(status, movement) {
    await _wlGuard(async () => {
        await API.post(`/api/projects/${_wlPid}/intersections/${_wlIid}/flags/batch`, {
            batch_key: _wlFlag.batch_key, status: status || 'resolved',
            movement: movement || null,
        });
        await _wlAfterTerminal();
    });
}

function _wlBatchMove(m) { _wlBatch('resolved', m); }

// --- gap add-missed ---------------------------------------------------------

function _wlScrub(v) {
    _wlSeconds = Number(v);
    const lbl = document.getElementById('wl-scrub-label');
    if (lbl) lbl.textContent = _wlFmt(_wlSeconds);
    const img = document.getElementById('wl-frame');
    if (img) img.src = `/api/projects/${_wlPid}/videos/${_wlFlag.clip.video_id}/frame?seconds=${_wlSeconds}`;
}

function _wlToggleAdd() {
    _wlAddMode = !_wlAddMode;
    const form = document.getElementById('wl-add-form');
    if (form) form.innerHTML = _wlAddMode
        ? `<p class="helper-text" style="color:#2563eb;">Add-missed ON — click the vehicle in the frame.</p>`
        : '';
}

function _wlCanvasClick(ev) {
    if (!_wlAddMode) return;
    const canvas = document.getElementById('wl-canvas');
    const rect = canvas.getBoundingClientRect();
    const x = (ev.clientX - rect.left) * (canvas.width / rect.width);
    const y = (ev.clientY - rect.top) * (canvas.height / rect.height);
    const legOpts = _wlLegs.map(l =>
        `<option value="${l.leg_id}">${escapeHtml(l.label)} (${escapeHtml(l.cardinal_direction)})</option>`).join('');
    const form = document.getElementById('wl-add-form');
    form.innerHTML = `<div style="margin-top:8px;padding:8px;border:1px solid #d1d5db;border-radius:6px;">
        <div class="helper-text">at (${x.toFixed(0)}, ${y.toFixed(0)}) · ${_wlFmt(_wlSeconds)}</div>
        <label>Origin leg <select id="wl-add-leg">${legOpts}</select></label>
        <label style="margin-left:8px;">Movement <select id="wl-add-mov">
            <option value="through">Through</option><option value="left">Left</option>
            <option value="right">Right</option><option value="u_turn">U-turn</option></select></label>
        <button style="margin-left:8px;" onclick="_wlConfirmAdd(${x},${y})">Add</button>
    </div>`;
}

async function _wlConfirmAdd(x, y) {
    const leg = document.getElementById('wl-add-leg'), mov = document.getElementById('wl-add-mov');
    if (!leg) return;
    try {
        await API.post(`/api/projects/${_wlPid}/review`, {
            origin_leg_id: Number(leg.value), movement: mov.value,
            timestamp_video: _wlSeconds, video_id: _wlFlag.clip.video_id, x, y,
        });
    } catch (e) { alert(`Add failed: ${e.message || e}`); return; }
    await _wlRefreshList();   // count + gate update; keep reviewing this interval
    const form = document.getElementById('wl-add-form');
    if (form) form.innerHTML = `<p class="helper-text" style="color:#16a34a;">Added. Click another, or Enter when done.</p>`;
    _wlRenderSideOnly();
}

function _wlRenderSideOnly() {
    const sec = document.getElementById('page-worklist');
    const aside = sec && sec.querySelector('aside');
    if (aside) aside.innerHTML = _wlSideHtml();
}

// --- keyboard + lifecycle ---------------------------------------------------

async function _wlGuard(fn) {
    if (_wlBusy) return;
    _wlBusy = true;
    try { await fn(); } catch (e) { alert(`Action failed: ${e.message || e}`); }
    finally { _wlBusy = false; }
}

function _wlKeydown(e) {
    const t = e.target;
    if (t && /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName)) return;
    if (!_wlFlag) return;
    const k = e.key;
    const gap = _wlFlag.kind === 'suspected_gap';
    let handled = true;
    if (k === 'Enter') gap ? _wlResolveGap() : _wlAccept();
    else if (k === 'd' || k === 'D') _wlDismiss();
    else if (k === 'ArrowRight' || k === ' ') _wlSkip();
    else if ((k === 'b' || k === 'B') && _wlFlag.batch_key && _wlGroupSize() > 1) _wlBatch('resolved');
    else if (gap && (k === 'a' || k === 'A')) _wlToggleAdd();
    else if (!gap && _WL_MOVE_KEY(k)) _wlSetMovement(_WL_MOVE_KEY(k));
    else if (!gap && (k === 'Delete' || k === 'Backspace')) _wlReject();
    else handled = false;
    if (handled) e.preventDefault();
}

function _WL_MOVE_KEY(k) { return _WL_MOVE[k] || null; }

function _wlBindKeys() {
    document.removeEventListener('keydown', _wlKeydown);
    document.addEventListener('keydown', _wlKeydown);
}

function _wlTeardown() {
    document.removeEventListener('keydown', _wlKeydown);
}

function _wlBackToQa() {
    showPage('page-setup');
    if (typeof loadSetupPage === 'function') loadSetupPage();
}

function _wlFmt(s) {
    s = Math.floor(s);
    return `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor(s / 60) % 60).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

if (typeof registerTeardown === 'function') registerTeardown('page-worklist', _wlTeardown);
