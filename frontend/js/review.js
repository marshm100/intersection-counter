// Default rejected filter to 'false' so the user sees active events first.
let _reviewFilters = { leg_id: '', movement: '', low_confidence: false, rejected: 'false' };

async function renderReviewPage() {
    _reviewFilters = { leg_id: '', movement: '', low_confidence: false, rejected: 'false' };
    await loadReviewPage(1);
}

async function loadReviewPage(page = 1) {
    const pid = AppState.currentProject;
    if (!pid) { showPage('page-projects'); loadProjectList(); return; }

    const section = document.getElementById('page-review');
    section.innerHTML = '<p class="empty-message">Loading...</p>';

    let params = `page=${page}&page_size=50`;
    if (_reviewFilters.leg_id) params += `&leg_id=${encodeURIComponent(_reviewFilters.leg_id)}`;
    if (_reviewFilters.movement) params += `&movement=${encodeURIComponent(_reviewFilters.movement)}`;
    if (_reviewFilters.low_confidence) params += `&low_confidence=true`;
    if (_reviewFilters.rejected !== '') params += `&rejected=${_reviewFilters.rejected}`;

    let data;
    try {
        data = await API.get(`/api/projects/${pid}/review?${params}`);
    } catch (e) {
        section.innerHTML = '<p class="empty-message">Could not load review data.</p>';
        return;
    }

    // Collect unique legs from current page for filter dropdown
    const legOptions = _buildLegOptions(data.events);

    let html = '';

    // Navigation
    html += '<div class="processing-header">';
    html += '<a href="#" class="back-link" onclick="showPage(\'page-dashboard\'); loadDashboardPage(); return false;">&larr; Back to Dashboard</a>';
    html += '<h2>Review Events</h2>';
    html += '</div>';

    // Filters
    html += '<div class="review-filters">';
    html += `<label>Leg: <select onchange="_reviewFilters.leg_id=this.value; loadReviewPage(1)">
        <option value="">All</option>${legOptions}</select></label>`;
    html += `<label>Movement: <select onchange="_reviewFilters.movement=this.value; loadReviewPage(1)">
        <option value="">All</option>
        <option value="through"${_reviewFilters.movement==='through'?' selected':''}>Through</option>
        <option value="left"${_reviewFilters.movement==='left'?' selected':''}>Left</option>
        <option value="right"${_reviewFilters.movement==='right'?' selected':''}>Right</option>
        <option value="u_turn"${_reviewFilters.movement==='u_turn'?' selected':''}>U-Turn</option>
    </select></label>`;
    html += `<label><input type="checkbox" ${_reviewFilters.low_confidence ? 'checked' : ''}
        onchange="_reviewFilters.low_confidence=this.checked; loadReviewPage(1)"> Low confidence only</label>`;
    html += `<label>Status: <select onchange="_reviewFilters.rejected=this.value; loadReviewPage(1)">
        <option value="false"${_reviewFilters.rejected==='false'?' selected':''}>Active only</option>
        <option value="true"${_reviewFilters.rejected==='true'?' selected':''}>Rejected only</option>
        <option value=""${_reviewFilters.rejected===''?' selected':''}>All</option>
    </select></label>`;
    html += '</div>';

    // Table
    if (data.events.length === 0) {
        html += '<p class="empty-message">No events match the current filters.</p>';
    } else {
        html += '<table class="review-table"><thead><tr>';
        html += '<th>ID</th><th>Leg</th><th>Movement</th><th>Class</th><th>Det.Conf</th><th>Traj.Conf</th><th>Time</th><th>Edited</th><th>Actions</th>';
        html += '</tr></thead><tbody>';
        for (const ev of data.events) {
            html += _reviewRow(ev);
        }
        html += '</tbody></table>';
    }

    // Pagination
    if (data.pages > 1) {
        html += '<div class="pagination-row">';
        html += `<button onclick="loadReviewPage(${page - 1})" ${page <= 1 ? 'disabled' : ''}>Prev</button>`;
        html += `<span>Page ${data.page} of ${data.pages}</span>`;
        html += `<button onclick="loadReviewPage(${page + 1})" ${page >= data.pages ? 'disabled' : ''}>Next</button>`;
        html += '</div>';
    }

    section.innerHTML = html;

    // Delegate edit/reject/preview button clicks to avoid inline onclick with user data
    section.addEventListener('click', function (e) {
        const editBtn = e.target.closest('.btn-review-edit');
        if (editBtn) {
            _startEdit(
                parseInt(editBtn.dataset.eventId, 10),
                editBtn.dataset.movement,
                editBtn.dataset.vehicleClass,
            );
            return;
        }
        const rejectBtn = e.target.closest('.btn-review-reject');
        if (rejectBtn) {
            _toggleReject(
                parseInt(rejectBtn.dataset.eventId, 10),
                rejectBtn.dataset.rejected === '1',
            );
            return;
        }
        const previewBtn = e.target.closest('.btn-review-preview');
        if (previewBtn) {
            _showPreview(parseInt(previewBtn.dataset.eventId, 10));
        }
    });
}

