async function loadExportPage() {
    const pid = AppState.currentProject;
    if (!pid) { showPage('page-projects'); loadProjectList(); return; }

    const section = document.getElementById('page-export');
    section.innerHTML = '<p class="empty-message">Loading export preview...</p>';

    let data;
    try {
        data = await API.get(`/api/projects/${pid}/export/preview`);
    } catch (e) {
        section.innerHTML = '<p class="empty-message">Could not load export data.</p>';
        return;
    }

    let html = '';

    html += '<div class="processing-header">';
    html += '<a href="#" class="back-link" onclick="showPage(\'page-dashboard\'); loadDashboardPage(); return false;">&larr; Back to Dashboard</a>';
    html += '<h2>Export</h2>';
    html += '</div>';

    // Metadata
    html += '<div style="margin-bottom:16px;font-size:14px;color:#374151;">';
    html += `<strong>${escapeHtml(data.project_name)}</strong>`;
    if (data.video_start_time) {
        html += ` &middot; ${escapeHtml(data.video_start_time.substring(0, 10))}`;
    }
    html += ` &middot; ${data.leg_count} leg${data.leg_count !== 1 ? 's' : ''}`;
    html += ` &middot; ${data.total_vehicles} vehicles`;
    html += '</div>';

    // Vehicle-class breakdown (Light/Medium/Articulated) — Miovision parity.
    if (data.class_summary) {
        const cs = data.class_summary;
        html += `<div style="margin-bottom:16px;font-size:13px;color:#374151;">
            <b>Classes:</b> Lights ${(cs.Lights || 0).toLocaleString()}
            &middot; Mediums ${(cs.Mediums || 0).toLocaleString()}
            &middot; Articulated ${(cs['Articulated Trucks'] || 0).toLocaleString()}</div>`;
    }

    // Export-readiness gate (filled async by _loadExportGate — runs the QA
    // acceptance gate across intersections, which can take a few seconds).
    html += '<div id="export-gate" style="margin-bottom:16px;">'
        + '<p class="helper-text">Checking export readiness…</p></div>';

    // TMC preview table
    if (data.tmc_matrix.length > 0) {
        html += '<table class="tmc-table">';
        const hasOther = data.tmc_matrix.some(row => (row.other || 0) > 0);
        html += '<thead><tr><th>Leg</th><th>Through</th><th>Left</th><th>Right</th><th>U-Turn</th>';
        if (hasOther) html += '<th>Other</th>';
        html += '<th>Total</th></tr></thead>';
        html += '<tbody>';
        let totThrough = 0, totLeft = 0, totRight = 0, totUTurn = 0, totOther = 0, totTotal = 0;
        for (const row of data.tmc_matrix) {
            html += `<tr>
                <td>${escapeHtml(row.label)}</td>
                <td>${row.through}</td>
                <td>${row.left}</td>
                <td>${row.right}</td>
                <td>${row.u_turn}</td>`;
            if (hasOther) html += `<td>${row.other || 0}</td>`;
            html += `<td>${row.total}</td>
            </tr>`;
            totThrough += row.through;
            totLeft += row.left;
            totRight += row.right;
            totUTurn += row.u_turn;
            totOther += (row.other || 0);
            totTotal += row.total;
        }
        html += '</tbody>';
        html += `<tfoot><tr><td>Total</td><td>${totThrough}</td><td>${totLeft}</td><td>${totRight}</td><td>${totUTurn}</td>`;
        if (hasOther) html += `<td>${totOther}</td>`;
        html += `<td>${totTotal}</td></tr></tfoot>`;
        html += '</table>';
    } else {
        html += '<p class="empty-message">No events to export. Run processing first.</p>';
    }

    // Download area — populated by _loadExportGate once the gate verdict is known.
    html += '<div id="export-dl-area" style="margin-top:20px;">'
        + '<button class="btn-proc" disabled>Checking readiness…</button></div>';

    section.innerHTML = html;
    _loadExportGate(pid);
}

// --- export readiness gate (MASTER_PLAN §3-A) -------------------------------

const _GATE_STYLE = {
    ship:   { bg: '#dcfce7', fg: '#166534', label: '✓ Ready to export — within the ±5% bar.' },
    review: { bg: '#fef3c7', fg: '#b45309', label: 'Draft — QA review pending.' },
    fail:   { bg: '#fee2e2', fg: '#b91c1c', label: 'Not ready to export.' },
};

