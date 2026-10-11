#!/bin/bash
# arm dt2 on the deliverable (operator ruling 2026-10-11 "score dt2 on the deliverable"):
# (a) dt2 re-tracks of the 5 fleet windows that have none; (b) same-day control fleet dt2c on the
# production dumps; (c) dt2 fleet on the 12 dt2_ dumps; (d) dev journey labels dt2c vs dt2.
cd /c/dev/intersection-counter
PY=.venv/Scripts/python.exe; L=runs/v2_week1
rt() { TRACKER_TWIN_RETIRE=1 TRACKER_TWIN_RETIRE_WHICH=younger $PY -X utf8 scripts/arm_retrack_alias.py 97a7849a $1 $2 dt2 > $L/dt2_retrack_$1_$2.log 2>&1; echo "$(date +%T) retrack cam$1 $2 done"; }
rt 1 study_1600 & rt 4 study_0700 & rt 4 study_1100 & rt 5 study_0700 & rt 5 study_1100 &
FLEET_STEM=dt2c FLEET_WORKERS=4 FLEET_ARMS=1:study_0700,1:study_1600,2:study_0700,2:study_1100,2:study_1600,3:study_0600,4:study_0700,4:study_1100,4:study_1600,5:study_0700,5:study_1100,5:study_1600 \
  $PY -X utf8 scripts/fleet_flags.py > $L/fleet_dt2c.log 2>&1; echo "$(date +%T) control fleet done"
wait
FLEET_STEM=dt2 FLEET_WORKERS=6 FLEET_ARMS=1:dt2_study_0700,1:dt2_study_1600,2:dt2_study_0700,2:dt2_study_1100,2:dt2_study_1600,3:dt2_study_0600,4:dt2_study_0700,4:dt2_study_1100,4:dt2_study_1600,5:dt2_study_0700,5:dt2_study_1100,5:dt2_study_1600 \
  $PY -X utf8 scripts/fleet_flags.py > $L/fleet_dt2.log 2>&1; echo "$(date +%T) dt2 fleet done"
$PY -X utf8 scripts/eval_journeys.py dt2c dt2:1=dt2_,2=dt2_,3=dt2_,4=dt2_,5=dt2_ > $L/journeys_dt2_dev.log 2>&1
echo "$(date +%T) ALL"