function _buildLegOptions(events) {
    const seen = new Map();
    for (const ev of events) {
        if (!seen.has(ev.origin_leg_id)) seen.set(ev.origin_leg_id, ev.leg_label);
    }
    return [...seen.entries()]
        .map(([id, label]) => `<option value="${id}" ${String(_reviewFilters.leg_id) === String(id) ? 'selected' : ''}>${_escR(label)}</option>`)
        .join('');
}

function _reviewRow(ev) {
    const trajClass = ev.trajectory_confidence < 0.5 ? ' class="confidence-low"' : '';
    const rowClass = ev.rejected ? ' class="review-row-rejected"' : '';
    const rejectLabel = ev.rejected ? 'Unreject' : 'Reject';
    return `<tr id="review-row-${ev.event_id}"${rowClass}>
        <td>${ev.event_id}</td>
        <td>${_escR(ev.leg_label)}</td>
        <td id="rv-mov-${ev.event_id}">${_escR(ev.movement)}</td>
        <td id="rv-cls-${ev.event_id}">${_escR(ev.vehicle_class)}</td>
        <td>${(ev.detection_confidence * 100).toFixed(0)}%</td>
        <td${trajClass}>${(ev.trajectory_confidence * 100).toFixed(0)}%</td>
        <td>${ev.timestamp_video != null ? ev.timestamp_video.toFixed(1) + 's' : '—'}</td>
        <td id="rv-edited-${ev.event_id}">${ev.manually_edited ? '✓' : ''}</td>
        <td>
            <button class="btn-edit btn-review-edit"
                data-event-id="${ev.event_id}"
                data-movement="${_escR(ev.movement)}"
                data-vehicle-class="${_escR(ev.vehicle_class)}">Edit</button>
            <button class="btn-preview btn-review-preview"
                data-event-id="${ev.event_id}">Preview</button>
            <button class="btn-reject btn-review-reject"
                data-event-id="${ev.event_id}"
                data-rejected="${ev.rejected ? 1 : 0}">${rejectLabel}</button>
        </td>
    </tr>`;
}

