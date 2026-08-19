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
let _wlCards = [];           // batch rollup: [{key, flags:[...], impact}] impact-desc
let _wlInner = 0;            // member cursor within the current card
let _wlFlag = null;          // current enriched flag
let _wlSummary = null, _wlGate = null, _wlTotal = 0;
let _wlLegs = [];            // origin legs for the gap add-missed form
let _wlAddMode = false;
let _wlSeconds = 0;          // current scrub position (video seconds)
let _wlBusy = false;
let _wlFlipTimer = null, _wlFlipFrames = [], _wlFlipIdx = 0;   // looping clip state
let _wlUndoStack = [];       // session-only action stack for Z (plan_C_polish §3b)
const _WL_UNDO_CAP = 50;

const _WL_MOVE = { '1': 'through', '2': 'left', '3': 'right', '4': 'u_turn' };
// Looping clip: stills sampled across the event clip window, cycled in JS (no
// video-segment endpoint exists; the browser caches each /frame URL so re-loops
// are free). Event-anchored flags only — gap flags span a long interval and keep
// the manual scrub UI.
const _WL_CLIP_FRAMES = 10;
const _WL_FLIP_MS = 150;     // ~6.7 fps playback

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
    sec.innerHTML = `<p class="empty-message">Loading review queue…</p>`;
    // Load the EXISTING flags immediately — do NOT rebuild on every open. Rebuild
    // scans the whole run (uncertain-event feeder + coverage/conservation) and is
    // slow on a large intersection, so it's an explicit action (_wlRebuild), not a
    // blocking await that hangs the worklist open.
    _wlBindKeys();
    _wlPos = 0;
    await _wlRefreshList();
    await _wlShow();
}

async function _wlRebuild() {
    const sec = document.getElementById('page-worklist');
    if (sec) sec.innerHTML = `<p class="empty-message">Rebuilding the review queue…
        (scans the run for uncertain events + coverage gaps; can take a minute on a
        large intersection)</p>`;
    try {
        await API.post(`/api/projects/${_wlPid}/intersections/${_wlIid}/flags/rebuild`, {});
    } catch (e) { alert('Rebuild failed: ' + (e.message || e)); }
    _wlBindKeys();
    _wlPos = 0;
    await _wlRefreshList();
    await _wlShow();
}

async function _wlRefreshList() {
    const r = await API.get(`/api/projects/${_wlPid}/intersections/${_wlIid}/flags?status=open`);
    _wlList = r.flags || [];
    _wlSummary = r.summary || _wlSummary;
    // Roll the flag list up into CARDS (plan_flood_control_2026-07-09): flags
    // sharing a batch_key = one card (one judgment); unkeyed flags = one card
    // each. Card impact = summed member impact, so a big low-conf batch still
    // ranks below a single high-impact gap flag. The cursor walks CARDS.
    const byKey = new Map();
    for (const f of _wlList) {
        const key = f.batch_key || `f${f.flag_id}`;
        if (!byKey.has(key)) byKey.set(key, { key, flags: [], impact: 0 });
        const c = byKey.get(key);
        c.flags.push(f);
        c.impact += Number(f.impact || 0);
    }
    _wlCards = [...byKey.values()].sort((a, b) => b.impact - a.impact);
    try {
        _wlGate = await API.get(`/api/projects/${_wlPid}/intersections/${_wlIid}/qa/acceptance`);
    } catch (e) { _wlGate = null; }
    try {
        const sum = await API.get(`/api/projects/${_wlPid}/intersections/${_wlIid}/summary`);
        _wlTotal = (sum.totals && sum.totals.vehicles) || 0;
    } catch (e) { /* keep last total */ }
    if (_wlPos >= _wlCards.length) _wlPos = Math.max(0, _wlCards.length - 1);
    _wlInner = 0;
}

async function _wlShow() {
    _wlAddMode = false;
    if (!_wlCards.length) { _wlFlag = null; _wlRender(); return; }
    const card = _wlCards[_wlPos];
    if (_wlInner >= card.flags.length) _wlInner = 0;
    const id = card.flags[_wlInner].flag_id;
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
    _wlStopFlip();   // innerHTML below replaces #wl-frame; kill any running loop first
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
    let html = '';
    if (_wlGate && _wlGate.overall === 'ship') {
        html += `<div style="margin:8px 0;padding:10px 14px;border-radius:6px;background:#dcfce7;
            color:#166534;font-weight:700;">✓ Ready to export — within the ±5% bar.
            <span style="font-weight:400;">Remaining flags are optional polish.</span></div>`;
    }
    // Stage-2 auto-resolution, visible (child test): the machine's work is
    // announced, and each bin card names its own closed members.
    if (_wlSummary && _wlSummary.auto_resolved > 0) {
        html += `<div style="margin:8px 0;padding:6px 14px;border-radius:6px;background:#f1f5f9;
            color:#475569;font-size:12px;">The machine closed
            <b>${_wlSummary.auto_resolved}</b> items on its own (out-of-window,
            redundant-for-a-bin, tiny holes) — each card shows its own, and any
            of them can be reopened.</div>`;
    }
    return html;
}

