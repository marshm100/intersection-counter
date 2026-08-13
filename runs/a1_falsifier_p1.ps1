Set-Location "C:\Users\onkar\Documents\intersection-counter"
Write-Output "A1F_START pass1"
py -X utf8 scripts/dump_raw_tracks.py --project 97a7849a --camera 2 --variant a1_study_0700 --start-hms 07:00:00 --minutes 120
if ($LASTEXITCODE -ne 0) { Write-Output "A1F_PASS1_FAILED" } else { Write-Output "A1F_PASS1_DONE" }
