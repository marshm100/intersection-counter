# Plan — F3: the playback studio (2026-07-28)

MASTER_PLAN §3-F stage 3, the last studio stage. Grounding finding: the
Phase-9 playback page already exists (`frontend/js/playback.js`) but its
`<video>` points at the FRAME endpoint with an in-code admission that no
streaming endpoint exists — video playback has been stubbed since
Phase 9. One backend piece unblocks both that page and the studio.

## Stage A — range-served video + the studio underlay (ship first)

1. `GET /api/projects/{pid}/videos/{video_id}/stream` — HTTP-Range file
   serving (206 partial content, Accept-Ranges, video/mp4; 200 full-file
   fallback; 416 on bad ranges). No transcoding: the corridor files are
   browser-playable mp4; "the sample window" is a UI clamp
   (`currentTime` + timeupdate loop), not a server segment.
2. `playback.js`: point the existing `<video>` at /stream (removes the
   Phase-9 stub + its file:/// fallback).
3. Calibration studio underlay: a "Play sample" toggle on the
   calibration page swaps the static frame for the `<video>` clamped to
   the auto-cal sample window, with the EXISTING F1 layer toggles
   drawing over it (the canvas is already an overlay; the video sits
   beneath). Pause → the frozen frame IS the calibration background at
   that moment.

## Stage B — sample trajectories persisted + synced replay

1. Auto-cal already observes (frame_no, tracked, trails) via the F2
   hook. Persist a downsampled per-frame track record for the sample
   window into the suggestion payload (`sample_tracks`: [{tid, points:
   [[frame, x, y], ...]}], capped ~500 KB via every-3rd-frame points) —
   written at persist time alongside the existing payload; shape-additive
   (readers ignore unknown keys; no migration).
2. Studio replay: while the sample video plays, draw each live track's
   trail at `currentTime*fps + start_frame` over the video (same canvas,
   honoring the layer toggles). The engineer WATCHES the traffic the
   clusters came from and conforms geometry against motion.

## Verification

Stage A: unit tests for Range parsing (206/200/416, boundary math);
live: play + seek the sample window on cam5 in the studio and on the
playback page. Stage B: payload-shape test (cap + downsample), replay
sync spot-check live (a screenshot with trails mid-playback).

## Non-goals

Transcoding/HLS; editing-gesture changes (F1's editors stay as-is);
persisting anything outside the suggestion payload.
