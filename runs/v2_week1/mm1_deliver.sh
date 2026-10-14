#!/bin/bash
# arm mm1 (MOUTH_FROM_MOTION wired into pass 2, mo7 switches) vs same-day control mm1c, 12 windows,
# then dev journey labels car by car. 2026-10-14.
cd /c/dev/intersection-counter
PY=.venv/Scripts/python.exe; L=runs/v2_week1
W=1:study_0700,1:study_1600,2:study_0700,2:study_1100,2:study_1600,3:study_0600,4:study_0700,4:study_1100,4:study_1600,5:study_0700,5:study_1100,5:study_1600
FLEET_STEM=mm1c FLEET_WORKERS=4 FLEET_ARMS=$W $PY -X utf8 scripts/fleet_flags.py > $L/fleet_mm1c.log 2>&1
MOUTH_FROM_MOTION=1 FLEET_STEM=mm1 FLEET_WORKERS=4 FLEET_ARMS=$W $PY -X utf8 scripts/fleet_flags.py > $L/fleet_mm1.log 2>&1
# sequential: both fleets share the arm/ working dir (concurrent runs collided, 2026-10-14)
echo "$(date +%T) fleets done"
$PY -X utf8 scripts/eval_journeys.py mm1c mm1 > $L/journeys_mm1_dev.log 2>&1
echo "$(date +%T) ALL"