function _startEdit(eventId, movement, vehicleClass) {
    const movCell = document.getElementById(`rv-mov-${eventId}`);
    const clsCell = document.getElementById(`rv-cls-${eventId}`);
    const actCell = movCell.closest('tr').querySelector('td:last-child');

    movCell.innerHTML = `<select id="rv-mov-sel-${eventId}">
        <option value="through"${movement==='through'?' selected':''}>Through</option>
        <option value="left"${movement==='left'?' selected':''}>Left</option>
        <option value="right"${movement==='right'?' selected':''}>Right</option>
        <option value="u_turn"${movement==='u_turn'?' selected':''}>U-Turn</option>
    </select>`;
    clsCell.innerHTML = `<select id="rv-cls-sel-${eventId}">
        <option value="car"${vehicleClass==='car'?' selected':''}>Car</option>
        <option value="motorcycle"${vehicleClass==='motorcycle'?' selected':''}>Motorcycle</option>
        <option value="bus"${vehicleClass==='bus'?' selected':''}>Bus</option>
        <option value="truck"${vehicleClass==='truck'?' selected':''}>Truck</option>
        <option value="unknown"${vehicleClass==='unknown'?' selected':''}>Unknown</option>
    </select>`;
    actCell.innerHTML = `<button class="btn-save" onclick="_saveEdit(${eventId})">Save</button>
        <button class="btn-cancel-edit" data-event-id="${eventId}"
            data-movement="${_escR(movement)}" data-vehicle-class="${_escR(vehicleClass)}"
            onclick="var b=this; _cancelEdit(parseInt(b.dataset.eventId),b.dataset.movement,b.dataset.vehicleClass)">Cancel</button>`;
}

async function _saveEdit(eventId) {
    const pid = AppState.currentProject;
    const movSel = document.getElementById(`rv-mov-sel-${eventId}`);
    const clsSel = document.getElementById(`rv-cls-sel-${eventId}`);
    const newMovement = movSel ? movSel.value : null;
    const newClass = clsSel ? clsSel.value : null;

    let updated;
    try {
        updated = await API.patch(`/api/projects/${pid}/review/${eventId}`, { movement: newMovement, vehicle_class: newClass });
    } catch (e) {
        alert('Failed to save: ' + (e.message || e));
        return;
    }

    const row = document.getElementById(`review-row-${eventId}`);
    if (row) {
        row.outerHTML = _reviewRow(updated);
    }
}

function _cancelEdit(eventId, movement, vehicleClass) {
    document.getElementById(`rv-mov-${eventId}`).textContent = movement;
    document.getElementById(`rv-cls-${eventId}`).textContent = vehicleClass;
    const row = document.getElementById(`review-row-${eventId}`);
    row.querySelector('td:last-child').innerHTML = `<button class="btn-edit btn-review-edit"
        data-event-id="${eventId}"
        data-movement="${_escR(movement)}"
        data-vehicle-class="${_escR(vehicleClass)}">Edit</button>`;
}

async function _toggleReject(eventId, currentlyRejected) {
    const pid = AppState.currentProject;
    let updated;
    try {
        updated = await API.patch(`/api/projects/${pid}/review/${eventId}`, { rejected: !currentlyRejected });
    } catch (e) {
        alert('Failed to update reject state: ' + (e.message || e));
        return;
    }
    const row = document.getElementById(`review-row-${eventId}`);
    if (row) {
        row.outerHTML = _reviewRow(updated);
    }
}

function _showPreview(eventId) {
    const pid = AppState.currentProject;
    const url = `/api/projects/${pid}/review/${eventId}/preview?width=960`;

    // Build/refresh a simple modal overlay with the preview image
    let modal = document.getElementById('review-preview-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'review-preview-modal';
        modal.className = 'review-preview-modal';
        modal.innerHTML = `
            <div class="review-preview-backdrop"></div>
            <div class="review-preview-content">
                <button class="review-preview-close" type="button">×</button>
                <img class="review-preview-img" alt="Event preview" />
                <div class="review-preview-caption"></div>
            </div>`;
        document.body.appendChild(modal);
        modal.querySelector('.review-preview-backdrop').addEventListener('click', _hidePreview);
        modal.querySelector('.review-preview-close').addEventListener('click', _hidePreview);
    }
    modal.querySelector('.review-preview-img').src = url;
    modal.querySelector('.review-preview-caption').textContent = `Event #${eventId}`;
    modal.classList.add('open');
}

function _hidePreview() {
    const modal = document.getElementById('review-preview-modal');
    if (modal) modal.classList.remove('open');
}

function _escR(str) {
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/'/g, '&#39;');
}