// --- One-question cards (Stage-4 4.2, plan_stage4_childtest_ux) -------------
//
// One question per card kind; the feeder's reason stays as small print.
// Presentation only: the actions, keys, undo, and batch machinery are the
// proven C-polish flow underneath.

const _WL_QUESTIONS = {
    low_det_conf: 'Is this a real vehicle?',
    ambiguous_dest: 'Which way did it go?',
    ambiguous_origin: 'Where did it come from?',
    echo_suspect: 'Are these separate vehicles?',
    bank_coverage_hole: 'Is this movement really this small?',
    merge_borderline: 'Fragments or separate vehicles?',
};

function _wlQuestionFor(f) {
    return _WL_QUESTIONS[f.subtype] ||
        (f.kind === 'suspected_gap' ? 'Did the system miss vehicles here?'
                                    : 'Does this look right?');
}

function _wlBinBannerHtml(f) {
    // batch_key `bin|cam|N-left|07:15` -> "Fix this window: NB left · 07:15–07:30"
    const m = /^bin\|\d+\|([A-Z?]+)-([a-z_?]+)\|(\d\d):(\d\d)$/.exec(f.batch_key || '');
    if (!m) return '';
    const [, appr, mv, hh, mm] = m;
    const t0 = `${hh}:${mm}`;
    const endMin = (parseInt(hh, 10) * 60 + parseInt(mm, 10) + 15);
    const t1 = `${String(Math.floor(endMin / 60) % 24).padStart(2, '0')}:${String(endMin % 60).padStart(2, '0')}`;
    const clusterN = (f.evidence && f.evidence.bin_cluster_n) || null;
    const live = _wlGroupSize() || 1;
    const closed = clusterN ? Math.max(0, clusterN - live) : 0;
    return `<div style="margin:0 0 8px;padding:6px 10px;border-radius:6px;background:#eff6ff;
            border:1px solid #bfdbfe;font-size:12px;color:#1e40af;">
        <b>Fix this window:</b> ${escapeHtml(appr)}B ${escapeHtml(mv.replace('_', '-'))}
        · ${t0}–${t1}
        ${clusterN ? ` · up to <b>${clusterN}</b> counts ride on this window` : ''}
        ${closed ? ` · the machine closed ${closed} similar item${closed > 1 ? 's' : ''} here` : ''}
    </div>`;
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
            <p class="helper-text">No open flags. ${ready ? '' : 'Rebuild the queue to (re)scan the run, or check the QA gate below.'}</p>
            <button class="btn-secondary" onclick="_wlRebuild()">Rebuild queue</button>
        </div>`;
    }
    const f = _wlFlag;
    const approach = f.approach ? `${escapeHtml(f.approach)}B` : '';
    const card = _wlCards[_wlPos] || { flags: [] };
    const groupChip = card.flags.length > 1
        ? `<span style="margin-left:8px;padding:2px 8px;border-radius:10px;background:#e0e7ff;
             color:#3730a3;font-size:11px;font-weight:700;">×${card.flags.length} similar
             — viewing ${_wlInner + 1}</span>`
        : '';
    const head = `${_wlBinBannerHtml(f)}
        <div style="display:flex;justify-content:space-between;align-items:baseline;">
            <div style="font-weight:700;font-size:16px;">${escapeHtml(_wlQuestionFor(f))}${groupChip}</div>
            <div class="helper-text">card ${_wlPos + 1} of ${_wlCards.length} (${_wlList.length} flags)</div>
        </div>
        <div class="helper-text" style="margin:2px 0 8px;">${approach}
            ${escapeHtml((f.subtype || '').replace(/_/g, ' '))} —
            ${escapeHtml(f.reason || '')}</div>`;
    // REVIEW-UI (2026-08-19, operator spec): real <video> on the Range
    // /stream endpoint + live track-bbox overlay; exact-frame jump,
    // 1 s + single-frame scrubbing. The flipbook is gone.
    const frame = `<div style="position:relative;background:#111;border-radius:6px;overflow:hidden;">
            <video id="wl-video" style="display:block;width:100%;" muted playsinline></video>
            <canvas id="wl-canvas" style="position:absolute;left:0;top:0;width:100%;height:100%;"></canvas>
        </div>
        <div class="helper-text" style="margin-top:4px;display:flex;gap:12px;align-items:center;">
            <span id="wl-vtime" style="font-variant-numeric:tabular-nums;font-weight:600;"></span>
            <span>&larr;/&rarr; 1 s · [ ] frame · space pause ·
            <span style="color:#b45309;">yellow = this event's track</span> ·
            grey = all tracks (<b>o</b> toggles)</span>
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
        ${_wlAnswerRowsHtml(f)}
        ${_wlGroupSize() > 1 ? `<div style="margin-top:6px;padding-top:6px;border-top:1px dashed #e5e7eb;">
            <button onclick="_wlBatch('resolved')"><b>B</b> Resolve all ${_wlGroupSize()} like this</button>
            <button class="btn-secondary" onclick="_wlBatch('dismissed')">Dismiss all</button>
            ${(f.batch_key || '').startsWith('dest|') ? `
            <span class="helper-text"> or all as:</span>
            <button class="btn-secondary" onclick="_wlBatchMove('through')">T</button>
            <button class="btn-secondary" onclick="_wlBatchMove('left')">L</button>
            <button class="btn-secondary" onclick="_wlBatchMove('right')">R</button>
            <button class="btn-secondary" onclick="_wlBatchMove('u_turn')">U</button>` : `
            <span class="helper-text">movement edits are per-item for this group (. to step through)</span>`}
        </div>` : ''}`;
}

// The primary answer(s) match the card's question and render BIG; the
// corrections and escape hatches stay small beneath. Same actions, same
// keys, same undo — presentation only (plan_stage4 4.2 rule 3).
const _WL_BIG = 'padding:12px 20px;font-size:15px;font-weight:700;' +
                'border-radius:8px;cursor:pointer;';

function _wlAnswerRowsHtml(f) {
    let primary, secondary;
    if (f.subtype === 'low_det_conf') {
        primary = `
            <button onclick="_wlAccept()" style="${_WL_BIG}background:#dcfce7;border:2px solid #16a34a;">
                Yes — keep it <b>(Enter)</b></button>
            <button onclick="_wlReject()" style="${_WL_BIG}background:#fee2e2;border:2px solid #dc2626;">
                No — remove it <b>(Del)</b></button>`;
        secondary = `
            <span class="helper-text">or correct its direction:</span>
            <button onclick="_wlSetMovement('through')"><b>1</b> Through</button>
            <button onclick="_wlSetMovement('left')"><b>2</b> Left</button>
            <button onclick="_wlSetMovement('right')"><b>3</b> Right</button>
            <button onclick="_wlSetMovement('u_turn')"><b>4</b> U-turn</button>`;
    } else if (f.subtype === 'ambiguous_dest' || f.subtype === 'ambiguous_origin') {
        primary = `
            <button onclick="_wlSetMovement('through')" style="${_WL_BIG}border:2px solid #0ea5e9;background:#f0f9ff;">
                Through <b>(1)</b></button>
            <button onclick="_wlSetMovement('left')" style="${_WL_BIG}border:2px solid #0ea5e9;background:#f0f9ff;">
                Left <b>(2)</b></button>
            <button onclick="_wlSetMovement('right')" style="${_WL_BIG}border:2px solid #0ea5e9;background:#f0f9ff;">
                Right <b>(3)</b></button>
            <button onclick="_wlSetMovement('u_turn')" style="${_WL_BIG}border:2px solid #0ea5e9;background:#f0f9ff;">
                U-turn <b>(4)</b></button>`;
        secondary = `
            <button onclick="_wlAccept()"><b>Enter</b> The guess is right</button>
            <button onclick="_wlReject()"><b>Del</b> Not a vehicle</button>`;
    } else {
        primary = `
            <button onclick="_wlAccept()" style="${_WL_BIG}background:#dcfce7;border:2px solid #16a34a;">
                Looks right <b>(Enter)</b></button>
            <button onclick="_wlReject()" style="${_WL_BIG}background:#fee2e2;border:2px solid #dc2626;">
                Remove it <b>(Del)</b></button>`;
        secondary = `
            <button onclick="_wlSetMovement('through')"><b>1</b> Through</button>
            <button onclick="_wlSetMovement('left')"><b>2</b> Left</button>
            <button onclick="_wlSetMovement('right')"><b>3</b> Right</button>
            <button onclick="_wlSetMovement('u_turn')"><b>4</b> U-turn</button>`;
    }
    return `
        <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:8px;">${primary}</div>
        <div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;">
            ${secondary}
            <button class="btn-secondary" onclick="_wlDismiss()"><b>D</b> Dismiss</button>
            <button class="btn-secondary" onclick="_wlSkip()"><b>&rarr;</b> Skip</button>
            <span class="helper-text">Z undoes anything</span>
        </div>`;
}

function _wlGapHtml(f) {
    const c = f.clip || {};
    return `
        <div style="margin-top:8px;font-size:13px;">
            ${f.subtype === 'echo_suspect'
                ? `<b>Double-count check.</b> Scrub the window — where the same vehicle
                   was counted twice on the ${escapeHtml(f.approach || '')}B approach,
                   open the Review screen for this movement and reject the duplicates.`
                : `<b>Interval review.</b> Scrub the window and add any vehicles the system missed
                   on the ${escapeHtml(f.approach || '')}B approach.`}
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
            <button onclick="_wlResolveGap()" style="${_WL_BIG}background:#dcfce7;border:2px solid #16a34a;">
                ${f.subtype === 'echo_suspect' ? 'Done — duplicates handled'
                                               : 'Done — looks counted'} <b>(Enter)</b></button>
            <button class="btn-secondary" onclick="_wlDismiss()"><b>D</b> Dismiss
                ${f.subtype === 'echo_suspect' ? '(they are separate vehicles)' : '(real low volume)'}</button>
            <button class="btn-secondary" onclick="_wlSkip()"><b>&rarr;</b> Skip</button>
            <span class="helper-text">Z undoes anything</span>
        </div>`;
}

// The stopping rule (plan_C_polish §3a): which gate items block export and
// what action closes each. The queue can only clear review_flags — the
// conservation checks and spot count need the QA tab, and saying so is the
// difference between "grind flags forever" and "know when you're done".
const _WL_GATE_HINTS = {
    corridor_consistency: "cross-intersection conservation — investigate on the QA tab; flags alone won't clear it",
    reverse_balance: 'directional balance — investigate on the QA tab',
    spot_count: 'record a spot count on the QA tab',
    review_flags: 'work the cards below',
};

function _wlVerdictBadge(v) {
    const c = ({ ok: ['#166534', '#dcfce7'], warn: ['#92400e', '#fef3c7'],
                 fail: ['#991b1b', '#fee2e2'], review: ['#92400e', '#fef3c7'],
                 info: ['#475569', '#f1f5f9'] })[v] || ['#475569', '#f1f5f9'];
    return `<span style="display:inline-block;min-width:44px;text-align:center;
        padding:0 6px;border-radius:8px;font-size:10px;font-weight:700;
        color:${c[0]};background:${c[1]};">${escapeHtml((v || '?').toUpperCase())}</span>`;
}

