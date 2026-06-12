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
    let _iid = null;
    let _intersectionRow = null;     // raw intersection row (incl. calib_* override columns)
    let _calibDefaults = null;        // {tripwire_half_length_px, trajectory_*_angle: numbers}
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

    // ---- Phase 2 polyline-paths state ---------------------------------
    let _paths = [];               // saved paths from GET /paths
    let _drawingPath = null;       // { origin_leg_id, destination_leg_id,
                                   //   movement_label, polyline: [[x,y],...] }
    let _pathFormVisible = false;  // sidebar "new path" form shown?

    // ---- Phase 2.1 operator-channel state ------------------------------
    let _channels = [];            // server shape: {channel_id?, origin_leg_id,
                                   //   destination_leg_id, movement, entry, apex,
                                   //   exit, width_in, width_out}
    let _drawingChannel = null;    // { pts: [[x,y],...], width_in, width_out }
    let _selectedChannel = -1;     // index into _channels (edit mode)
    let _channelsDirty = false;    // unsaved local edits
    let _dragChannel = null;       // { ch, role: entry|apex|exit|win|wout }

    // ---- Phase 3 suggestion state -------------------------------------
    let _suggestion = null;            // GET /calibration/suggestion result
    let _suggestionPreviewOn = false;  // overlay suggested paths on canvas?
    let _suggestionJobStatus = null;   // null | running | error | etc

    async function render(host, pid, cid, opts) {
        opts = opts || {};
        _pid = pid;
        _cid = cid;
        _iid = opts.intersectionId || null;
        _intersectionRow = null;
        _calibDefaults = null;
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
                // leg_id was dropped here previously, which broke the paths
                // form's leg selects (value="undefined") — keep it.
                leg_id: l.leg_id,
                label: l.label,
                cardinal_direction: l.cardinal_direction,
                sort_order: l.sort_order,
                origin_zone: l.origin_zone,
                reference_heading: l.reference_heading,
            }));
        } catch (e) {
            // start fresh
        }

        // Fetch the intersection row so we have current calib_* overrides
        // + defaults to display in the params editor.
        if (_iid != null) {
            try {
                const detail = await API.get(`/api/projects/${pid}/intersections/${_iid}`);
                _intersectionRow = detail.intersection || null;
                _calibDefaults = detail.calibration_defaults || null;
            } catch (e) {
                // params editor will render empty / disabled if fetch failed
            }
        }

        // Fetch existing polyline paths for this camera (Phase 2).
        _paths = [];
        try {
            const r = await API.get(`/api/projects/${pid}/cameras/${cid}/paths`);
            _paths = r.paths || [];
        } catch (e) { /* leave empty */ }
        _drawingPath = null;
        _pathFormVisible = false;

        // Fetch operator-drawn channels (Phase 2.1).
        _channels = [];
        try {
            const r = await API.get(`/api/projects/${pid}/cameras/${cid}/channels`);
            _channels = r.channels || [];
        } catch (e) { /* leave empty */ }
        _drawingChannel = null;
        _selectedChannel = -1;
        _channelsDirty = false;
        _dragChannel = null;

        // Fetch auto-cal suggestion (Phase 3).
        _suggestion = null;
        _suggestionPreviewOn = false;
        try {
            const s = await API.get(`/api/projects/${pid}/cameras/${cid}/calibration/suggestion`);
            if (s && s.status) _suggestion = s;
        } catch (e) { /* no suggestion yet */ }

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
                    <div id="v3-calib-suggestion" style="margin-bottom:10px;"></div>
                    <div id="v3-calib-leg-list"></div>
                    <p id="v3-calib-status" style="margin-top:8px;font-size:13px;color:#6b7280;"></p>
                    <div id="v3-calib-form" style="display:none;margin-top:12px;"></div>
                    <div id="v3-calib-paths" style="margin-top:20px;"></div>
                    <div id="v3-calib-channels" style="margin-top:20px;"></div>
                    <div id="v3-calib-params" style="margin-top:20px;"></div>
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
            _renderParamsEditor();
            _renderPathsSection();
            _renderChannelsSection();
            _renderSuggestionBanner();
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
        // Path-drawing keyboard / mouse finishers.
        _canvas.addEventListener('dblclick', (e) => {
            if (_drawingPath) {
                e.preventDefault();
                window.v3CalibrationFinishPath();
            }
        });
        document.addEventListener('keydown', _onKeydown);

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
        // Channel-drawing mode (Phase 2.1) wins over everything when active:
        // entry -> apex -> exit, 3 clicks; first/last snap to the nearest leg.
        if (_drawingChannel) {
            if (_dragChannel) return;            // a drag just ended
            let p = _canvasCoordsArr(e);
            if (_drawingChannel.pts.length === 0) {
                const n = _nearestLegTo(p);
                if (n && n.d <= 22) p = n.leg.origin_zone[0].slice();
            }
            _drawingChannel.pts.push(p);
            if (_drawingChannel.pts.length === 3) {
                const n = _nearestLegTo(_drawingChannel.pts[2]);
                if (n && n.d <= 22) _drawingChannel.pts[2] = n.leg.origin_zone[0].slice();
                _finishChannelDraw();
            } else {
                _redraw();
                _renderChannelsSection();
            }
            return;
        }

        // Path-drawing mode wins over leg placement when active.
        if (_drawingPath) {
            const { x, y } = _canvasCoords(e);
            _drawingPath.polyline.push([Math.round(x * 10) / 10,
                                        Math.round(y * 10) / 10]);
            _redraw();
            _renderPathsSection();
            return;
        }

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
        // Selected-channel handle drag wins (Phase 2.1).
        if (_selectedChannel >= 0 && !_drawingChannel) {
            const hit = _hitChannelHandle(_canvasCoordsArr(e));
            if (hit) {
                _dragChannel = hit;
                e.preventDefault();
                return;
            }
        }
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
        if (_dragChannel) {
            _moveChannelHandle(_dragChannel, _canvasCoordsArr(e));
            _channelsDirty = true;
            _redraw();
            _renderChannelsSection();
            return;
        }
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
        if (_dragChannel) {
            _dragChannel = null;
            return;
        }
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

        // Saved polyline paths drawn first (under everything else) so the
        // leg dots and calibration overlays stay readable on top.
        _drawChannels();              // operator corridors at the very bottom
        _drawSavedPaths();
        _drawSuggestedPaths();        // dashed overlay when preview is on
        if (_drawingPath) _drawInProgressPath();
        if (_drawingChannel) _drawChannelDraft();

        // Draw calibration-param overlays UNDER the leg nodes/arrows so the
        // dots stay legible on top. Fans are most-transparent, then tripwires,
        // then the leg dot + heading arrow + label.
        for (const leg of _legs) {
            if (leg.reference_heading == null) continue;
            const color = LEG_COLORS[leg.idx % LEG_COLORS.length];
            _drawAngleFan(leg.origin_zone[0], leg.reference_heading);
            _drawTripwire(leg.origin_zone[0], leg.reference_heading, color);
        }
        for (const leg of _legs) {
            _drawNode(leg.origin_zone[0], LEG_COLORS[leg.idx % LEG_COLORS.length], leg.label, leg.reference_heading);
        }
        if (_currentLeg) {
            _drawNode(_currentLeg.origin_zone[0],
                LEG_COLORS[_currentLeg.idx % LEG_COLORS.length], '', _currentLeg.reference_heading);
        }
    }

    // ---- Calibration-param overlays -----------------------------------
    //
    // Live visualization of the four calibration parameters on the video
    // canvas. Re-rendered by _redraw() whenever a value changes in the
    // sidebar — so the engineer sees the geometric effect immediately.

    function _effectiveCalib() {
        const fallback = (col, defKey) => {
            const o = _intersectionRow ? _intersectionRow[col] : null;
            if (o != null) return o;
            return _calibDefaults ? _calibDefaults[defKey] : null;
        };
        return {
            tripwire_half_length_px: fallback(
                'calib_tripwire_half_length_px', 'tripwire_half_length_px'),
            through_max: fallback(
                'calib_trajectory_through_max_angle', 'trajectory_through_max_angle'),
            turn_min: fallback(
                'calib_trajectory_turn_min_angle', 'trajectory_turn_min_angle'),
            uturn_min: fallback(
                'calib_trajectory_uturn_min_angle', 'trajectory_uturn_min_angle'),
        };
    }

    function _drawTripwire(p, heading, color) {
        const halfLen = _effectiveCalib().tripwire_half_length_px;
        if (!halfLen) return;
        // Perpendicular to approach heading. Heading H -> direction
        // (sin H, -cos H); perp adds 90° -> (sin(H+90), -cos(H+90)).
        const perpRad = (heading + 90) * Math.PI / 180;
        const dx = Math.sin(perpRad);
        const dy = -Math.cos(perpRad);
        _ctx.save();
        _ctx.beginPath();
        _ctx.moveTo(p[0] - dx * halfLen, p[1] - dy * halfLen);
        _ctx.lineTo(p[0] + dx * halfLen, p[1] + dy * halfLen);
        _ctx.strokeStyle = color;
        _ctx.globalAlpha = 0.55;
        _ctx.lineWidth = 3;
        _ctx.setLineDash([8, 5]);
        _ctx.stroke();
        _ctx.restore();
    }

    function _drawAngleFan(p, heading) {
        const c = _effectiveCalib();
        if (c.through_max == null || c.turn_min == null || c.uturn_min == null) return;
        const R = 50;
        // Heading-to-canvas-angle: 0°=N=up; canvas 0 rad = east. So canvas
        // angle = (H - 90)°. We draw wedges as angular offsets from this
        // base, sweeping clockwise (canvas-positive).
        const baseRad = (heading - 90) * Math.PI / 180;
        const toRad = d => d * Math.PI / 180;

        function wedge(offsetDegA, offsetDegB, fill, alpha) {
            _ctx.save();
            _ctx.beginPath();
            _ctx.moveTo(p[0], p[1]);
            _ctx.arc(p[0], p[1], R, baseRad + toRad(offsetDegA), baseRad + toRad(offsetDegB), false);
            _ctx.closePath();
            _ctx.globalAlpha = alpha;
            _ctx.fillStyle = fill;
            _ctx.fill();
            _ctx.restore();
        }

        // Through (centered on approach direction): ±through_max°
        wedge(-c.through_max, c.through_max, '#22c55e', 0.32);
        // Right turn (clockwise from approach): [turn_min, uturn_min]
        wedge(c.turn_min, c.uturn_min, '#f59e0b', 0.25);
        // Left turn (CCW from approach): [-uturn_min, -turn_min]
        wedge(-c.uturn_min, -c.turn_min, '#f59e0b', 0.25);
        // U-turn (the back arc): from +uturn_min around past 180° to -uturn_min
        wedge(c.uturn_min, 360 - c.uturn_min, '#ef4444', 0.20);

        // Faint outer ring so the fan has a clear extent even where wedges fade
        _ctx.save();
        _ctx.beginPath();
        _ctx.arc(p[0], p[1], R, 0, 2 * Math.PI);
        _ctx.strokeStyle = '#ffffff';
        _ctx.globalAlpha = 0.25;
        _ctx.lineWidth = 1;
        _ctx.stroke();
        _ctx.restore();
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

    // ---- Per-intersection calibration params --------------------------
    //
    // These knobs are stored per intersection but surfaced here in the
    // leg-calibration sidebar so the engineer sees them at the same time
    // they're placing leg origins. NULL/blank = use the global default
    // (shown as placeholder text).

    const _PARAMS = [
        {
            key: 'tripwire_half_length_px',
            col: 'calib_tripwire_half_length_px',
            label: 'Tripwire half-length (px)',
            help: 'Origin tripwire extends this far each side of the leg origin point. Larger = catches more vehicles entering from the edge; too large risks spurious crossings.',
            step: '10',
            min: '10',
            max: '500',
        },
        {
            key: 'trajectory_through_max_angle',
            col: 'calib_trajectory_through_max_angle',
            label: 'Through max angle (°)',
            help: 'Net heading change at or below this is classified as a through movement.',
            step: '1',
            min: '1',
            max: '89',
        },
        {
            key: 'trajectory_turn_min_angle',
            col: 'calib_trajectory_turn_min_angle',
            label: 'Turn min angle (°)',
            help: 'Net heading change at or above this is a clear left/right turn (between through_max and this is the ambiguous zone).',
            step: '1',
            min: '1',
            max: '179',
        },
        {
            key: 'trajectory_uturn_min_angle',
            col: 'calib_trajectory_uturn_min_angle',
            label: 'U-turn min angle (°)',
            help: 'Net heading change at or above this is classified as a u-turn.',
            step: '1',
            min: '1',
            max: '180',
        },
    ];

    function _renderParamsEditor() {
        const host = document.getElementById('v3-calib-params');
        if (!host) return;
        if (_iid == null || !_calibDefaults) {
            host.innerHTML = '';
            return;
        }
        let html = `
            <div style="border-top:1px solid #e5e7eb;padding-top:14px;">
                <h4 style="margin:0 0 4px;font-size:14px;">Calibration parameters</h4>
                <p style="margin:0 0 12px;font-size:12px;color:#6b7280;">
                    Per-intersection overrides. Leave blank to use the default (shown as placeholder).
                </p>
                <div style="display:flex;flex-direction:column;gap:10px;">`;
        for (const p of _PARAMS) {
            const override = _intersectionRow ? _intersectionRow[p.col] : null;
            const def = _calibDefaults[p.key];
            const value = (override == null) ? '' : String(override);
            const placeholder = `${def} (default)`;
            html += `
                <div>
                    <label style="display:block;font-size:12px;font-weight:600;margin-bottom:2px;">
                        ${escapeHtml(p.label)}
                    </label>
                    <input type="number" id="v3-calib-param-${p.key}"
                        data-key="${p.key}"
                        value="${escapeAttr(value)}"
                        placeholder="${escapeAttr(placeholder)}"
                        step="${p.step}" min="${p.min}" max="${p.max}"
                        style="width:100%;padding:4px 6px;font-size:13px;"
                        onchange="v3CalibrationSaveParam('${p.key}', this.value)" />
                    <p style="margin:2px 0 0;font-size:11px;color:#9ca3af;line-height:1.4;">
                        ${escapeHtml(p.help)}
                    </p>
                </div>`;
        }
        html += `</div>
                <p id="v3-calib-params-status" style="margin-top:10px;font-size:12px;color:#6b7280;min-height:1em;"></p>
            </div>`;
        host.innerHTML = html;
    }

    window.v3CalibrationSaveParam = async function (key, rawValue) {
        if (_iid == null) return;
        const status = document.getElementById('v3-calib-params-status');
        // Build the PATCH body. Empty string => null => clear override (use default).
        const col = `calib_${key}`;
        const body = {};
        if (rawValue === '' || rawValue == null) {
            body[col] = null;
        } else {
            const num = parseFloat(rawValue);
            if (!isFinite(num)) {
                if (status) status.textContent = 'Invalid number; not saved.';
                return;
            }
            body[col] = num;
        }
        try {
            const updated = await API.patch(
                `/api/projects/${_pid}/intersections/${_iid}`, body,
            );
            _intersectionRow = updated;   // refresh override values shown
            _redraw();                     // live-update tripwire/fan overlay
            if (status) {
                const wasCleared = body[col] === null;
                status.textContent = wasCleared
                    ? `Reverted ${key} to default.`
                    : `Saved ${key}.`;
            }
        } catch (e) {
            if (status) status.textContent = 'Save failed: ' + (e.message || String(e));
        }
    };

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
        _drawingPath = null;
        document.removeEventListener('keydown', _onKeydown);
        _img = null;
        _canvas = null;
        _ctx = null;
        const close = _onClose;
        _onClose = null;
        if (close) close();
    };

    // ---- Phase 2 polyline-paths UI ------------------------------------

    const MOVEMENT_COLORS = {
        "through":  "#22c55e",
        "left":     "#3b82f6",
        "right":    "#f59e0b",
        "u_turn":   "#ef4444",
    };

    function _onKeydown(e) {
        if (_drawingChannel) {
            if (e.key === "Escape") {
                window.v3CalibrationCancelChannel();
            } else if (e.key === "Enter") {
                e.preventDefault();
                _finishChannelDraw();      // 2 points + Enter = straight channel
            } else if (e.key === "Backspace") {
                e.preventDefault();
                _drawingChannel.pts.pop();
                _redraw();
                _renderChannelsSection();
            }
            return;
        }
        if (_selectedChannel >= 0 && e.key === "Escape" &&
                e.target.tagName !== "SELECT" && e.target.tagName !== "INPUT") {
            _selectedChannel = -1;
            _redraw();
            _renderChannelsSection();
            return;
        }
        if (!_drawingPath) return;
        if (e.key === "Escape") {
            window.v3CalibrationCancelPath();
        } else if (e.key === "Enter") {
            window.v3CalibrationFinishPath();
        }
    }

    function _drawSavedPaths() {
        if (!_paths || _paths.length === 0) return;
        for (const p of _paths) {
            const color = MOVEMENT_COLORS[p.movement_label] || "#888";
            _drawPolyline(p.polyline, color, /*alpha*/ 0.7,
                          /*lineWidth*/ 2, /*dashed*/ false, /*tipArrow*/ true);
        }
    }

    function _drawInProgressPath() {
        if (!_drawingPath || _drawingPath.polyline.length === 0) return;
        const color = MOVEMENT_COLORS[_drawingPath.movement_label] || "#fff";
        _drawPolyline(_drawingPath.polyline, color, /*alpha*/ 0.95,
                      /*lineWidth*/ 3, /*dashed*/ true, /*tipArrow*/ false);
        // Highlight each clicked point with a small white-ringed dot.
        _ctx.save();
        _ctx.globalAlpha = 1.0;
        for (const [x, y] of _drawingPath.polyline) {
            _ctx.beginPath();
            _ctx.arc(x, y, 4, 0, 2 * Math.PI);
            _ctx.fillStyle = color;
            _ctx.fill();
            _ctx.strokeStyle = "#ffffff";
            _ctx.lineWidth = 1.5;
            _ctx.stroke();
        }
        _ctx.restore();
    }

    function _drawPolyline(pts, color, alpha, lineWidth, dashed, tipArrow) {
        if (!pts || pts.length < 2) return;
        _ctx.save();
        _ctx.globalAlpha = alpha;
        _ctx.strokeStyle = color;
        _ctx.lineWidth = lineWidth;
        if (dashed) _ctx.setLineDash([8, 5]);
        _ctx.beginPath();
        _ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i++) {
            _ctx.lineTo(pts[i][0], pts[i][1]);
        }
        _ctx.stroke();
        _ctx.setLineDash([]);
        if (tipArrow && pts.length >= 2) {
            const tip = pts[pts.length - 1];
            const prev = pts[pts.length - 2];
            const dx = tip[0] - prev[0];
            const dy = tip[1] - prev[1];
            const mag = Math.hypot(dx, dy) || 1;
            const ux = dx / mag, uy = dy / mag;
            const px = -uy, py = ux;       // perpendicular
            const base = [tip[0] - ux * 12, tip[1] - uy * 12];
            _ctx.beginPath();
            _ctx.moveTo(tip[0], tip[1]);
            _ctx.lineTo(base[0] + px * 6, base[1] + py * 6);
            _ctx.lineTo(base[0] - px * 6, base[1] - py * 6);
            _ctx.closePath();
            _ctx.fillStyle = color;
            _ctx.fill();
        }
        _ctx.restore();
    }

    function _renderPathsSection() {
        const host = document.getElementById("v3-calib-paths");
        if (!host) return;
        const legs = _legs.slice().sort((a, b) => a.sort_order - b.sort_order);

        // Show saved paths grouped by origin leg.
        const byOrigin = {};
        for (const p of _paths) {
            (byOrigin[p.origin_leg_id] = byOrigin[p.origin_leg_id] || []).push(p);
        }

        let html = `<div style="border-top:1px solid #e5e7eb;padding-top:14px;">
            <h4 style="margin:0 0 4px;font-size:14px;">Road paths (polylines)</h4>
            <p style="margin:0 0 12px;font-size:12px;color:#6b7280;">
                Each path is one (origin&rarr;destination) road centerline through the
                intersection. The pipeline uses these for curve-aware origin attribution
                and movement labeling.
            </p>`;
        if (_paths.length === 0) {
            html += `<p style="font-size:12px;color:#9ca3af;margin-bottom:8px;">
                No paths saved yet.
            </p>`;
        }
        for (const leg of legs) {
            const group = byOrigin[leg.leg_id] || [];
            if (group.length === 0) continue;
            const color = LEG_COLORS[leg.idx % LEG_COLORS.length];
            html += `<div style="margin-bottom:6px;">
                <div style="font-size:12px;font-weight:600;color:${color};">
                    From ${escapeHtml(leg.label)} (${escapeHtml(leg.cardinal_direction)})
                </div>`;
            for (const p of group) {
                const destLeg = legs.find(l => l.leg_id === p.destination_leg_id);
                const destLbl = destLeg ? destLeg.label : `leg ${p.destination_leg_id}`;
                const moveColor = MOVEMENT_COLORS[p.movement_label] || "#888";
                html += `<div style="display:flex;align-items:center;gap:6px;font-size:11px;padding:2px 0 2px 10px;">
                    <span style="display:inline-block;width:10px;height:10px;background:${moveColor};border-radius:1px;flex-shrink:0;"></span>
                    <span style="flex:1;">&rarr; ${escapeHtml(destLbl)} (${escapeHtml(p.movement_label)}, ${p.polyline.length} pts, ${p.supporting_count}n, ${p.source})</span>
                    <button onclick="v3CalibrationDeletePath(${p.path_id})"
                        style="font-size:10px;padding:1px 4px;color:#ef4444;background:none;border:1px solid #ef4444;border-radius:3px;cursor:pointer;">
                        Del
                    </button>
                </div>`;
            }
            html += `</div>`;
        }

        // Drawing form / in-progress path UI.
        if (_drawingPath) {
            const status = _drawingPath.polyline.length === 0
                ? "Click on the canvas to start drawing the path. Add 2+ points. Enter or double-click to save; Escape to cancel."
                : `${_drawingPath.polyline.length} points placed. Add more, or finish (Enter / double-click).`;
            html += `<div style="margin-top:8px;padding:8px;background:#eff6ff;border:1px solid #3b82f6;border-radius:4px;font-size:12px;">
                <div style="font-weight:600;margin-bottom:4px;">Drawing:
                    L${_drawingPath.origin_leg_id} &rarr; L${_drawingPath.destination_leg_id}
                    (${escapeHtml(_drawingPath.movement_label)})
                </div>
                <p style="margin:0 0 6px;color:#1e40af;">${status}</p>
                <button onclick="v3CalibrationFinishPath()"
                    style="font-size:11px;padding:2px 8px;margin-right:4px;background:#3b82f6;color:white;border:none;border-radius:3px;cursor:pointer;">
                    Finish path
                </button>
                <button onclick="v3CalibrationCancelPath()"
                    style="font-size:11px;padding:2px 8px;background:white;color:#6b7280;border:1px solid #d1d5db;border-radius:3px;cursor:pointer;">
                    Cancel
                </button>
            </div>`;
        } else if (_pathFormVisible) {
            // Show selector form: origin, destination, movement label.
            html += `<div style="margin-top:8px;padding:8px;background:#f3f4f6;border:1px solid #d1d5db;border-radius:4px;font-size:12px;">
                <div style="font-weight:600;margin-bottom:6px;">New path</div>
                <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 6px;align-items:center;">
                    <label>Origin leg:</label>
                    <select id="v3-path-origin" style="font-size:12px;">
                        ${legs.map(l => `<option value="${l.leg_id}">${escapeHtml(l.label)} (${escapeHtml(l.cardinal_direction)})</option>`).join("")}
                    </select>
                    <label>Destination leg:</label>
                    <select id="v3-path-dest" style="font-size:12px;">
                        ${legs.map(l => `<option value="${l.leg_id}">${escapeHtml(l.label)} (${escapeHtml(l.cardinal_direction)})</option>`).join("")}
                    </select>
                    <label>Movement:</label>
                    <select id="v3-path-movement" style="font-size:12px;">
                        <option value="through">through</option>
                        <option value="left">left</option>
                        <option value="right">right</option>
                        <option value="u_turn">u_turn</option>
                    </select>
                </div>
                <div style="margin-top:6px;">
                    <button onclick="v3CalibrationStartDrawPath()"
                        style="font-size:11px;padding:2px 8px;margin-right:4px;background:#22c55e;color:white;border:none;border-radius:3px;cursor:pointer;">
                        Start drawing
                    </button>
                    <button onclick="v3CalibrationHidePathForm()"
                        style="font-size:11px;padding:2px 8px;background:white;color:#6b7280;border:1px solid #d1d5db;border-radius:3px;cursor:pointer;">
                        Cancel
                    </button>
                </div>
            </div>`;
        } else if (_legs.length >= 2) {
            html += `<button onclick="v3CalibrationShowPathForm()"
                style="font-size:12px;padding:4px 10px;margin-top:6px;background:white;color:#3b82f6;border:1px solid #3b82f6;border-radius:3px;cursor:pointer;">
                + New path
            </button>`;
        }
        html += `</div>`;
        host.innerHTML = html;
    }

    window.v3CalibrationShowPathForm = function () {
        if (_legs.length < 2) return;
        _pathFormVisible = true;
        _renderPathsSection();
    };

    window.v3CalibrationHidePathForm = function () {
        _pathFormVisible = false;
        _renderPathsSection();
    };

    window.v3CalibrationStartDrawPath = function () {
        const o = parseInt(document.getElementById("v3-path-origin").value, 10);
        const d = parseInt(document.getElementById("v3-path-dest").value, 10);
        const m = document.getElementById("v3-path-movement").value;
        if (!isFinite(o) || !isFinite(d) || !m) return;
        _drawingPath = {
            origin_leg_id: o,
            destination_leg_id: d,
            movement_label: m,
            polyline: [],
        };
        _pathFormVisible = false;
        _renderPathsSection();
        _redraw();
    };

    window.v3CalibrationCancelPath = function () {
        _drawingPath = null;
        _renderPathsSection();
        _redraw();
    };

    window.v3CalibrationFinishPath = async function () {
        if (!_drawingPath || _drawingPath.polyline.length < 2) {
            // Don't try to save a 0- or 1-point path; just cancel quietly.
            return;
        }
        try {
            const saved = await API.post(
                `/api/projects/${_pid}/cameras/${_cid}/paths`,
                {
                    origin_leg_id: _drawingPath.origin_leg_id,
                    destination_leg_id: _drawingPath.destination_leg_id,
                    polyline: _drawingPath.polyline,
                    movement_label: _drawingPath.movement_label,
                    supporting_count: 0,
                    source: "manual",
                },
            );
            // Refresh local cache from server (include path_id etc.)
            const r = await API.get(`/api/projects/${_pid}/cameras/${_cid}/paths`);
            _paths = r.paths || [];
        } catch (e) {
            alert("Save path failed: " + (e.message || String(e)));
        }
        _drawingPath = null;
        _renderPathsSection();
        _redraw();
    };

    window.v3CalibrationDeletePath = async function (path_id) {
        if (!confirm("Delete this path?")) return;
        try {
            await API.del(`/api/projects/${_pid}/cameras/${_cid}/paths/${path_id}`);
            _paths = _paths.filter(p => p.path_id !== path_id);
        } catch (e) {
            alert("Delete failed: " + (e.message || String(e)));
        }
        _renderPathsSection();
        _redraw();
    };

    // ---- Phase 2.1 operator-channel UI ---------------------------------
    //
    // Port of experiments/channel_tool.html onto the calibration canvas.
    // A channel is a quadratic corridor through entry -> apex -> exit with
    // per-mouth widths. Geometry: control point C = 2*apex - (entry+exit)/2
    // makes the curve pass THROUGH the apex at t=0.5. Channels feed the
    // GT-free bank builder (corridor-claiming + hand-drawn fallback).

    function _canvasCoordsArr(e) {
        const { x, y } = _canvasCoords(e);
        return [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
    }

    function _nearestLegTo(p) {
        let best = null, bd = Infinity;
        for (const l of _legs) {
            const d = Math.hypot(p[0] - l.origin_zone[0][0], p[1] - l.origin_zone[0][1]);
            if (d < bd) { bd = d; best = l; }
        }
        return best ? { leg: best, d: bd } : null;
    }

    // Movement from the ORIGIN/DEST cardinal pair — same world-knowledge rule
    // the GT-free bank builder uses (image-space heading deltas mislabel
    // collinear exits at skewed 4-ways). Heading-delta only as fallback when
    // a cardinal is missing.
    const _CH_LEFT  = { NE: 1, ES: 1, SW: 1, WN: 1 };
    const _CH_RIGHT = { NW: 1, WS: 1, SE: 1, EN: 1 };
    function _chDeriveMovement(oLeg, dLeg) {
        if (!oLeg || !dLeg) return "through";
        if (oLeg.leg_id === dLeg.leg_id) return "u_turn";
        const a = (oLeg.cardinal_direction || "").toUpperCase();
        const b = (dLeg.cardinal_direction || "").toUpperCase();
        if (a && b) {
            if (a === b) return "u_turn";
            if (_CH_LEFT[a + b]) return "left";
            if (_CH_RIGHT[a + b]) return "right";
            return "through";
        }
        const entry = oLeg.reference_heading || 0;
        const exit = ((dLeg.reference_heading || 0) + 180) % 360;
        const delta = ((exit - entry + 540) % 360) - 180;
        if (Math.abs(delta) <= 35) return "through";
        return delta > 0 ? "right" : "left";
    }

    function _chCtrl(ch) {
        return [2 * ch.apex[0] - (ch.entry[0] + ch.exit[0]) / 2,
                2 * ch.apex[1] - (ch.entry[1] + ch.exit[1]) / 2];
    }
    function _chQuadAt(e0, c, x1, t) {
        const u = 1 - t;
        return [u * u * e0[0] + 2 * u * t * c[0] + t * t * x1[0],
                u * u * e0[1] + 2 * u * t * c[1] + t * t * x1[1]];
    }
    function _chQuadTan(e0, c, x1, t) {
        const u = 1 - t;
        return [2 * u * (c[0] - e0[0]) + 2 * t * (x1[0] - c[0]),
                2 * u * (c[1] - e0[1]) + 2 * t * (x1[1] - c[1])];
    }
    function _chUnit(v) {
        const L = Math.hypot(v[0], v[1]) || 1;
        return [v[0] / L, v[1] / L];
    }
    function _chPerp(v) { return [-v[1], v[0]]; }

    function _chCorridorPts(ch, n) {
        n = n || 26;
        const c = _chCtrl(ch), L = [], R = [];
        for (let i = 0; i <= n; i++) {
            const t = i / n;
            const p = _chQuadAt(ch.entry, c, ch.exit, t);
            const nv = _chPerp(_chUnit(_chQuadTan(ch.entry, c, ch.exit, t)));
            const hw = (ch.width_in + (ch.width_out - ch.width_in) * t) / 2;
            L.push([p[0] + nv[0] * hw, p[1] + nv[1] * hw]);
            R.push([p[0] - nv[0] * hw, p[1] - nv[1] * hw]);
        }
        return L.concat(R.reverse());
    }

    function _chTripEnds(center, tan, w) {
        const nv = _chPerp(_chUnit(tan));
        return [[center[0] - nv[0] * w / 2, center[1] - nv[1] * w / 2],
                [center[0] + nv[0] * w / 2, center[1] + nv[1] * w / 2]];
    }

    const _CH_PALETTE = ["#0ea5e9", "#a855f7", "#10b981", "#f97316",
                         "#e11d48", "#8b5cf6", "#14b8a6", "#f43f5e"];
    function _chColor(i) { return _CH_PALETTE[i % _CH_PALETTE.length]; }

    function _drawChannels() {
        for (let i = 0; i < _channels.length; i++) {
            const ch = _channels[i];
            const sel = i === _selectedChannel;
            const color = _chColor(i);
            const c = _chCtrl(ch);
            // corridor fill
            const poly = _chCorridorPts(ch);
            _ctx.save();
            _ctx.globalAlpha = sel ? 0.30 : 0.16;
            _ctx.fillStyle = color;
            _ctx.beginPath();
            _ctx.moveTo(poly[0][0], poly[0][1]);
            for (let k = 1; k < poly.length; k++) _ctx.lineTo(poly[k][0], poly[k][1]);
            _ctx.closePath();
            _ctx.fill();
            // centerline (sampled quadratic)
            _ctx.globalAlpha = 0.95;
            _ctx.strokeStyle = color;
            _ctx.lineWidth = 2;
            _ctx.beginPath();
            _ctx.moveTo(ch.entry[0], ch.entry[1]);
            for (let k = 1; k <= 20; k++) {
                const p = _chQuadAt(ch.entry, c, ch.exit, k / 20);
                _ctx.lineTo(p[0], p[1]);
            }
            _ctx.stroke();
            // mouth tripwires (entry solid, exit dashed)
            const eIn = _chTripEnds(ch.entry, _chQuadTan(ch.entry, c, ch.exit, 0), ch.width_in);
            const eOut = _chTripEnds(ch.exit, _chQuadTan(ch.entry, c, ch.exit, 1), ch.width_out);
            _ctx.lineWidth = 3;
            _ctx.beginPath(); _ctx.moveTo(eIn[0][0], eIn[0][1]); _ctx.lineTo(eIn[1][0], eIn[1][1]); _ctx.stroke();
            _ctx.setLineDash([4, 4]);
            _ctx.beginPath(); _ctx.moveTo(eOut[0][0], eOut[0][1]); _ctx.lineTo(eOut[1][0], eOut[1][1]); _ctx.stroke();
            _ctx.setLineDash([]);
            // label at the apex
            _ctx.font = "bold 11px system-ui";
            _ctx.lineWidth = 3;
            _ctx.strokeStyle = "#000";
            _ctx.fillStyle = color;
            const lbl = `${_chLegCard(ch.origin_leg_id)}→${_chLegCard(ch.destination_leg_id)} ${ch.movement}`;
            _ctx.strokeText(lbl, ch.apex[0] + 8, ch.apex[1] - 8);
            _ctx.fillText(lbl, ch.apex[0] + 8, ch.apex[1] - 8);
            // edit handles
            if (sel) {
                _chHandleDot(ch.entry, "#22c55e", 6);
                _chHandleDot(ch.exit, "#f97316", 6);
                _chHandleDot(ch.apex, "#eab308", 6, true);
                _chHandleDot(eIn[1], "#ffffff", 5);
                _chHandleDot(eOut[1], "#ffffff", 5);
            }
            _ctx.restore();
        }
    }

    function _chHandleDot(p, fill, r, square) {
        _ctx.save();
        _ctx.globalAlpha = 1;
        _ctx.fillStyle = fill;
        _ctx.strokeStyle = "#000";
        _ctx.lineWidth = 1.5;
        if (square) {
            _ctx.fillRect(p[0] - r, p[1] - r, 2 * r, 2 * r);
            _ctx.strokeRect(p[0] - r, p[1] - r, 2 * r, 2 * r);
        } else {
            _ctx.beginPath();
            _ctx.arc(p[0], p[1], r, 0, 2 * Math.PI);
            _ctx.fill();
            _ctx.stroke();
        }
        _ctx.restore();
    }

    function _chLegCard(legId) {
        const l = _legs.find(x => x.leg_id === legId);
        return l ? (l.cardinal_direction || `L${legId}`) : `L${legId}`;
    }

    function _drawChannelDraft() {
        const cols = ["#22c55e", "#eab308", "#f97316"];
        const pts = _drawingChannel.pts;
        for (let i = 0; i < pts.length; i++) _chHandleDot(pts[i], cols[i] || "#fff", 5);
        if (pts.length === 2) {
            _ctx.save();
            _ctx.strokeStyle = "#ffffff";
            _ctx.setLineDash([6, 5]);
            _ctx.lineWidth = 2;
            _ctx.beginPath();
            _ctx.moveTo(pts[0][0], pts[0][1]);
            _ctx.lineTo(pts[1][0], pts[1][1]);
            _ctx.stroke();
            _ctx.restore();
        }
    }

    function _hitChannelHandle(p) {
        const ch = _channels[_selectedChannel];
        if (!ch) return null;
        const c = _chCtrl(ch);
        const eIn = _chTripEnds(ch.entry, _chQuadTan(ch.entry, c, ch.exit, 0), ch.width_in);
        const eOut = _chTripEnds(ch.exit, _chQuadTan(ch.entry, c, ch.exit, 1), ch.width_out);
        const targets = [
            ["win", eIn[1]], ["wout", eOut[1]],
            ["entry", ch.entry], ["exit", ch.exit], ["apex", ch.apex],
        ];
        for (const [role, pt] of targets) {
            if (Math.hypot(p[0] - pt[0], p[1] - pt[1]) <= 10) {
                return { ch, role };
            }
        }
        return null;
    }

    function _moveChannelHandle(drag, p) {
        const ch = drag.ch;
        const c = _chCtrl(ch);
        if (drag.role === "entry") ch.entry = p;
        else if (drag.role === "exit") ch.exit = p;
        else if (drag.role === "apex") ch.apex = p;
        else if (drag.role === "win") {
            const nv = _chPerp(_chUnit(_chQuadTan(ch.entry, c, ch.exit, 0)));
            const d = [p[0] - ch.entry[0], p[1] - ch.entry[1]];
            ch.width_in = Math.max(6, 2 * Math.abs(d[0] * nv[0] + d[1] * nv[1]));
        } else if (drag.role === "wout") {
            const nv = _chPerp(_chUnit(_chQuadTan(ch.entry, c, ch.exit, 1)));
            const d = [p[0] - ch.exit[0], p[1] - ch.exit[1]];
            ch.width_out = Math.max(6, 2 * Math.abs(d[0] * nv[0] + d[1] * nv[1]));
        }
        if (drag.role === "entry" || drag.role === "exit") {
            const o = _nearestLegTo(ch.entry), d = _nearestLegTo(ch.exit);
            if (o && d) {
                ch.origin_leg_id = o.leg.leg_id;
                ch.destination_leg_id = d.leg.leg_id;
                ch.movement = _chDeriveMovement(o.leg, d.leg);
            }
        }
    }

    function _finishChannelDraw() {
        const pts = _drawingChannel ? _drawingChannel.pts : null;
        if (!pts || pts.length < 2) return;
        let entry, apex, exit;
        if (pts.length >= 3) { [entry, apex, exit] = pts; }
        else {
            entry = pts[0]; exit = pts[1];
            apex = [(entry[0] + exit[0]) / 2, (entry[1] + exit[1]) / 2];
        }
        const o = _nearestLegTo(entry), d = _nearestLegTo(exit);
        if (!o || !d) { _drawingChannel = null; return; }
        _channels.push({
            origin_leg_id: o.leg.leg_id,
            destination_leg_id: d.leg.leg_id,
            movement: _chDeriveMovement(o.leg, d.leg),
            entry: entry.slice(), apex: apex.slice(), exit: exit.slice(),
            width_in: _drawingChannel.width_in,
            width_out: _drawingChannel.width_out,
        });
        _drawingChannel = null;
        _selectedChannel = _channels.length - 1;
        _channelsDirty = true;
        _redraw();
        _renderChannelsSection();
    }

    function _renderChannelsSection() {
        const host = document.getElementById("v3-calib-channels");
        if (!host) return;
        const legs = _legs.slice().sort((a, b) => a.sort_order - b.sort_order);
        let html = `<div style="border-top:1px solid #e5e7eb;padding-top:14px;">
            <h4 style="margin:0 0 4px;font-size:14px;">Movement channels
                ${_channelsDirty ? '<span style="color:#f59e0b;font-size:11px;">(unsaved)</span>' : ''}</h4>
            <p style="margin:0 0 10px;font-size:12px;color:#6b7280;">
                Operator-drawn corridors declaring each movement and where it runs.
                Used to bootstrap new sites without ground truth (and to pin flows
                at cameras where leg anchors sit on a through path). Draw the
                THROUGH corridors too, not just turns.
            </p>`;

        if (_drawingChannel) {
            const next = ["entry", "apex (the bend)", "exit"][_drawingChannel.pts.length] || "exit";
            html += `<div style="padding:8px;background:#ecfeff;border:1px solid #0ea5e9;border-radius:4px;font-size:12px;margin-bottom:8px;">
                <b>Drawing channel:</b> next click = <b>${next}</b>.
                Endpoints snap to the nearest leg. 2 clicks + Enter = straight channel.
                Esc cancels, Backspace undoes a point.
                <div style="margin-top:6px;">
                    <button onclick="v3CalibrationCancelChannel()"
                        style="font-size:11px;padding:2px 8px;background:white;color:#6b7280;border:1px solid #d1d5db;border-radius:3px;cursor:pointer;">
                        Cancel
                    </button>
                </div>
            </div>`;
        }

        if (_channels.length === 0 && !_drawingChannel) {
            html += `<p style="font-size:12px;color:#9ca3af;margin-bottom:8px;">No channels yet.</p>`;
        }
        for (let i = 0; i < _channels.length; i++) {
            const ch = _channels[i];
            const sel = i === _selectedChannel;
            html += `<div onclick="v3CalibrationSelectChannel(${i})"
                style="display:flex;align-items:center;gap:6px;font-size:12px;padding:4px 6px;margin-bottom:3px;
                       border:1px solid ${sel ? '#0ea5e9' : '#e5e7eb'};border-radius:4px;cursor:pointer;
                       background:${sel ? '#f0f9ff' : 'white'};">
                <span style="display:inline-block;width:10px;height:10px;background:${_chColor(i)};border-radius:2px;flex-shrink:0;"></span>
                <span style="flex:1;">${escapeHtml(_chLegCard(ch.origin_leg_id))}&rarr;${escapeHtml(_chLegCard(ch.destination_leg_id))}
                    <b>${escapeHtml(ch.movement)}</b>
                    <span style="color:#9ca3af;">in ${Math.round(ch.width_in)} / out ${Math.round(ch.width_out)} px</span></span>
                <button onclick="event.stopPropagation(); v3CalibrationDeleteChannel(${i})"
                    style="font-size:10px;padding:1px 5px;color:#ef4444;background:none;border:1px solid #ef4444;border-radius:3px;cursor:pointer;">
                    Del
                </button>
            </div>`;
        }

        // Selected-channel editor: legs + movement dropdowns.
        const selCh = _channels[_selectedChannel];
        if (selCh && !_drawingChannel) {
            const legOpts = (cur) => legs.map(l =>
                `<option value="${l.leg_id}" ${l.leg_id === cur ? 'selected' : ''}>${escapeHtml(l.label)} (${escapeHtml(l.cardinal_direction)})</option>`).join("");
            html += `<div style="margin-top:6px;padding:8px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:4px;font-size:12px;">
                <div style="font-weight:600;margin-bottom:4px;">Selected channel</div>
                <p style="margin:0 0 6px;color:#6b7280;">Drag the green entry / orange exit / yellow apex
                    on the canvas; white dots set mouth widths. Esc deselects.</p>
                <div style="display:grid;grid-template-columns:auto 1fr;gap:4px 6px;align-items:center;">
                    <label>Origin:</label>
                    <select onchange="v3CalibrationChannelField(${_selectedChannel}, 'origin_leg_id', parseInt(this.value,10))" style="font-size:12px;">${legOpts(selCh.origin_leg_id)}</select>
                    <label>Destination:</label>
                    <select onchange="v3CalibrationChannelField(${_selectedChannel}, 'destination_leg_id', parseInt(this.value,10))" style="font-size:12px;">${legOpts(selCh.destination_leg_id)}</select>
                    <label>Movement:</label>
                    <select onchange="v3CalibrationChannelField(${_selectedChannel}, 'movement', this.value)" style="font-size:12px;">
                        ${["through", "left", "right", "u_turn"].map(m =>
                            `<option value="${m}" ${m === selCh.movement ? 'selected' : ''}>${m}</option>`).join("")}
                    </select>
                </div>
            </div>`;
        }

        if (!_drawingChannel) {
            html += `<div style="margin-top:8px;">
                <button onclick="v3CalibrationNewChannel()" ${_legs.length < 2 ? 'disabled' : ''}
                    style="font-size:12px;padding:4px 10px;margin-right:6px;background:white;color:#0ea5e9;border:1px solid #0ea5e9;border-radius:3px;cursor:pointer;">
                    + New channel
                </button>
                <button onclick="v3CalibrationSaveChannels()" ${_channelsDirty ? '' : 'disabled'}
                    style="font-size:12px;padding:4px 10px;background:${_channelsDirty ? '#0ea5e9' : '#e5e7eb'};color:white;border:none;border-radius:3px;cursor:${_channelsDirty ? 'pointer' : 'default'};">
                    Save channels
                </button>
            </div>`;
        }
        html += `</div>`;
        host.innerHTML = html;
    }

    window.v3CalibrationNewChannel = function () {
        if (_legs.length < 2) return;
        _drawingChannel = { pts: [], width_in: 40, width_out: 40 };
        _selectedChannel = -1;
        _redraw();
        _renderChannelsSection();
    };

    window.v3CalibrationCancelChannel = function () {
        _drawingChannel = null;
        _redraw();
        _renderChannelsSection();
    };

    window.v3CalibrationSelectChannel = function (i) {
        _selectedChannel = (_selectedChannel === i) ? -1 : i;
        _redraw();
        _renderChannelsSection();
    };

    window.v3CalibrationDeleteChannel = function (i) {
        _channels.splice(i, 1);
        if (_selectedChannel === i) _selectedChannel = -1;
        else if (_selectedChannel > i) _selectedChannel--;
        _channelsDirty = true;
        _redraw();
        _renderChannelsSection();
    };

    window.v3CalibrationChannelField = function (i, field, value) {
        const ch = _channels[i];
        if (!ch) return;
        ch[field] = value;
        if (field !== "movement") {
            const o = _legs.find(l => l.leg_id === ch.origin_leg_id);
            const d = _legs.find(l => l.leg_id === ch.destination_leg_id);
            ch.movement = _chDeriveMovement(o, d);
        }
        _channelsDirty = true;
        _redraw();
        _renderChannelsSection();
    };

    window.v3CalibrationSaveChannels = async function () {
        try {
            const r = await API.put(
                `/api/projects/${_pid}/cameras/${_cid}/channels`,
                { channels: _channels.map(ch => ({
                    origin_leg_id: ch.origin_leg_id,
                    destination_leg_id: ch.destination_leg_id,
                    movement: ch.movement,
                    entry: ch.entry, apex: ch.apex, exit: ch.exit,
                    width_in: ch.width_in, width_out: ch.width_out,
                })) },
            );
            _channels = r.channels || [];
            _channelsDirty = false;
        } catch (e) {
            alert("Save channels failed: " + (e.message || String(e)));
        }
        _redraw();
        _renderChannelsSection();
    };

    // ---- Phase 3 suggestion banner + apply flow -----------------------

    function _renderSuggestionBanner() {
        const host = document.getElementById("v3-calib-suggestion");
        if (!host) return;
        const running = _suggestionJobStatus &&
            ["queued", "running"].includes(_suggestionJobStatus.status);
        if (!_suggestion && !running) {
            host.innerHTML = `<button onclick="v3CalibrationStartAutoCal()"
                style="font-size:12px;padding:4px 10px;background:white;color:#7c3aed;border:1px solid #7c3aed;border-radius:3px;cursor:pointer;">
                Run auto-calibration on this video
            </button>`;
            return;
        }
        if (running) {
            const pct = (_suggestionJobStatus.progress_pct || 0).toFixed(1);
            host.innerHTML = `<div style="padding:8px;background:#fef3c7;border:1px solid #f59e0b;border-radius:4px;font-size:12px;">
                Auto-calibration running... ${pct}% (${escapeHtml(_suggestionJobStatus.phase || "")})
                <button onclick="v3CalibrationCancelAutoCal()"
                    style="margin-left:8px;font-size:11px;padding:1px 6px;background:white;color:#92400e;border:1px solid #92400e;border-radius:3px;cursor:pointer;">
                    Cancel
                </button>
            </div>`;
            return;
        }
        if (!_suggestion) { host.innerHTML = ""; return; }
        const s = _suggestion;
        const status = s.status || "pending";
        if (status !== "pending") {
            host.innerHTML = `<div style="padding:6px 8px;background:#f3f4f6;border:1px solid #d1d5db;border-radius:4px;font-size:12px;color:#6b7280;">
                Last auto-cal: <strong>${escapeHtml(status)}</strong>
                (${escapeHtml(s.generated_at || "")})
                <button onclick="v3CalibrationStartAutoCal()"
                    style="margin-left:8px;font-size:11px;padding:1px 6px;background:white;color:#7c3aed;border:1px solid #7c3aed;border-radius:3px;cursor:pointer;">
                    Re-run
                </button>
            </div>`;
            return;
        }
        const payload = s.payload || {};
        const n_zones = (payload.leg_zones || []).length;
        const n_paths = (payload.paths || []).length;
        const traj_kept = ((payload.stats || {}).trajectories_kept || "?");
        host.innerHTML = `<div style="padding:8px;background:#ede9fe;border:1px solid #7c3aed;border-radius:4px;font-size:12px;">
            <div style="font-weight:600;margin-bottom:4px;color:#5b21b6;">
                Auto-calibration ready
            </div>
            <p style="margin:0 0 6px;color:#6d28d9;">
                ${n_zones} legs and ${n_paths} road paths detected from ${traj_kept} observed trajectories.
            </p>
            <button onclick="v3CalibrationToggleSuggestionPreview()"
                style="font-size:11px;padding:2px 8px;margin-right:4px;background:white;color:#5b21b6;border:1px solid #5b21b6;border-radius:3px;cursor:pointer;">
                ${_suggestionPreviewOn ? "Hide preview" : "Preview on canvas"}
            </button>
            <button onclick="v3CalibrationApplySuggestion()"
                style="font-size:11px;padding:2px 8px;margin-right:4px;background:#7c3aed;color:white;border:none;border-radius:3px;cursor:pointer;">
                Apply all
            </button>
            <button onclick="v3CalibrationRejectSuggestion()"
                style="font-size:11px;padding:2px 8px;background:white;color:#6b7280;border:1px solid #d1d5db;border-radius:3px;cursor:pointer;">
                Reject
            </button>
        </div>`;
    }

    function _drawSuggestedPaths() {
        if (!_suggestionPreviewOn || !_suggestion || !_suggestion.payload) return;
        const paths = _suggestion.payload.paths || [];
        for (const p of paths) {
            const color = MOVEMENT_COLORS[p.movement_label] || "#a78bfa";
            // Draw dotted in slightly different color so it's visually
            // distinguishable from saved paths.
            _drawPolyline(p.polyline, color, /*alpha*/ 0.7,
                          /*lineWidth*/ 2, /*dashed*/ true, /*tipArrow*/ false);
        }
        // Suggested leg-zone centroids — small purple rings.
        const zones = _suggestion.payload.leg_zones || [];
        _ctx.save();
        _ctx.globalAlpha = 0.85;
        _ctx.strokeStyle = "#7c3aed";
        _ctx.lineWidth = 2;
        for (const z of zones) {
            const [x, y] = z.origin_point || [0, 0];
            _ctx.beginPath();
            _ctx.arc(x, y, 16, 0, 2 * Math.PI);
            _ctx.stroke();
        }
        _ctx.restore();
    }

    window.v3CalibrationStartAutoCal = async function () {
        try {
            const resp = await API.post(
                `/api/projects/${_pid}/cameras/${_cid}/calibration/suggestion/start`,
                {},  // default sample window: first 15 min
            );
            _suggestionJobStatus = { status: "queued", progress_pct: 0, phase: "queued" };
            _renderSuggestionBanner();
            _pollAutoCalStatus();
        } catch (e) {
            alert("Start auto-cal failed: " + (e.message || String(e)));
        }
    };

    window.v3CalibrationCancelAutoCal = async function () {
        try {
            await API.post(`/api/projects/${_pid}/cameras/${_cid}/calibration/suggestion/cancel`, {});
        } catch (e) {}
    };

    function _pollAutoCalStatus() {
        if (!_suggestionJobStatus) return;
        setTimeout(async () => {
            try {
                const s = await API.get(
                    `/api/projects/${_pid}/cameras/${_cid}/calibration/suggestion/status`,
                );
                _suggestionJobStatus = s;
                if (s.status === "running" || s.status === "queued") {
                    _renderSuggestionBanner();
                    _pollAutoCalStatus();
                } else {
                    // Complete / error / cancelled — refresh suggestion.
                    _suggestionJobStatus = null;
                    try {
                        const sug = await API.get(
                            `/api/projects/${_pid}/cameras/${_cid}/calibration/suggestion`,
                        );
                        _suggestion = (sug && sug.status) ? sug : null;
                    } catch (e) { _suggestion = null; }
                    _renderSuggestionBanner();
                    _redraw();
                }
            } catch (e) {
                _suggestionJobStatus = null;
                _renderSuggestionBanner();
            }
        }, 2000);
    }

    window.v3CalibrationToggleSuggestionPreview = function () {
        _suggestionPreviewOn = !_suggestionPreviewOn;
        _renderSuggestionBanner();
        _redraw();
    };

    window.v3CalibrationApplySuggestion = async function () {
        if (!confirm("Apply auto-cal? This replaces all existing paths for this camera.")) return;
        try {
            const r = await API.post(
                `/api/projects/${_pid}/cameras/${_cid}/calibration/suggestion/apply`, {},
            );
            const skipped = (r.skipped || []).length;
            const applied = r.applied_paths || 0;
            alert(`Applied ${applied} path(s).` +
                  (skipped > 0 ? ` Skipped ${skipped} (no matching leg within 80 px).` : ""));
            _paths = r.current_paths || [];
            // Refresh suggestion to flip status -> applied.
            const sug = await API.get(`/api/projects/${_pid}/cameras/${_cid}/calibration/suggestion`);
            _suggestion = (sug && sug.status) ? sug : null;
            _suggestionPreviewOn = false;
        } catch (e) {
            alert("Apply failed: " + (e.message || String(e)));
        }
        _renderSuggestionBanner();
        _renderPathsSection();
        _redraw();
    };

    window.v3CalibrationRejectSuggestion = async function () {
        try {
            await API.post(`/api/projects/${_pid}/cameras/${_cid}/calibration/suggestion/reject`, {});
            const sug = await API.get(`/api/projects/${_pid}/cameras/${_cid}/calibration/suggestion`);
            _suggestion = (sug && sug.status) ? sug : null;
        } catch (e) {}
        _renderSuggestionBanner();
    };

    window.v3RenderCalibration = render;
})();
