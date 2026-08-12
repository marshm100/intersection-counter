# Block C-1 — evidence-ranked chain arbitration measurement
# (docs/plan_v2_c1_arbitration_2026-08-12.md). ONE variable vs the D1 CONS
# arm: CHAIN_ARBITRATION_EVIDENCE=1 (CONSERVE_ON_ACTIVATION=1 in both).
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\onkar\Documents\intersection-counter"

foreach ($v in @("V2_DEMOTION", "V2_MERGE_RESCUE", "EVIDENCE_ACTIVATION_ENABLED",
                 "ORIGIN_POSTERIOR_ENABLED", "V2_TIMELOCAL", "V2_GATE_AXIS",
                 "ORIGIN_EVIDENCE_GATE_ENABLED", "ORIGIN_CLAIM_VETO",
                 "APPLY_GATE", "TWO_PASS_ENABLED")) {
    Remove-Item "Env:\$v" -ErrorAction SilentlyContinue
}
$env:CONSERVE_ON_ACTIVATION = "1"        # the D1 basis
$env:CHAIN_ARBITRATION_EVIDENCE = "1"    # the ONE new variable

$scratch = "data\projects\97a7849a\_replay_scratch\c1_arb"
$copyPy = "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()"

foreach ($w in @("study_0700", "study_1100", "study_1600")) {
    $wd = "$scratch\$w"
    New-Item -ItemType Directory -Force $wd | Out-Null
    Write-Output "=== C1 cam2 $w ==="
    Remove-Item -Force -ErrorAction SilentlyContinue `
        "$wd\twopass_cam2_${w}.db", "$wd\twopass_cam2_${w}.stats.json"
    py -X utf8 scripts/v2_run_pass2.py --camera 2 --variant $w --workdir $wd
    if ($LASTEXITCODE -ne 0) { Write-Output "C1_WINDOW_FAILED $w"; continue }
    $src = "$wd\twopass_cam2_${w}.db"
    $dst = "$wd\c1arb_cam2_${w}.db"
    py -X utf8 -c $copyPy $src $dst
    if ($LASTEXITCODE -ne 0) { Write-Output "C1_COPY_FAILED $w"; continue }
    py -X utf8 scripts/v2_score_dev.py $dst
    if ($LASTEXITCODE -ne 0) { Write-Output "C1_SCORE_FAILED $w" }
    Remove-Item -Force -ErrorAction SilentlyContinue $src, $dst
}
Write-Output "C1_CHAIN_DONE"