function _wlGateItemFact(it) {
    const d = it.detail;
    if (it.item === 'corridor_consistency' && Array.isArray(d)) {
        const bad = d.filter(l => l.verdict === 'fail').length;
        return bad ? `${bad} of ${d.length} corridor links failing`
                   : `${d.length} corridor links checked`;
    }
    if (it.item === 'spot_count' && Array.isArray(d)) {
        const todo = d.find(c => c.verdict === 'review');
        return todo ? (todo.note || 'coverage segment unsampled') : 'covered';
    }
    return (d && d.note) || '';
}

function _wlGateRowsHtml() {
    if (!_wlGate) return '';
    const ov = _wlGate.overall;
    const col = ov === 'ship' ? '#16a34a' : ov === 'fail' ? '#b91c1c' : '#b45309';
    let rows = '';
    for (const it of (_wlGate.items || [])) {
        const hint = _WL_GATE_HINTS[it.item] || '';
        const blocking = it.verdict === 'fail' || it.verdict === 'review';
        rows += `<div style="display:flex;gap:6px;align-items:baseline;margin-top:5px;
                ${it.verdict === 'info' ? 'opacity:0.6;' : ''}">
            ${_wlVerdictBadge(it.verdict)}
            <div style="min-width:0;">
                <div style="font-weight:600;">${escapeHtml(it.item.replace(/_/g, ' '))}</div>
                <div class="helper-text">${escapeHtml(_wlGateItemFact(it))}</div>
                ${blocking && hint ? `<div class="helper-text" style="color:#2563eb;">→ ${escapeHtml(hint)}</div>` : ''}
            </div>
        </div>`;
    }
    return `<div style="margin-top:12px;padding:10px;border-radius:6px;background:#f8fafc;">
        <div style="font-weight:700;color:${col};">Gate: ${ov.toUpperCase()}</div>
        ${ov === 'ship' ? `<div style="color:#16a34a;font-weight:600;margin-top:4px;">✓ Ready to export</div>` : ''}
        ${rows}
    </div>`;
}

