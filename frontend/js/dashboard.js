async function loadDashboardPage() {
    const pid = AppState.currentProject;
    if (!pid) { showPage('page-projects'); loadProjectList(); return; }

    const section = document.getElementById('page-dashboard');
    section.innerHTML = '<p class="empty-message">Loading...</p>';

    let data;
    try {
        data = await API.get(`/api/projects/${pid}/dashboard`);
    } catch (e) {
        section.innerHTML = '<p class="empty-message">Could not load dashboard.</p>';
        return;
    }

    let html = '';

    // Navigation
    html += '<div class="processing-header">';
    html += '<a href="#" class="back-link" onclick="showPage(\'page-processing\'); loadProcessingPage(); return false;">&larr; Back to Processing</a>';
    html += '<h2>Dashboard</h2>';
    html += '<button class="btn-proc btn-start" style="margin-left:auto" onclick="showPage(\'page-review\'); loadReviewPage()">Go to Review &rarr;</button>';
    html += '</div>';

    const noEvents = data.totals.vehicles === 0 && data.totals.pedestrians === 0;

    if (noEvents) {
        html += '<p class="empty-message">No events recorded yet.</p>';
        section.innerHTML = html;
        return;
    }

    // Totals
    html += `<p style="margin-bottom:16px;font-size:15px;">${data.totals.vehicles} vehicles, ${data.totals.pedestrians} pedestrians</p>`;

    // TMC table
    if (data.tmc_matrix.length > 0) {
        html += '<table class="tmc-table">';
        html += '<thead><tr><th>Leg</th><th>Through</th><th>Left</th><th>Right</th><th>U-Turn</th><th>Total</th></tr></thead>';
        html += '<tbody>';
        let totThrough = 0, totLeft = 0, totRight = 0, totUTurn = 0, totTotal = 0;
        for (const row of data.tmc_matrix) {
            html += `<tr>
                <td>${_esc(row.leg_label)}</td>
                <td>${row.through}</td>
                <td>${row.left}</td>
                <td>${row.right}</td>
                <td>${row.u_turn}</td>
                <td>${row.total}</td>
            </tr>`;
            totThrough += row.through; totLeft += row.left; totRight += row.right;
            totUTurn += row.u_turn; totTotal += row.total;
        }
        html += '</tbody>';
        html += `<tfoot><tr><td>Total</td><td>${totThrough}</td><td>${totLeft}</td><td>${totRight}</td><td>${totUTurn}</td><td>${totTotal}</td></tr></tfoot>`;
        html += '</table>';
    }

    // Bar chart
    if (data.time_series.length > 0) {
        const maxVehicles = Math.max(...data.time_series.map(r => r.vehicle_count), 1);
        html += '<h3 style="font-size:14px;color:#6b7280;margin-bottom:8px;">Vehicles per interval</h3>';
        html += '<div class="bar-chart">';
        for (const row of data.time_series) {
            const pct = (row.vehicle_count / maxVehicles * 100).toFixed(1);
            html += `<div class="bar-chart-row">
                <span class="bar-chart-label">${_esc(row.interval_start)}</span>
                <div class="bar-chart-track"><div class="bar-fill" style="width:${pct}%"></div></div>
                <span class="bar-count">${row.vehicle_count}</span>
            </div>`;
        }
        html += '</div>';
    }

    section.innerHTML = html;
}

function _esc(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
