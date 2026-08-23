# Decision: video ingest copies into the project (2026-08-23)

**Context.** Until now, adding a video recorded the absolute path wherever the
file lived. The 2026-08-22 machine transition demonstrated the failure mode in
full: every project's videos pointed at a company OneDrive the new machine
could not reach, blocking gate calibration and operator review until the files
were retrieved and reinstalled by hand. Reference-only ingest decouples media
from the app; source media also commonly lives on SD cards that get reformatted
and network drives that get reorganized.

**Decision (operator ratified 2026-08-23): copy in by default, opt out
explicitly.**

- Adding a video COPIES it to `data/projects/<pid>/videos/<filename>`. A
  project directory is a self-contained study: archive it, move it, hand it to
  a new machine, and everything works (this matches the frozen-base archive
  pattern at C:\dev\_archive).
- `copy_in: false` ("Leave files in place" checkbox) opts out for huge local
  files. Linked rows carry `linked: true` and render with a warning badge.
- Re-adding the same source is idempotent (same-name same-size copy is reused;
  same-name different-size gets a " (2)" suffix).
- The content hash recorded at ingest plus `scripts/reconnect_videos.py`
  (filename match -> size check -> blake2b verification -> repoint) is the
  repair path for anything that still goes missing.
- Cost accepted: disk duplication at ingest time (~GBs per study, disk is
  cheap). After processing, the detection caches make videos optional for all
  replay/scoring, so completed studies' videos can be offloaded later; the
  detection-density backdrop (scripts/build_backdrop.py) keeps calibration
  usable even then.

**Scope.** v3 endpoints (`POST /videos`, `POST /videos/bulk`). The legacy v2
singular `/video` router is unchanged (migration-era code, not in the v3 flow).

All seven existing videos (5 corridor + 2 FM51) were moved into their
projects' `videos/` folders the same day, hash-verified against the recorded
content hashes.