function _wlSideHtml() {
    const s = _wlSummary || {};
    const gapImpact = (s.open_impact_by_kind && s.open_impact_by_kind.suspected_gap) || 0;
    const uncertain = (s.by_kind && s.by_kind.uncertain_event) || 0;
    const impact = Math.round(s.open_impact || 0);
    return `<div style="border:1px solid #e5e7eb;border-radius:8px;padding:12px;font-size:13px;">
        <div style="font-weight:700;margin-bottom:6px;">Live count</div>
        <div>Running total: <b>${(_wlTotal || 0).toLocaleString()}</b> veh</div>
        <div style="font-weight:700;margin:8px 0 6px;">Remaining work</div>
        <div><b>${_wlCards.length}</b> cards · <b>${s.open || 0}</b> flags ·
            est. impact ~<b>${impact}</b> veh to a clean queue</div>
        <div>Est. missed (gaps): <b>${Math.round(gapImpact)}</b></div>
        <div>Uncertain to confirm: <b>${uncertain}</b></div>
        ${_wlGateRowsHtml()}
        <button class="btn-secondary" style="margin-top:10px;" onclick="_wlRebuild()">Rebuild queue</button>
        <div class="helper-text" style="margin-top:8px;">Z undo (${_wlUndoStack.length} available)</div>
        <p class="helper-text" style="margin-top:6px;">Keys: Enter accept · 1–4 movement ·
            Shift+1–4 batch movement · Del reject · A add-missed · D dismiss ·
            X next card · . next in group · B resolve group · Z undo ·
            &larr;/&rarr; scrub 1 s · [ ] frame · space pause · O overlay</p>
    </div>`;
}

