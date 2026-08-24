# G-TR-1 arm chain (docs/plan_track_repair_2026-08-24.md, procedure step 1)
$ErrorActionPreference = "Continue"
Set-Location C:\dev\intersection-counter
$wd = "data\projects\97a7849a\_replay_scratch\trackrepair_20260824"
New-Item -ItemType Directory -Force $wd | Out-Null
$env:A3_CUT_DUMPS = "1"
foreach ($v in @("study_0700", "study_1100", "study_1600")) {
    Write-Output "=== GTR1 cam2 $v start $(Get-Date -Format o) ==="
    & .\.venv\Scripts\python.exe -X utf8 scripts/v2_run_pass2.py --camera 2 --variant $v --workdir $wd
    Write-Output "=== GTR1 cam2 $v exit $LASTEXITCODE $(Get-Date -Format o) ==="
}
Write-Output "GTR1_DONE $(Get-Date -Format o)"
