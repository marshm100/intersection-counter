// Camera-scoped calibration view (v3).
//
// Rendered inline inside the Intersections > Camera sub-tab when the user
// clicks "Calibrate" on a camera. Reads/writes legs via the camera-scoped
// backend endpoints, loads its background frame from the camera's first
// video, and gets its leg count from the parent intersection.
//
// Single-instance module — only one calibration view is open at a time.
// Public API:
//   window.v3RenderCalibration(host, pid, cid, opts)
//     host: HTMLElement to render into
//     pid:  project id
//     cid:  camera id
//     opts: { legCount, videoId, videoDuration, cameraLabel, onClose }
//       onClose is invoked when the user clicks "Back to cameras" or after
//       a successful save.

(function () {
    const LEG_COLORS = ['#ef4444', '#3b82f6', '#22c55e', '#f59e0b'];

    let _pid = null;
    let _cid = null;
    let _videoId = null;
    let _onClose = null;

    let _canvas = null;
    let _ctx = null;
    let _img = null;
    let _numLegs = 4;
    let _legs = [];
    let _currentLeg = null;
    let _currentSeconds = 5;
    let _videoDuration = 0;
    let _scrubTimer = null;

    let _dragLeg = null;
    let _dragMoved = false;
    let _editingIdx = -1;

    async function render(host, pid, cid, opts) {
        opts = opts || {};
        _pid = pid;
        _cid = cid;
        _videoId = opts.videoId || null;
        _onClose = typeof opts.onClose === 'function' ? opts.onClose : null;
        _numLegs = parseInt(opts.legCount, 10) || 4;
        _videoDuration = parseFloat(opts.videoDuration) || 0;
        _legs = [];
        _currentLeg = null;
        _currentSeconds = 5;
        _dragLeg = null;
        _dragMoved = false;
        _editingIdx = -1;

        host.innerHTML = '<p class="empty-message">Loading calibration...</p>';

        try {
            const calib = await API.get(`/api/projects/${pid}/cameras/${cid}/calibration`);
            _legs = (calib.legs || []).map((l, i) => ({
                idx: i,
                label: l.label,
                cardinal_direction: l.cardinal_direction,
                sort_order: l.sort_order,
                origin_zone: l.origin_zone,
                reference_heading: l.reference_heading,
            }));
        } catch (e) {
            // start fresh
        }

        if (!_videoId) {
            host.innerHTML = '<p class="empty-message">No videos attached to this camera — upload one in the Videos tab first.</p>'
                + `<p><a href="#" onclick="event.preventDefault(); v3CalibrationBack();">&larr; Back to cameras</a></p>`;
            return;
        }

        const allDone = _legs.length >= _numLegs;
        const camLabel = opts.cameraLabel || `Camera ${cid}`;

        host.innerHTML = `
            <div class="v3-calib-header">
                <a href="#" class="back-link" onclick="event.preventDefault(); v3CalibrationBack();">&larr; Back to cameras</a>
                <h3 style="margin:0;font-size:16px;">Calibrating ${escapeHtml(camLabel)}</h3>
            </div>
            <div class="calib-layout">
                <div class="calib-canvas-wrap">
                    <p style="font-size:13px;color:#6b7280;margin-bottom:6px;">
                        Click once on each approach arm to place an origin node.
                    </p>
                    <canvas id="v3-calib-canvas" style="border:1px solid #d1d5db;cursor:crosshair;max-width:100%;display:block;"></canvas>
                    <div class="calib-scrubber-row">
                        <span class="calib-scrubber-time" id="v3-calib-time-display">00:00:05</span>
                        <input type="range" id="v3-calib-scrubber"
                            min="0" max="${Math.floor(_videoDuration)}" step="1"
                            value="${_currentSeconds}"
                            style="flex:1;" />
                        <span style="font-size:12px;color:#9ca3af;">${_fmtTime(Math.floor(_videoDuration))}</span>
                    </div>
                </div>
                <div class="calib-sidebar">
                    <div id="v3-calib-leg-list"></div>
                    <p id="v3-calib-status" style="margin-top:8px;font-size:13px;color:#6b7280;"></p>
                    <div id="v3-calib-form" style="display:none;margin-top:12px;"></div>
                    <div style="margin-top:16px;">
                        <button id="v3-calib-save-btn" class="btn-proc btn-start"
                            onclick="v3CalibrationSave()" ${allDone ? '' : 'disabled'}>
                            Save Calibration
                        </button>
                    </div>
                </div>
            </div>`;

        _canvas = document.getElementById('v3-calib-canvas');
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
            const el = document.getElementById('v3-calib-status');
            if (el) el.textContent = 'Could not load video frame from this camera.';
        };
        _loadFrame(_currentSeconds);

        _canvas.addEventListener('click', _onCanvasClick);
        _canvas.addEventListener('mousedown', _onCanvasMousedown);
        _canvas.addEventListener('mousemove', _onCanvasMousemove);
        _canvas.addEventListener('mouseup',   _onCanvasMouseup);

        const scrubber = document.getElementById('v3-calib-scrubber');
        if (scrubber) {
            scrubber.addEventListener('input', () => {
                _currentSeconds = parseInt(scrubber.value, 10);
                const display = document.getElementById('v3-calib-time-display');
                if (display) display.textContent = _fmtTime(_currentSeconds);
                clearTimeout(_scrubTimer);
                _scrubTimer = setTimeout(() => _loadFrame(_currentSeconds), 300);
            });
        }
    }

    function _loadFrame(seconds) {
        if (!_videoId) return;
        _img.src = `/api/projects/${_pid}/videos/${_videoId}/frame?seconds=${seconds}&_t=${Date.now()}`;
    }

    function _fmtTime(totalSec) {
        const h = Math.floor(totalSec / 3600);
        const m = Math.floor((totalSec % 3600) / 60);
        const s = totalSec % 60;
        return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    }

    function _canvasCoords(e) {
        const rect = _canvas.getBoundingClientRect();
        return {
            x: (e.clientX - rect.left) * (_canvas.width / rect.width),
            y: (e.clientY - rect.top)  * (_canvas.height / rect.height),
        };
    }

    function _onCanvasClick(e) {
        if (_legs.length >= _numLegs && !_currentLeg) return;
        if (_currentLeg) return;

        const { x, y } = _canvasCoords(e);
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
        const { x, y } = _canvasCoords(e);
        for (const leg of _legs) {
            const [nx, ny] = leg.origin_zone[0];
            if (Math.hypot(x - nx, y - ny) <= 16) {
                _dragLeg = { idx: leg.idx, isCurrentLeg: false };
                _dragMoved = false;
                _canvas.style.cursor = 'grabbing';
                e.preventDefault();
                return;
            }
        }
        if (_currentLeg) {
            const [nx, ny] = _currentLeg.origin_zone[0];
            if (Math.hypot(x - nx, y - ny) <= 16) {
                _dragLeg = { idx: _currentLeg.idx, isCurrentLeg: true };
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
            const target = _dragLeg.isCurrentLeg
                ? _currentLeg
                : _legs.find(l => l.idx === _dragLeg.idx);
            if (target) {
                target.origin_zone = [[cx, cy]];
                target.reference_heading = _computeNodeHeading([cx, cy], _canvas.width, _canvas.height);
                _dragMoved = true;
                _redraw();
                const headingInp = document.getElementById(`v3-leg-heading-${target.idx}`);
                if (headingInp) headingInp.value = target.reference_heading;
            }
            return;
        }
        let onNode = _legs.some(l => Math.hypot(x - l.origin_zone[0][0], y - l.origin_zone[0][1]) <= 16);
        if (!onNode && _currentLeg) {
            const [nx, ny] = _currentLeg.origin_zone[0];
            onNode = Math.hypot(x - nx, y - ny) <= 16;
        }
        _canvas.style.cursor = onNode ? 'grab' : 'crosshair';
    }

    function _onCanvasMouseup() {
        if (!_dragLeg) return;
        const { idx, isCurrentLeg } = _dragLeg;
        const wasDrag = _dragMoved;
        _dragLeg = null;
        _dragMoved = false;
        _canvas.style.cursor = 'crosshair';
        if (isCurrentLeg) {
            if (wasDrag) _updateLegList();
        } else if (!wasDrag) {
            _editLeg(idx);
        } else {
            _updateLegList();
        }
    }

    function _computeNodeHeading(p, imgW, imgH) {
        const cx = imgW / 2 - p[0];
        const cy = imgH / 2 - p[1];
        const heading = (Math.atan2(cx, -cy) * 180 / Math.PI + 360) % 360;
        return Math.round(heading * 10) / 10;
    }

    function _editLeg(idx) {
        if (_currentLeg) return;
        _editingIdx = idx;
        const leg = _legs.find(l => l.idx === idx);
        if (leg) _showLegForm(leg);
    }

    function _showLegForm(leg) {
        const formDiv = document.getElementById('v3-calib-form');
        if (!formDiv) return;
        const color = LEG_COLORS[leg.idx % LEG_COLORS.length];
        const dirs = ['N', 'S', 'E', 'W', 'NE', 'NW', 'SE', 'SW'];
        const dirLabels = {
            N: 'N — Southbound', S: 'S — Northbound',
            E: 'E — Westbound', W: 'W — Eastbound',
            NE: 'NE — Southwestbound', NW: 'NW — Southeastbound',
            SE: 'SE — Northwestbound', SW: 'SW — Northeastbound',
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
                    <input type="text" id="v3-leg-label-${leg.idx}"
                        value="${escapeHtml(leg.label)}"
                        style="width:100%;box-sizing:border-box;"/>
                </div>
                <div style="margin-bottom:6px;">
                    <label style="font-size:13px;display:block;margin-bottom:3px;">Cardinal Direction</label>
                    <select id="v3-leg-dir-${leg.idx}" style="width:100%;">${dirOptions}</select>
                </div>
                <div style="margin-bottom:8px;font-size:12px;color:#6b7280;">
                    <label style="display:block;margin-bottom:3px;">Reference heading</label>
                    <div style="display:flex;align-items:center;gap:6px;">
                        <button type="button" onclick="v3CalibrationRotateHeading(${leg.idx}, -15)"
                            style="font-size:11px;padding:2px 6px;cursor:pointer;">-15°</button>
                        <input type="number" id="v3-leg-heading-${leg.idx}" value="${leg.reference_heading}"
                            min="0" max="360" step="1" style="width:70px;text-align:center;"
                            onchange="v3CalibrationPreviewHeading(${leg.idx})" />
                        <button type="button" onclick="v3CalibrationRotateHeading(${leg.idx}, 15)"
                            style="font-size:11px;padding:2px 6px;cursor:pointer;">+15°</button>
                    </div>
                </div>
                <button onclick="v3CalibrationConfirmLeg(${leg.idx})"
                    class="btn-proc btn-start"
                    style="font-size:13px;padding:4px 12px;">
                    ${isEdit ? 'Update' : 'Confirm'} Leg ${leg.idx + 1}
                </button>
                <button onclick="v3CalibrationCancelLeg()"
                    class="btn-proc btn-cancel"
                    style="font-size:13px;padding:4px 12px;margin-left:6px;">
                    Cancel
                </button>
            </div>`;
    }

    window.v3CalibrationConfirmLeg = function (legIdx) {
        const isEdit = _editingIdx >= 0 && _editingIdx === legIdx;
        const source = isEdit ? _legs.find(l => l.idx === legIdx) : _currentLeg;
        if (!source) return;

        const labelEl = document.getElementById(`v3-leg-label-${legIdx}`);
        const dirEl   = document.getElementById(`v3-leg-dir-${legIdx}`);
        source.label              = (labelEl?.value.trim()) || `Leg ${legIdx + 1}`;
        source.cardinal_direction = dirEl?.value || 'N';
        const headingEl = document.getElementById(`v3-leg-heading-${legIdx}`);
        if (headingEl) {
            let h = parseFloat(headingEl.value) || 0;
            source.reference_heading = ((h % 360) + 360) % 360;
        }

        if (!isEdit) {
            _legs.push({ ...source });
            _currentLeg = null;
        }
        _editingIdx = -1;
        document.getElementById('v3-calib-form').style.display = 'none';
        _redraw();
        _updateLegList();
        _updateStatus();
        if (_legs.length >= _numLegs) {
            const btn = document.getElementById('v3-calib-save-btn');
            if (btn) btn.disabled = false;
        }
    };

    window.v3CalibrationCancelLeg = function () {
        _currentLeg = null;
        _editingIdx = -1;
        document.getElementById('v3-calib-form').style.display = 'none';
        _redraw();
        _updateStatus();
    };

    window.v3CalibrationRemoveLeg = function (idx) {
        _legs = _legs.filter(l => l.idx !== idx).map((l, i) => ({ ...l, idx: i, sort_order: i }));
        _redraw();
        _updateLegList();
        _updateStatus();
        const saveBtn = document.getElementById('v3-calib-save-btn');
        if (saveBtn) saveBtn.disabled = _legs.length < _numLegs;
    };

    window.v3CalibrationEditLeg = _editLeg;

    window.v3CalibrationRotateHeading = function (legIdx, delta) {
        const target = (_currentLeg && _currentLeg.idx === legIdx)
            ? _currentLeg
            : _legs.find(l => l.idx === legIdx);
        if (!target) return;
        let h = (target.reference_heading + delta) % 360;
        if (h < 0) h += 360;
        h = Math.round(h * 10) / 10;
        target.reference_heading = h;
        const inp = document.getElementById(`v3-leg-heading-${legIdx}`);
        if (inp) inp.value = h;
        _redraw();
    };

    window.v3CalibrationPreviewHeading = function (legIdx) {
        const target = (_currentLeg && _currentLeg.idx === legIdx)
            ? _currentLeg
            : _legs.find(l => l.idx === legIdx);
        if (!target) return;
        const inp = document.getElementById(`v3-leg-heading-${legIdx}`);
        if (!inp) return;
        let h = parseFloat(inp.value) || 0;
        h = ((h % 360) + 360) % 360;
        h = Math.round(h * 10) / 10;
        target.reference_heading = h;
        inp.value = h;
        _redraw();
    };

    function _redraw() {
        if (!_canvas || !_ctx || !_img.complete) return;
        _ctx.clearRect(0, 0, _canvas.width, _canvas.height);
        _ctx.drawImage(_img, 0, 0);

        for (const leg of _legs) {
            _drawNode(leg.origin_zone[0], LEG_COLORS[leg.idx % LEG_COLORS.length], leg.label, leg.reference_heading);
        }
        if (_currentLeg) {
            _drawNode(_currentLeg.origin_zone[0],
                LEG_COLORS[_currentLeg.idx % LEG_COLORS.length], '', _currentLeg.reference_heading);
        }
    }

    function _drawNode(p, color, label, heading) {
        _ctx.beginPath();
        _ctx.arc(p[0], p[1], 12, 0, 2 * Math.PI);
        _ctx.fillStyle = color;
        _ctx.fill();

        if (heading != null) {
            const arrowLen = 40;
            const rad = (heading - 90) * Math.PI / 180;
            const ax = p[0] + Math.cos(rad) * arrowLen;
            const ay = p[1] + Math.sin(rad) * arrowLen;
            _ctx.beginPath();
            _ctx.moveTo(p[0], p[1]);
            _ctx.lineTo(ax, ay);
            _ctx.strokeStyle = color;
            _ctx.lineWidth = 2.5;
            _ctx.stroke();
            const headLen = 10;
            const aHead1 = rad + Math.PI * 0.8;
            const aHead2 = rad - Math.PI * 0.8;
            _ctx.beginPath();
            _ctx.moveTo(ax, ay);
            _ctx.lineTo(ax + Math.cos(aHead1) * headLen, ay + Math.sin(aHead1) * headLen);
            _ctx.moveTo(ax, ay);
            _ctx.lineTo(ax + Math.cos(aHead2) * headLen, ay + Math.sin(aHead2) * headLen);
            _ctx.stroke();
        }

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

    function _updateLegList() {
        const listDiv = document.getElementById('v3-calib-leg-list');
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
                <span style="flex:1;">${escapeHtml(leg.label)} (${escapeHtml(leg.cardinal_direction)}) ${Number(leg.reference_heading).toFixed(1)}°</span>
                <button onclick="v3CalibrationEditLeg(${leg.idx})"
                    style="font-size:11px;padding:1px 6px;color:#3b82f6;background:none;border:1px solid #3b82f6;border-radius:3px;cursor:pointer;">
                    Edit
                </button>
                <button onclick="v3CalibrationRemoveLeg(${leg.idx})"
                    style="font-size:11px;padding:1px 6px;color:#ef4444;background:none;border:1px solid #ef4444;border-radius:3px;cursor:pointer;">
                    Remove
                </button>
            </div>`;
        }
        listDiv.innerHTML = html;
    }

    function _updateStatus() {
        const el = document.getElementById('v3-calib-status');
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

    window.v3CalibrationSave = async function () {
        const payload = _legs.map(l => ({
            label: l.label,
            cardinal_direction: l.cardinal_direction,
            sort_order: l.sort_order,
            origin_zone: l.origin_zone,
            reference_heading: l.reference_heading,
        }));
        const statusEl = document.getElementById('v3-calib-status');
        try {
            await API.put(`/api/projects/${_pid}/cameras/${_cid}/calibration/legs`, { legs: payload });
            if (statusEl) statusEl.textContent = 'Calibration saved.';
            if (_onClose) _onClose();
        } catch (e) {
            if (statusEl) statusEl.textContent = 'Save failed: ' + (e.message || String(e));
        }
    };

    window.v3CalibrationBack = function () {
        clearTimeout(_scrubTimer);
        _scrubTimer = null;
        _currentLeg = null;
        _editingIdx = -1;
        _img = null;
        _canvas = null;
        _ctx = null;
        const close = _onClose;
        _onClose = null;
        if (close) close();
    };

    window.v3RenderCalibration = render;
})();
