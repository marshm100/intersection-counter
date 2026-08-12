# Block H1 — supplementary flag-off OC arms for the two activation-flipped
# windows (docs/plan_h1_hybrid_2026-08-12.md activation guard). The oc dumps
# drop coverage below the 0.45 bar at study_1100/1600 (0.397/0.388 vs base
# 0.487/0.485), voiding the default-flag comparison there. Flag-off BASE
# controls already exist (e4ctrlx_cam2_study_{1100,1600}, run today, same
# env) — only the OC side is needed.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\onkar\Documents\intersection-counter"

foreach ($v in @("V2_DEMOTION", "V2_MERGE_RESCUE", "CONSERVE_ON_ACTIVATION",
                 "ORIGIN_POSTERIOR_ENABLED", "V2_TIMELOCAL", "V2_GATE_AXIS",
                 "ORIGIN_EVIDENCE_GATE_ENABLED", "ORIGIN_CLAIM_VETO",
                 "APPLY_GATE", "TWO_PASS_ENABLED", "CHAIN_ARBITRATION_EVIDENCE")) {
    Remove-Item "Env:\$v" -ErrorAction SilentlyContinue
}
$env:EVIDENCE_ACTIVATION_ENABLED = "0"

$scratch = "data\projects\97a7849a\_replay_scratch\h1_hybrid"
$copyPy = "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()"

foreach ($w in @("study_1100", "study_1600")) {
    $v = "oc_${w}"
    $wd = "$scratch\h1ocx_${w}"
    New-Item -ItemType Directory -Force $wd | Out-Null
    Write-Output "=== H1X h1ocx cam2 $v ==="
    Remove-Item -Force -ErrorAction SilentlyContinue `
        "$wd\twopass_cam2_${v}.db", "$wd\twopass_cam2_${v}.stats.json"
    py -X utf8 scripts/v2_run_pass2.py --camera 2 --variant $v --workdir $wd
    if ($LASTEXITCODE -ne 0) { Write-Output "H1X_WINDOW_FAILED $v"; continue }
    $src = "$wd\twopass_cam2_${v}.db"
    $dst = "$wd\h1ocx_cam2_${w}.db"
    py -X utf8 -c $copyPy $src $dst
    if ($LASTEXITCODE -ne 0) { Write-Output "H1X_COPY_FAILED $v"; continue }
    py -X utf8 scripts/v2_score_dev.py $dst
    if ($LASTEXITCODE -ne 0) { Write-Output "H1X_SCORE_FAILED $v" }
    Remove-Item -Force -ErrorAction SilentlyContinue $src
}
Write-Output "H1X_CHAIN_DONE"
