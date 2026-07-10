"""cam2 full-day pass-1 dumps (the two-pass exercise, plan_A4_stage3 stage 4).

Three study windows, BoT-SORT (cam2's live-recipe family per
calib_pass1_backend), sequential. Detach this from any session harness
(Start-Process) — each window is ~1h+ of tracking at 25 fps; --resume makes a
kill cheap to recover. Run from the repo root."""
import subprocess
import sys

WINDOWS = [("study_0700", "07:00:00"), ("study_1100", "11:00:00"),
           ("study_1600", "16:00:00")]

for variant, hms in WINDOWS:
    print(f"=== cam2 {variant} ({hms}, botsort) ===", flush=True)
    r = subprocess.run([sys.executable, "-u", "scripts/dump_raw_tracks.py",
                        "--camera", "2", "--variant", variant,
                        "--start-hms", hms, "--minutes", "120",
                        "--backend", "botsort", "--resume"])
    if r.returncode != 0:
        print(f"!! {variant} failed ({r.returncode})", flush=True)
        sys.exit(r.returncode)
print("ALL_DONE", flush=True)