async function _loadExportGate(pid) {
    const banner = document.getElementById('export-gate');
    const dl = document.getElementById('export-dl-area');
    let g;
    try {
        g = await API.get(`/api/projects/${pid}/export/gate`);
    } catch (e) {
        if (banner) banner.innerHTML = '<p class="helper-text">Could not check export readiness.</p>';
        if (dl) dl.innerHTML = `<button class="btn-proc btn-start" onclick="downloadExcel('${pid}', false)">Download Excel (.xlsx)</button>`;
        return;
    }
    const st = _GATE_STYLE[g.overall] || _GATE_STYLE.review;

    // detail lines: blocking reasons (fail) and/or warnings (review)
    const reasons = (g.blocking_reasons || []).concat(g.warnings || []);
    let detail = '';
    if (reasons.length) {
        detail = '<ul style="margin:6px 0 0;padding-left:18px;font-weight:400;font-size:13px;">'
            + reasons.map(r => `<li>${escapeHtml(r)}</li>`).join('') + '</ul>';
    }
    // per-intersection traffic lights (Stage-4 4.4, plan_stage4_childtest_ux):
    // one lamp lit per intersection-day + "what stands between you and export"
    // in child language. Presentation only — same gate data as before.
    let rows = '';
    for (const ix of (g.intersections || [])) {
        rows += _exportLightRow(ix);
    }
    if (banner) {
        banner.innerHTML = `<div style="padding:10px 14px;border-radius:6px;background:${st.bg};color:${st.fg};font-weight:700;">
            ${escapeHtml(st.label)}${detail}
        </div>
        <div style="margin-top:10px;display:flex;flex-direction:column;gap:8px;">${rows}</div>`;
    }

    if (!dl) return;
    if (g.blocking) {
        dl.innerHTML = `<button class="btn-proc" disabled title="Resolve the QA gate first">Download blocked</button>
            <button class="btn-secondary" style="margin-left:8px;"
                onclick="_exportOverride('${pid}')">Export anyway (override)</button>
            <p class="helper-text" style="margin-top:6px;">Export is withheld until the blocking items above are resolved (or overridden).</p>`;
    } else if (g.overall === 'review') {
        dl.innerHTML = `<button class="btn-proc btn-start" onclick="downloadExcel('${pid}', false)">Download draft (.xlsx)</button>
            <button class="btn-secondary" style="margin-left:8px;" onclick="downloadPdf('${pid}', false)">Download PDF report</button>
            <p class="helper-text" style="margin-top:6px;">Draft — QA not yet certified (e.g. spot count pending). Clear the QA tab to certify.</p>`;
    } else {
        dl.innerHTML = `<button class="btn-proc btn-start" onclick="downloadExcel('${pid}', false)">Download Excel (.xlsx)</button>
            <button class="btn-secondary" style="margin-left:8px;" onclick="downloadPdf('${pid}', false)">Download PDF report</button>`;
    }
}

// Child-language actions per acceptance item (Stage-4 4.4): what closes it,
// said the way you'd tell a person, not a log line.
const _EXPORT_ITEM_WORDS = {
    spot_count: 'Count a spot window on the QA tab (the tally screen serves it)',
    review_flags: 'Work the review cards',
    corridor_consistency: 'Neighboring intersections disagree — investigate on the QA tab',
    reverse_balance: 'Directional balance looks off — usually real peaking; confirm on the QA tab',
};

function _exportLightRow(ix) {
    const v = ix.blocked ? 'fail' : (ix.overall || 'review');
    const lamp = (color, on) => `<div style="width:14px;height:14px;border-radius:50%;
        margin:2px auto;background:${on ? color : '#e5e7eb'};
        ${on ? `box-shadow:0 0 6px ${color};` : ''}"></div>`;
    const light = `<div style="flex:none;padding:4px;border-radius:6px;background:#1f2937;">
        ${lamp('#ef4444', v === 'fail')}${lamp('#f59e0b', v === 'review')}${lamp('#22c55e', v === 'ship')}
    </div>`;
    const headline = v === 'ship' ? 'Ready to export.'
        : v === 'fail' ? 'Not ready.' : 'Almost — draft only for now.';
    let todo = [];
    for (const n of (ix.notes || [])) todo.push(n);
    for (const it of (ix.items || [])) {
        if (it.verdict === 'fail' || it.verdict === 'review') {
            todo.push(_EXPORT_ITEM_WORDS[it.item] || it.item.replace(/_/g, ' '));
        }
    }
    const list = v === 'ship'
        ? `<div style="font-size:12px;color:#166534;">Nothing — this one is ready.</div>`
        : `<div style="font-size:12px;color:#374151;">
             <b>What stands between you and export:</b>
             <ul style="margin:2px 0 0;padding-left:18px;">
                 ${todo.map(t => `<li>${escapeHtml(t)}</li>`).join('') || '<li>see the QA tab</li>'}
             </ul></div>`;
    return `<div style="display:flex;gap:10px;align-items:flex-start;padding:8px;
            border:1px solid #e5e7eb;border-radius:8px;">
        ${light}
        <div style="min-width:0;">
            <div style="font-weight:700;">${escapeHtml(ix.name)}
                <span style="font-weight:400;color:#6b7280;">— ${headline}</span></div>
            ${list}
        </div>
    </div>`;
}

function _exportOverride(pid) {
    if (confirm('The QA gate is blocking this export (see the reasons above). Export anyway?')) {
        downloadExcel(pid, true);
    }
}

async function downloadExcel(pid, override) {
    return _download(`/api/projects/${pid}/export/download`, override, `project_${pid}_tmc.xlsx`);
}

async function downloadPdf(pid, override) {
    return _download(`/api/projects/${pid}/export/report.pdf`, override, `project_${pid}_tmc_report.pdf`);
}

async function _download(baseUrl, override, filename) {
    try {
        const url = baseUrl + (override ? '?override=true' : '');
        const r = await fetch(url);
        if (r.status === 409) {
            const j = await r.json().catch(() => ({}));
            const reasons = ((j.detail && j.detail.blocking_reasons) || []).join('\n  • ');
            alert('Export blocked by the QA gate:\n  • ' + (reasons || 'not ready')
                + '\n\nUse "Export anyway (override)" to export despite this.');
            return;
        }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const blob = await r.blob();
        const objUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = objUrl;
        a.download = filename;
        a.click();
        setTimeout(() => URL.revokeObjectURL(objUrl), 100);
    } catch (e) {
        alert('Download failed: ' + (e.message || e));
    }
}