function _wlMountFrame() {
    const vid = document.getElementById('wl-video');
    const canvas = document.getElementById('wl-canvas');
    if (!vid || !canvas || !_wlFlag.clip) return;
    const c = _wlFlag.clip;
    vid.src = `/api/projects/${_wlPid}/videos/${c.video_id}/stream`;
    // exact-frame landing: event flags at the event moment, gap flags
    // at the interval start (operator spec: no pre-roll)
    const startAt = _wlFlag.kind === 'uncertain_event'
        ? Number(c.center_seconds || c.start_seconds || 0)
        : Number(c.start_seconds || 0);
    _wlSeconds = startAt;
    vid.addEventListener('loadedmetadata', () => {
        canvas.width = vid.videoWidth || 1280;
        canvas.height = vid.videoHeight || 720;
        vid.currentTime = startAt;
        if (_wlFlag.kind === 'uncertain_event') vid.play().catch(() => {});
    }, { once: true });
    // event clips loop over their padded window
    vid.addEventListener('timeupdate', () => {
        if (_wlFlag && _wlFlag.kind === 'uncertain_event'
                && vid.currentTime > Number(c.end_seconds || 0) + 1.5) {
            vid.currentTime = Number(c.start_seconds || 0);
        }
        _wlSeconds = vid.currentTime;
        const lbl = document.getElementById('wl-scrub-label');
        if (lbl) lbl.textContent = _wlFmt(_wlSeconds);
        const scr = document.getElementById('wl-scrub');
        if (scr && Math.abs(Number(scr.value) - _wlSeconds) > 1.5) {
            scr.value = Math.floor(_wlSeconds);
        }
    });
    canvas.onclick = _wlFlag.kind === 'suspected_gap' ? _wlCanvasClick : null;
    _wlFetchOverlayTracks();
    _wlStartOverlayLoop();
}

// --- track overlay (REVIEW-UI) ----------------------------------------------

let _wlTracks = [];
let _wlRafId = null;
let _wlOverlayAll = true;

async function _wlFetchOverlayTracks() {
    _wlTracks = [];
    const f = _wlFlag;
    if (!f || !f.clip || !f.camera_id) return;
    const pad = f.kind === 'uncertain_event' ? 8 : 0;
    const lo = Math.max(0, Number(f.clip.start_seconds || 0) - pad);
    const hi = Number(f.clip.end_seconds || lo) + pad;
    try {
        const r = await API.get(`/api/projects/${_wlPid}/cameras/${f.camera_id}` +
            `/tracks?t_lo=${lo.toFixed(1)}&t_hi=${hi.toFixed(1)}`);
        _wlTracks = (r && r.tracks) || [];
    } catch (e) { /* overlay is decoration; the reviewer works without it */ }
}

