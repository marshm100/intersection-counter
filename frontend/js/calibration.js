(function () {
    const LEG_COLORS = ['#ef4444', '#3b82f6', '#22c55e', '#f59e0b'];

    let _canvas = null;
    let _ctx = null;
    let _img = null;
    let _numLegs = 4;
    let _legs = [];          // confirmed legs
    let _currentLeg = null;  // leg being confirmed (drawn but not yet named)
    let _drawState = 'idle'; // 'idle' only
    let _currentSeconds = 5;
    let _videoDuration = 0;
    let _scrubTimer = null;

    let _dragLeg = null;    // { idx } — leg currently being dragged
    let _dragMoved = false; // true if mousemove fired with significant movement
    let _editingIdx = -1;   // idx of confirmed leg being edited (-1 = new leg)

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
        _currentSeconds = 5;
        _dragLeg = null;
        _dragMoved = false;
        _editingIdx = -1;

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
                        Click once on each approach arm to place an origin node.
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
        _canvas.removeEventListener('mousedown', _onCanvasMousedown);
        _canvas.removeEventListener('mousemove', _onCanvasMousemove);
        _canvas.removeEventListener('mouseup',   _onCanvasMouseup);
        _canvas.addEventListener('click', _onCanvasClick);
        _canvas.addEventListener('mousedown', _onCanvasMousedown);
        _canvas.addEventListener('mousemove', _onCanvasMousemove);
        _canvas.addEventListener('mouseup',   _onCanvasMouseup);

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

    // ------------------------------------------------------------------ coordinate helper

    function _canvasCoords(e) {
        const rect = _canvas.getBoundingClientRect();
        return {
            x: (e.clientX - rect.left) * (_canvas.width / rect.width),
            y: (e.clientY - rect.top)  * (_canvas.height / rect.height),
        };
    }

    // ------------------------------------------------------------------ drawing

    function _onCanvasClick(e) {
        // If all legs are confirmed and no form is open, ignore clicks
        if (_legs.length >= _numLegs && !_currentLeg) return;
        // Don't start a new leg while a form is open
        if (_currentLeg) return;

        const { x, y } = _canvasCoords(e);

        // If click landed on a confirmed node, mouseup already opened edit form
        if (_legs.some(l => Math.hypot(x - l.origin_zone[0][0], y - l.origin_zone[0][1]) <= 16)) return;

        const heading = _computeNodeHeading([x, y], _canvas.width, _canvas.height);
        _currentLeg = {
            idx: _legs.length,
            label: `Leg ${_legs.length + 1}`,
            cardinal_direction: 'N',
            sort_order: _legs.length,
            origin_zone: [[x, y]],
            reference_heading: heading,
        };

        _redraw();
        _showLegForm(_currentLeg);
        _updateStatus();
    }

    function _onCanvasMousedown(e) {
        if (_currentLeg) return;
        const { x, y } = _canvasCoords(e);
        for (const leg of _legs) {
            const [nx, ny] = leg.origin_zone[0];
            if (Math.hypot(x - nx, y - ny) <= 16) {
                _dragLeg = { idx: leg.idx };
                _dragMoved = false;
                _canvas.style.cursor = 'grabbing';
                e.preventDefault();
                return;
            }
        }
    }

    function _onCanvasMousemove(e) {
        const { x, y } = _canvasCoords(e);
        if (_dragLeg) {
            const cx = Math.max(0, Math.min(_canvas.width, x));
            const cy = Math.max(0, Math.min(_canvas.height, y));
            const leg = _legs.find(l => l.idx === _dragLeg.idx);
            if (leg) {
                leg.origin_zone = [[cx, cy]];
                leg.reference_heading = _computeNodeHeading([cx, cy], _canvas.width, _canvas.height);
                _dragMoved = true;
                _redraw();
            }
            return;
        }
        // Hover cursor
        if (_currentLeg) return;
        const onNode = _legs.some(l => Math.hypot(x - l.origin_zone[0][0], y - l.origin_zone[0][1]) <= 16);
        _canvas.style.cursor = onNode ? 'grab' : 'crosshair';
    }

    function _onCanvasMouseup() {
        if (!_dragLeg) return;
        const { idx } = _dragLeg;
        const wasDrag = _dragMoved;
        _dragLeg = null;
        _dragMoved = false;
        _canvas.style.cursor = 'crosshair';
        if (!wasDrag) {
            _editLeg(idx);
        } else {
            _updateLegList();
        }
    }

    function _computeNodeHeading(p, imgW, imgH) {
        // Direction from node toward image center = expected approach heading
        const cx = imgW / 2 - p[0];
        const cy = imgH / 2 - p[1];
        const heading = (Math.atan2(cx, -cy) * 180 / Math.PI + 360) % 360;
        return Math.round(heading * 10) / 10;
    }

    // ------------------------------------------------------------------ form

    function _editLeg(idx) {
        if (_currentLeg) return;
        _editingIdx = idx;
        const leg = _legs.find(l => l.idx === idx);
        if (leg) _showLegForm(leg);
    }

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

        const isEdit = _editingIdx >= 0;

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
                    ${isEdit ? 'Update' : 'Confirm'} Leg ${leg.idx + 1}
                </button>
                <button onclick="cancelLeg()"
                    class="btn-proc btn-cancel"
                    style="font-size:13px;padding:4px 12px;margin-left:6px;">
                    Cancel
                </button>
            </div>`;
    }

    window.confirmLeg = function (legIdx) {
        const isEdit = _editingIdx >= 0 && _editingIdx === legIdx;
        const source = isEdit ? _legs.find(l => l.idx === legIdx) : _currentLeg;
        if (!source) return;

        const labelEl = document.getElementById(`leg-label-${legIdx}`);
        const dirEl   = document.getElementById(`leg-dir-${legIdx}`);
        source.label              = (labelEl?.value.trim()) || `Leg ${legIdx + 1}`;
        source.cardinal_direction = dirEl?.value || 'N';

        if (!isEdit) {
            _legs.push({ ...source });
            _currentLeg = null;
        }
        _editingIdx = -1;
        document.getElementById('calib-form').style.display = 'none';
        _redraw();
        _updateLegList();
        _updateStatus();
        if (_legs.length >= _numLegs) document.getElementById('calib-save-btn').disabled = false;
    };

    window.cancelLeg = function () {
        _currentLeg = null;
        _editingIdx = -1;
        _drawState = 'idle';
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

    window.editLeg = _editLeg;

    // ------------------------------------------------------------------ canvas rendering

    function _redraw() {
        if (!_canvas || !_ctx || !_img.complete) return;
        _ctx.clearRect(0, 0, _canvas.width, _canvas.height);
        _ctx.drawImage(_img, 0, 0);

        for (const leg of _legs) {
            _drawNode(leg.origin_zone[0], LEG_COLORS[leg.idx % LEG_COLORS.length], leg.label);
        }

        if (_currentLeg) {
            _drawNode(_currentLeg.origin_zone[0],
                LEG_COLORS[_currentLeg.idx % LEG_COLORS.length], '');
        }
    }

    function _drawNode(p, color, label) {
        _ctx.beginPath();
        _ctx.arc(p[0], p[1], 12, 0, 2 * Math.PI);
        _ctx.fillStyle = color;
        _ctx.fill();

        if (label) {
            _ctx.fillStyle = '#ffffff';
            _ctx.font = 'bold 13px sans-serif';
            _ctx.textAlign = 'center';
            _ctx.textBaseline = 'middle';
            _ctx.fillText(label, p[0], p[1]);
            _ctx.textAlign = 'left';
            _ctx.textBaseline = 'alphabetic';
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
                <span style="flex:1;">${escapeHtml(leg.label)} (${escapeHtml(leg.cardinal_direction)}) ${leg.reference_heading}°</span>
                <button onclick="editLeg(${leg.idx})"
                    style="font-size:11px;padding:1px 6px;color:#3b82f6;background:none;border:1px solid #3b82f6;border-radius:3px;cursor:pointer;">
                    Edit
                </button>
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
        if (_currentLeg) {
            el.textContent = 'Fill in leg details and click Confirm.';
        } else if (_editingIdx >= 0) {
            el.textContent = `Editing Leg ${_editingIdx + 1}. Update details and click Update.`;
        } else if (_legs.length >= _numLegs) {
            el.textContent = `All ${_numLegs} legs placed. Click Save Calibration to confirm.`;
        } else {
            el.textContent = `Place node ${_legs.length + 1} of ${_numLegs}: click on an approach arm.`;
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
