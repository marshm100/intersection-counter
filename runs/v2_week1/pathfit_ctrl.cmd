@echo off
cd /d C:\Users\onkar\Documents\intersection-counter
echo CONTROL start %DATE% %TIME% >> runs\v2_week1\pathfit_ctrl.log
py -X utf8 scripts\v2_run_pass2.py --camera 2 --variant study_0700 >> runs\v2_week1\pathfit_ctrl.log 2>> runs\v2_week1\pathfit_ctrl.err
py -X utf8 scripts\v2_run_pass2.py --camera 2 --variant study_1100 >> runs\v2_week1\pathfit_ctrl.log 2>> runs\v2_week1\pathfit_ctrl.err
py -X utf8 scripts\v2_run_pass2.py --camera 2 --variant study_1600 >> runs\v2_week1\pathfit_ctrl.log 2>> runs\v2_week1\pathfit_ctrl.err
echo CONTROL_DONE >> runs\v2_week1\pathfit_ctrl.log