function _wlStartOverlayLoop() {
    if (_wlRafId) cancelAnimationFrame(_wlRafId);
    const step = () => {
        _wlRafId = requestAnimationFrame(step);
        _wlDrawOverlay();
        const vt = document.getElementById('wl-vtime');
        const vid = document.getElementById('wl-video');
        if (vt && vid) vt.textContent = _wlFmt(vid.currentTime || 0);
    };
    _wlRafId = requestAnimationFrame(step);
}

function _wlBoxAt(pts, t) {
    // binary search + interpolation; pts = [[t,cx,cy,bw,bh],...]
    if (!pts.length || t < pts[0][0] - 0.4
            || t > pts[pts.length - 1][0] + 0.4) return null;
    let lo = 0, hi = pts.length - 1;
    while (lo < hi - 1) {
        const mid = (lo + hi) >> 1;
        if (pts[mid][0] <= t) lo = mid; else hi = mid;
    }
    const a = pts[lo], b = pts[Math.min(hi, pts.length - 1)];
    const f = b[0] > a[0] ? Math.max(0, Math.min(1, (t - a[0]) / (b[0] - a[0]))) : 0;
    return [a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f,
            a[3] + (b[3] - a[3]) * f, a[4] + (b[4] - a[4]) * f];
}

// --- looping clip (frame-flipbook) ------------------------------------------

function _wlStopFlip() {
    // REVIEW-UI: the flipbook is retired; this now tears down the video
    // player + overlay loop (name kept — every card transition calls it).
    if (_wlFlipTimer) { clearInterval(_wlFlipTimer); _wlFlipTimer = null; }
    _wlFlipFrames = []; _wlFlipIdx = 0;
    if (_wlRafId) { cancelAnimationFrame(_wlRafId); _wlRafId = null; }
    const vid = document.getElementById('wl-video');
    if (vid) { vid.pause(); vid.removeAttribute('src'); vid.load(); }
    _wlTracks = [];
}

function _wlStartFlip() {
    const f = _wlFlag;
    if (!f || f.kind !== 'uncertain_event' || !f.clip) return;
    const a = Number(f.clip.start_seconds), b = Number(f.clip.end_seconds);
    if (!(b > a)) return;   // degenerate window — keep the single still
    const vid = f.clip.video_id;
    _wlFlipFrames = [];
    let ready = 0;
    for (let i = 0; i < _WL_CLIP_FRAMES; i++) {
        const s = a + (b - a) * i / (_WL_CLIP_FRAMES - 1);
        const im = new Image();   // preload + hold a ref so the URL stays cached
        im.src = `/api/projects/${_wlPid}/videos/${vid}/frame?seconds=${s.toFixed(2)}`;
        im.onload = () => { if (++ready === 2 && !_wlFlipTimer) _wlRunFlip(); };
        _wlFlipFrames.push(im);
    }
}

function _wlRunFlip() {
    _wlFlipTimer = setInterval(() => {
        const img = document.getElementById('wl-frame');
        if (!img || !_wlFlipFrames.length) return;   // re-render dropped the frame
        for (let n = 0; n < _wlFlipFrames.length; n++) {   // advance to next LOADED frame
            _wlFlipIdx = (_wlFlipIdx + 1) % _wlFlipFrames.length;
            if (_wlFlipFrames[_wlFlipIdx].complete) break;
        }
        img.src = _wlFlipFrames[_wlFlipIdx].src;   // cached -> instant swap; onload redraws overlay
    }, _WL_FLIP_MS);
}

function _wlDrawOverlay() {
    const canvas = document.getElementById('wl-canvas');
    const vid = document.getElementById('wl-video');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const t = vid ? (vid.currentTime || 0) : _wlSeconds;
    const evTid = _wlFlag && _wlFlag.event
        ? Number(_wlFlag.event.vehicle_track_id) : null;
    // all-tracks layer (dim) + the flag's own track (bright yellow)
    for (const tr of _wlTracks) {
        const isEv = evTid != null && tr.tid === evTid;
        if (!isEv && !_wlOverlayAll) continue;
        const box = _wlBoxAt(tr.pts, t);
        if (!box) continue;
        const [cx, cy, bw, bh] = box;
        ctx.lineWidth = isEv ? 3 : 1.5;
        ctx.strokeStyle = isEv ? '#ffd479' : 'rgba(180,190,200,0.55)';
        ctx.strokeRect(cx - bw / 2, cy - bh / 2, bw, bh);
        if (isEv) {
            ctx.fillStyle = '#ffd479';
            ctx.font = 'bold 13px system-ui';
            ctx.fillText('#' + tr.tid, cx - bw / 2, cy - bh / 2 - 5);
        }
    }
    // the event's stored trajectory (fallback identity when tid = -1,
    // and the claimed-path context always)
    const ev = _wlFlag && _wlFlag.event;
    if (!ev || !ev.trajectory_data) return;
    let traj; try { traj = JSON.parse(ev.trajectory_data); } catch (e) { return; }
    if (!traj || traj.length < 1) return;
    ctx.setLineDash([5, 5]);
    ctx.strokeStyle = 'rgba(0,200,255,0.8)'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(traj[0][0], traj[0][1]);
    for (let i = 1; i < traj.length; i++) ctx.lineTo(traj[i][0], traj[i][1]);
    ctx.stroke();
    ctx.setLineDash([]);
    const last = traj[traj.length - 1];
    ctx.fillStyle = 'rgba(255,60,60,0.95)';
    ctx.beginPath(); ctx.arc(last[0], last[1], 7, 0, Math.PI * 2); ctx.fill();
}

