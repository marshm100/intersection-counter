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
    html += `<strong>${_escExport(data.project_name)}</strong>`;
    if (data.video_start_time) {
        html += ` &middot; ${_escExport(data.video_start_time.substring(0, 10))}`;
    }
    html += ` &middot; ${data.leg_count} leg${data.leg_count !== 1 ? 's' : ''}`;
    html += ` &middot; ${data.total_vehicles} vehicles, ${data.total_pedestrians} pedestrians`;
    html += '</div>';

    // TMC preview table
    if (data.tmc_matrix.length > 0) {
        html += '<table class="tmc-table">';
        html += '<thead><tr><th>Leg</th><th>Through</th><th>Left</th><th>Right</th><th>U-Turn</th><th>Total</th></tr></thead>';
        html += '<tbody>';
        let totThrough = 0, totLeft = 0, totRight = 0, totUTurn = 0, totTotal = 0;
        for (const row of data.tmc_matrix) {
            html += `<tr>
                <td>${_escExport(row.label)}</td>
                <td>${row.through}</td>
                <td>${row.left}</td>
                <td>${row.right}</td>
                <td>${row.u_turn}</td>
                <td>${row.total}</td>
            </tr>`;
            totThrough += row.through;
            totLeft += row.left;
            totRight += row.right;
            totUTurn += row.u_turn;
            totTotal += row.total;
        }
        html += '</tbody>';
        html += `<tfoot><tr><td>Total</td><td>${totThrough}</td><td>${totLeft}</td><td>${totRight}</td><td>${totUTurn}</td><td>${totTotal}</td></tr></tfoot>`;
        html += '</table>';
    } else {
        html += '<p class="empty-message">No events to export. Run processing first.</p>';
    }

    // Download button
    html += `<div style="margin-top:20px;">
        <button class="btn-proc btn-start" style="padding:8px 20px;"
            onclick="downloadExcel(${pid})">
            Download Excel (.xlsx)
        </button>
    </div>`;

    section.innerHTML = html;
}

async function downloadExcel(pid) {
    try {
        const r = await fetch(`/api/projects/${pid}/export/download`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `project_${pid}_tmc.xlsx`;
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        alert('Download failed: ' + (e.message || e));
    }
}

function _escExport(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
