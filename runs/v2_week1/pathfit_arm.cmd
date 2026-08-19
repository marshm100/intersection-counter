@echo off
cd /d C:\Users\onkar\Documents\intersection-counter
echo ARM start %DATE% %TIME% >> runs\v2_week1\pathfit_arm.log
py -X utf8 scripts\v2_run_pass2.py --camera 2 --variant study_0700 >> runs\v2_week1\pathfit_arm.log 2>> runs\v2_week1\pathfit_arm.err
py -X utf8 scripts\v2_run_pass2.py --camera 2 --variant study_1100 >> runs\v2_week1\pathfit_arm.log 2>> runs\v2_week1\pathfit_arm.err
py -X utf8 scripts\v2_run_pass2.py --camera 2 --variant study_1600 >> runs\v2_week1\pathfit_arm.log 2>> runs\v2_week1\pathfit_arm.err
echo ARM_DONE >> runs\v2_week1\pathfit_arm.log