// --- actions ----------------------------------------------------------------

async function _wlPatchFlag(status) {
    await API.patch(`/api/projects/${_wlPid}/flags/${_wlFlag.flag_id}`, { status });
}

async function _wlAfterTerminal() {
    await _wlRefreshList();   // the resolved flag left the open list; stay at _wlPos
    await _wlShow();
}

// --- undo (plan_C_polish §3b) -------------------------------------------
// Entries are pushed AFTER the action's API calls succeed; priors for single
// edits come from the enriched flag at display time, priors for batches from
// the batch endpoint's `changes`. Reverting uses only existing endpoints
// (flag reopen clears resolved_at server-side; the review PATCH accepts an
// explicit manually_edited so an edit-then-undo doesn't leave the event
// falsely marked operator-edited). Add-missed is deliberately not undoable.

function _wlPushUndo(label, flags, events) {
    _wlUndoStack.push({ label, flags: flags || [], events: events || [] });
    if (_wlUndoStack.length > _WL_UNDO_CAP) _wlUndoStack.shift();
}

function _wlEventPrior(patch) {
    const ev = _wlFlag && _wlFlag.event;
    if (!ev) return null;
    return { event_id: ev.event_id,
             patch: { ...patch, manually_edited: !!ev.manually_edited } };
}

async function _wlUndoLast() {
    if (_wlBusy) return;
    const entry = _wlUndoStack.pop();
    if (!entry) { _wlToast('Nothing to undo'); return; }
    _wlBusy = true;
    try {
        for (const ev of entry.events) {
            await API.patch(`/api/projects/${_wlPid}/review/${ev.event_id}`, ev.patch);
        }
        for (const fid of entry.flags) {
            await API.patch(`/api/projects/${_wlPid}/flags/${fid}`, { status: 'open' });
        }
        _wlToast(`Undone: ${entry.label}`);
    } catch (e) {
        alert(`Undo failed (was the queue rebuilt since?): ${e.message || e}`);
    } finally {
        _wlBusy = false;
    }
    await _wlRefreshList();
    await _wlShow();
}

function _wlToast(msg) {
    const el = document.createElement('div');
    el.textContent = msg;
    el.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);'
        + 'background:#111827;color:#f9fafb;padding:8px 16px;border-radius:6px;'
        + 'font-size:13px;z-index:1000;opacity:0.95;';
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2500);
}

async function _wlAccept() {
    await _wlGuard(async () => {
        const fid = _wlFlag.flag_id;
        await _wlPatchFlag('resolved');
        _wlPushUndo('accept', [fid]);
        await _wlAfterTerminal();
    });
}
async function _wlDismiss() {
    await _wlGuard(async () => {
        const fid = _wlFlag.flag_id;
        await _wlPatchFlag('dismissed');
        _wlPushUndo('dismiss', [fid]);
        await _wlAfterTerminal();
    });
}
async function _wlResolveGap() {
    await _wlGuard(async () => {
        const fid = _wlFlag.flag_id;
        await _wlPatchFlag('resolved');
        _wlPushUndo('resolve interval', [fid]);
        await _wlAfterTerminal();
    });
}

async function _wlSetMovement(m) {
    await _wlGuard(async () => {
        const fid = _wlFlag.flag_id;
        const prior = _wlEventPrior({ movement: _wlFlag.event && _wlFlag.event.movement });
        if (_wlFlag.event) {
            await API.patch(`/api/projects/${_wlPid}/review/${_wlFlag.event.event_id}`, { movement: m });
        }
        await _wlPatchFlag('resolved');
        _wlPushUndo(`set movement ${m}`, [fid], prior ? [prior] : []);
        await _wlAfterTerminal();
    });
}

