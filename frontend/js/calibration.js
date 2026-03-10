(function () {
    const LEG_COLORS = ['#ef4444', '#3b82f6', '#22c55e', '#f59e0b'];

    let _canvas = null;
    let _ctx = null;
    let _img = null;
    let _numLegs = 4;
    let _legs = [];          // confirmed legs
    let _currentLeg = null;  // leg being confirmed (drawn but not yet named)
    let _drawState = 'idle'; // 'idle' | 'awaiting_second'
    let _firstPoint = null;
    let _currentSeconds = 5;
    let _videoDuration = 0;
    let _scrubTimer = null;

    async function loadCalibrationPage() {
        const pid = AppState.currentProject;
        if (!pid) { showPage('page-projects'); loadProjectList(); return; }

        const section = document.getElementById('page-calibration');
        section.innerHTML = '<p class="empty-message">Loading calibration...</p>';

        let project;
        try {
            project = await API.get(`/api/projects/${pid}`);
        } catch (e) {
            section.innerHTML = '<p class="empty-message">Could not load project.</p>';
            return;
        }

        _numLegs = parseInt(project.num_legs || '4', 10);
        _videoDuration = parseFloat(project.video_duration_seconds || '0');
        _legs = [];
        _currentLeg = null;
        _drawState = 'idle';
        _firstPoint = null;
        _currentSeconds = 5;

        // Load existing calibration
        try {
            const calib = await API.get(`/api/projects/${pid}/calibration`);
            _legs = (calib.legs || []).map((l, i) => ({
                idx: i,
                label: l.label,
                cardinal_direction: l.cardinal_direction,
                sort_order: l.sort_order,
                origin_zone: l.origin_zone,
                reference_heading: l.reference_heading,
            }));
        } catch (e) {
            // no existing calibration — start fresh
        }

        const allDone = _legs.length >= _numLegs;

        section.innerHTML = `
            <div class="processing-header">
                <a href="#" class="back-link" onclick="showPage('page-setup'); loadSetupPage(); return false;">&larr; Back to Setup</a>
                <h2>Calibration</h2>
            </div>
            <div class="calib-layout">
                <div class="calib-canvas-wrap">
                    <p style="font-size:13px;color:#6b7280;margin-bottom:6px;">
                        Click two points on the frame to draw each leg's origin line.
                    </p>
                    <canvas id="calib-canvas" style="border:1px solid #d1d5db;cursor:crosshair;max-width:100%;display:block;"></canvas>
                    <div class="calib-scrubber-row">
                        <span class="calib-scrubber-time" id="calib-time-display">00:00:05</span>
                        <input type="range" id="calib-scrubber"
                            min="0" max="${Math.floor(_videoDuration)}" step="1"
                            value="${_currentSeconds}"
                            style="flex:1;" />
                        <span style="font-size:12px;color:#9ca3af;">${_fmtTime(Math.floor(_videoDuration))}</span>
                    </div>
                </div>
                <div class="calib-sidebar">
                    <div id="calib-leg-list"></div>
                    <p id="calib-status" style="margin-top:8px;font-size:13px;color:#6b7280;"></p>
                    <div id="calib-form" style="display:none;margin-top:12px;"></div>
                    <div style="margin-top:16px;">
                        <button id="calib-save-btn" class="btn-proc btn-start"
                            onclick="saveCalibration()" ${allDone ? '' : 'disabled'}>
                            Save Calibration
                        </button>
                    </div>
                    <div style="margin-top:8px;">
                        <button id="calib-proceed-btn" class="btn-proc btn-start"
                            onclick="proceedFromCalibration()"
                            style="display:${allDone ? 'inline-block' : 'none'};">
                            Proceed to Processing &rarr;
                        </button>
                    </div>
                </div>
            </div>`;

        _canvas = document.getElementById('calib-canvas');
        _ctx = _canvas.getContext('2d');

        _img = new Image();
        _img.crossOrigin = 'anonymous';
        _img.onload = () => {
            _canvas.width = _img.naturalWidth;
            _canvas.height = _img.naturalHeight;
            _redraw();
            _updateLegList();
            _updateStatus();
        };
        _img.onerror = () => {
            document.getElementById('calib-status').textContent =
                'Could not load video frame. Ensure a video is selected.';
        };
        _loadFrame(pid, _currentSeconds);

        _canvas.removeEventListener('click', _onCanvasClick);
        _canvas.addEventListener('click', _onCanvasClick);

        // Wire up scrubber
        const scrubber = document.getElementById('calib-scrubber');
        if (scrubber) {
            scrubber.addEventListener('input', () => {
                _currentSeconds = parseInt(scrubber.value, 10);
                const display = document.getElementById('calib-time-display');
                if (display) display.textContent = _fmtTime(_currentSeconds);
                // Debounce: wait 300 ms after last move before fetching
                clearTimeout(_scrubTimer);
                _scrubTimer = setTimeout(() => _loadFrame(pid, _currentSeconds), 300);
            });
        }
    }

    function _loadFrame(pid, seconds) {
        _img.src = `/api/projects/${pid}/video/frame?seconds=${seconds}&_t=${Date.now()}`;
    }

    function _fmtTime(totalSec) {
        const h = Math.floor(totalSec / 3600);
        const m = Math.floor((totalSec % 3600) / 60);
        const s = totalSec % 60;
        return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    }

    // ------------------------------------------------------------------ drawing

    function _onCanvasClick(e) {
        // If all legs are confirmed and no form is open, ignore clicks
        if (_legs.length >= _numLegs && _drawState === 'idle' && !_currentLeg) return;

        const rect = _canvas.getBoundingClientRect();
        const scaleX = _canvas.width / rect.width;
        const scaleY = _canvas.height / rect.height;
        const x = (e.clientX - rect.left) * scaleX;
        const y = (e.clientY - rect.top) * scaleY;

        if (_drawState === 'idle') {
            _drawState = 'awaiting_second';
            _firstPoint = [x, y];
            _updateStatus();
            _redraw();
        } else if (_drawState === 'awaiting_second') {
            const p1 = _firstPoint;
            const p2 = [x, y];
            _firstPoint = null;
            _drawState = 'idle';

            const heading = _computeHeading(p1, p2, _canvas.width, _canvas.height);
            _currentLeg = {
                idx: _legs.length,
                label: `Leg ${_legs.length + 1}`,
                cardinal_direction: 'N',
                sort_order: _legs.length,
                origin_zone: [p1, p2],
                reference_heading: heading,
            };

            _redraw();
            _showLegForm(_currentLeg);
            _updateStatus();
        }
    }

    function _computeHeading(p1, p2, imgW, imgH) {
        const dx = p2[0] - p1[0];
        const dy = p2[1] - p1[1];
        // Two candidate normals (perpendiculars to the line)
        const n1 = [-dy, dx];
        const n2 = [dy, -dx];
        // Pick the one pointing toward the image centre (inward)
        const cx = imgW / 2 - (p1[0] + p2[0]) / 2;
        const cy = imgH / 2 - (p1[1] + p2[1]) / 2;
        const normal = (n1[0] * cx + n1[1] * cy >= 0) ? n1 : n2;
        // Convert to compass heading: 0°=North(up), CW positive, y-axis points down
        const heading = (Math.atan2(normal[0], -normal[1]) * 180 / Math.PI + 360) % 360;
        return Math.round(heading * 10) / 10;
    }

    // ------------------------------------------------------------------ form

    function _showLegForm(leg) {
        const formDiv = document.getElementById('calib-form');
        const color = LEG_COLORS[leg.idx % LEG_COLORS.length];
        const dirs = ['N', 'S', 'E', 'W', 'NE', 'NW', 'SE', 'SW'];
        const dirLabels = {
            N: 'N — Northbound', S: 'S — Southbound',
            E: 'E — Eastbound', W: 'W — Westbound',
            NE: 'NE — Northeastbound', NW: 'NW — Northwestbound',
            SE: 'SE — Southeastbound', SW: 'SW — Southwestbound',
        };
        const dirOptions = dirs.map(d =>
            `<option value="${d}"${d === leg.cardinal_direction ? ' selected' : ''}>${dirLabels[d]}</option>`
        ).join('');

        formDiv.style.display = '';
        formDiv.innerHTML = `
            <div style="border-left:3px solid ${color};padding-left:10px;">
                <h4 style="margin:0 0 8px;font-size:14px;">Leg ${leg.idx + 1} Details</h4>
                <div style="margin-bottom:6px;">
                    <label style="font-size:13px;display:block;margin-bottom:3px;">Label</label>
                    <input type="text" id="leg-label-${leg.idx}"
                        value="${escapeHtml(leg.label)}"
                        style="width:100%;box-sizing:border-box;"/>
                </div>
                <div style="margin-bottom:6px;">
                    <label style="font-size:13px;display:block;margin-bottom:3px;">Cardinal Direction</label>
                    <select id="leg-dir-${leg.idx}" style="width:100%;">${dirOptions}</select>
                </div>
                <div style="margin-bottom:8px;font-size:12px;color:#6b7280;">
                    Reference heading: <strong>${leg.reference_heading}°</strong>
                </div>
                <button onclick="confirmLeg(${leg.idx})"
                    class="btn-proc btn-start"
                    style="font-size:13px;padding:4px 12px;">
                    Confirm Leg ${leg.idx + 1}
                </button>
                <button onclick="cancelLeg()"
                    class="btn-proc btn-cancel"
                    style="font-size:13px;padding:4px 12px;margin-left:6px;">
                    Cancel
                </button>
            </div>`;
    }

    window.confirmLeg = function (legIdx) {
        if (!_currentLeg || _currentLeg.idx !== legIdx) return;
        const labelEl = document.getElementById(`leg-label-${legIdx}`);
        const dirEl = document.getElementById(`leg-dir-${legIdx}`);
        _currentLeg.label = (labelEl ? labelEl.value.trim() : '') || `Leg ${legIdx + 1}`;
        _currentLeg.cardinal_direction = dirEl ? dirEl.value : 'N';
        _legs.push({ ..._currentLeg });
        _currentLeg = null;
        document.getElementById('calib-form').style.display = 'none';
        _redraw();
        _updateLegList();
        _updateStatus();
        if (_legs.length >= _numLegs) {
            document.getElementById('calib-save-btn').disabled = false;
        }
    };

    window.cancelLeg = function () {
        _currentLeg = null;
        _drawState = 'idle';
        _firstPoint = null;
        document.getElementById('calib-form').style.display = 'none';
        _redraw();
        _updateStatus();
    };

    window.removeLeg = function (idx) {
        _legs = _legs.filter(l => l.idx !== idx).map((l, i) => ({ ...l, idx: i, sort_order: i }));
        _redraw();
        _updateLegList();
        _updateStatus();
        const saveBtn = document.getElementById('calib-save-btn');
        if (saveBtn) saveBtn.disabled = _legs.length < _numLegs;
        const procBtn = document.getElementById('calib-proceed-btn');
        if (procBtn) procBtn.style.display = 'none';
    };

    // ------------------------------------------------------------------ canvas rendering

    function _redraw() {
        if (!_canvas || !_ctx || !_img.complete) return;
        _ctx.clearRect(0, 0, _canvas.width, _canvas.height);
        _ctx.drawImage(_img, 0, 0);

        for (const leg of _legs) {
            _drawLine(leg.origin_zone[0], leg.origin_zone[1],
                LEG_COLORS[leg.idx % LEG_COLORS.length], leg.label);
        }

        if (_firstPoint) {
            _ctx.beginPath();
            _ctx.arc(_firstPoint[0], _firstPoint[1], 6, 0, 2 * Math.PI);
            _ctx.fillStyle = '#ffffff';
            _ctx.fill();
            _ctx.strokeStyle = '#374151';
            _ctx.lineWidth = 2;
            _ctx.stroke();
        }

        if (_currentLeg) {
            _drawLine(_currentLeg.origin_zone[0], _currentLeg.origin_zone[1],
                LEG_COLORS[_currentLeg.idx % LEG_COLORS.length], '');
        }
    }

    function _drawLine(p1, p2, color, label) {
        _ctx.beginPath();
        _ctx.moveTo(p1[0], p1[1]);
        _ctx.lineTo(p2[0], p2[1]);
        _ctx.strokeStyle = color;
        _ctx.lineWidth = 3;
        _ctx.setLineDash([]);
        _ctx.stroke();

        for (const pt of [p1, p2]) {
            _ctx.beginPath();
            _ctx.arc(pt[0], pt[1], 6, 0, 2 * Math.PI);
            _ctx.fillStyle = color;
            _ctx.fill();
        }

        if (label) {
            const mx = (p1[0] + p2[0]) / 2 + 6;
            const my = (p1[1] + p2[1]) / 2 - 6;
            _ctx.font = 'bold 14px sans-serif';
            _ctx.lineWidth = 3;
            _ctx.strokeStyle = '#000000';
            _ctx.strokeText(label, mx, my);
            _ctx.fillStyle = '#ffffff';
            _ctx.fillText(label, mx, my);
        }
    }

    // ------------------------------------------------------------------ UI helpers

    function _updateLegList() {
        const listDiv = document.getElementById('calib-leg-list');
        if (!listDiv) return;
        if (_legs.length === 0) {
            listDiv.innerHTML = '<p style="font-size:13px;color:#6b7280;">No legs drawn yet.</p>';
            return;
        }
        let html = '';
        for (const leg of _legs) {
            const color = LEG_COLORS[leg.idx % LEG_COLORS.length];
            html += `<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;font-size:13px;">
                <span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:${color};flex-shrink:0;"></span>
                <span style="flex:1;">${escapeHtml(leg.label)} (${escapeHtml(leg.cardinal_direction)})</span>
                <button onclick="removeLeg(${leg.idx})"
                    style="font-size:11px;padding:1px 6px;color:#ef4444;background:none;border:1px solid #ef4444;border-radius:3px;cursor:pointer;">
                    Remove
                </button>
            </div>`;
        }
        listDiv.innerHTML = html;
    }

    function _updateStatus() {
        const el = document.getElementById('calib-status');
        if (!el) return;
        if (_drawState === 'awaiting_second') {
            el.textContent = `Leg ${_legs.length + 1}: click the second point to complete the line.`;
        } else if (_currentLeg) {
            el.textContent = 'Fill in leg details and click Confirm.';
        } else if (_legs.length >= _numLegs) {
            el.textContent = `All ${_numLegs} legs drawn. Click Save Calibration to confirm.`;
        } else {
            el.textContent = `Draw leg ${_legs.length + 1} of ${_numLegs}: click the first point.`;
        }
    }

    // ------------------------------------------------------------------ save / proceed

    window.saveCalibration = async function () {
        const pid = AppState.currentProject;
        const payload = _legs.map(l => ({
            label: l.label,
            cardinal_direction: l.cardinal_direction,
            sort_order: l.sort_order,
            origin_zone: l.origin_zone,
            reference_heading: l.reference_heading,
        }));
        try {
            await API.put(`/api/projects/${pid}/calibration/legs`, { legs: payload });
            document.getElementById('calib-status').textContent = 'Calibration saved.';
            document.getElementById('calib-proceed-btn').style.display = 'inline-block';
        } catch (e) {
            document.getElementById('calib-status').textContent =
                'Save failed: ' + (e.message || String(e));
        }
    };

    window.proceedFromCalibration = function () {
        showPage('page-processing');
        loadProcessingPage();
    };

    window.loadCalibrationPage = loadCalibrationPage;
})();