async function _wlReject() {
    await _wlGuard(async () => {
        const fid = _wlFlag.flag_id;
        const prior = _wlEventPrior({ rejected: !!(_wlFlag.event && _wlFlag.event.rejected) });
        if (_wlFlag.event) {
            await API.patch(`/api/projects/${_wlPid}/review/${_wlFlag.event.event_id}`, { rejected: true });
        }
        await _wlPatchFlag('resolved');
        _wlPushUndo('reject phantom', [fid], prior ? [prior] : []);
        await _wlAfterTerminal();
    });
}

async function _wlSkip() {
    if (_wlBusy) return;
    _wlPos = (_wlPos + 1) % Math.max(1, _wlCards.length);   // next CARD
    _wlInner = 0;
    await _wlShow();
}

async function _wlNextInCard() {
    if (_wlBusy) return;
    const card = _wlCards[_wlPos];
    if (!card || card.flags.length < 2) return;
    _wlInner = (_wlInner + 1) % card.flags.length;   // sample members before batching
    await _wlShow();
}

async function _wlBatch(status, movement) {
    await _wlGuard(async () => {
        const r = await API.post(`/api/projects/${_wlPid}/intersections/${_wlIid}/flags/batch`, {
            batch_key: _wlFlag.batch_key, status: status || 'resolved',
            movement: movement || null,
        });
        const changes = r.changes || [];
        // events were only touched when a movement was applied
        const events = movement ? changes
            .filter(c => c.event_id != null)
            .map(c => ({ event_id: c.event_id,
                         patch: { movement: c.prior_movement,
                                  manually_edited: !!c.prior_manually_edited } }))
            : [];
        _wlPushUndo(`batch ${status || 'resolved'}${movement ? ' as ' + movement : ''} ×${r.affected}`,
                    changes.map(c => c.flag_id), events);
        await _wlAfterTerminal();
    });
}

function _wlBatchMove(m) { _wlBatch('resolved', m); }

// --- gap add-missed ---------------------------------------------------------

function _wlScrub(v) {
    _wlSeconds = Number(v);
    const lbl = document.getElementById('wl-scrub-label');
    if (lbl) lbl.textContent = _wlFmt(_wlSeconds);
    const vid = document.getElementById('wl-video');
    if (vid) { vid.pause(); vid.currentTime = _wlSeconds; }
}

function _wlNudge(sec) {
    const vid = document.getElementById('wl-video');
    if (!vid) return;
    vid.pause();
    vid.currentTime = Math.max(0, (vid.currentTime || 0) + sec);
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
    // Undo works even with the queue clear (the last resolve emptied it).
    if (e.key === 'z' || e.key === 'Z') { e.preventDefault(); _wlUndoLast(); return; }
    if (!_wlFlag) return;
    const k = e.key;
    const gap = _wlFlag.kind === 'suspected_gap';
    // Shift+digit must match on e.code — e.key yields '!' etc. on US layouts.
    const shiftMove = (!gap && e.shiftKey && /^Digit[1-4]$/.test(e.code))
        ? _WL_MOVE[e.code.slice(5)] : null;
    let handled = true;
    // REVIEW-UI (operator spec): arrows scrub the video 1 s, [ ] step a
    // single frame, space pauses. Skip moved to X (arrows no longer skip).
    if (k === 'Enter') gap ? _wlResolveGap() : _wlAccept();
    else if (k === 'd' || k === 'D') _wlDismiss();
    else if (k === 'ArrowLeft') _wlNudge(-1);
    else if (k === 'ArrowRight') _wlNudge(1);
    else if (k === '[') _wlNudge(-0.04);
    else if (k === ']') _wlNudge(0.04);
    else if (k === ' ') {
        const vid = document.getElementById('wl-video');
        if (vid) { vid.paused ? vid.play().catch(() => {}) : vid.pause(); }
    }
    else if (k === 'o' || k === 'O') { _wlOverlayAll = !_wlOverlayAll; }
    else if (k === 'x' || k === 'X') _wlSkip();
    else if (k === '.' || k === 'ArrowDown') _wlNextInCard();
    else if ((k === 'b' || k === 'B') && _wlFlag.batch_key && _wlGroupSize() > 1) _wlBatch('resolved');
    else if (gap && (k === 'a' || k === 'A')) _wlToggleAdd();
    else if (shiftMove && (_wlFlag.batch_key || '').startsWith('dest|') && _wlGroupSize() > 1)
        _wlBatchMove(shiftMove);
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
    _wlStopFlip();
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
