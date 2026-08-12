# Block E4 — supplementary flag-off pairs for cam2 (pre-registered activation
# contingency, docs/plan_v2_e4_ft2_2026-08-12.md). ft2 dropped cam2 coverage
# below the 0.45 bar at all three windows (0.564->0.385, 0.487->0.320,
# 0.485->0.329), flipping the pair OFF in the arm while ON in the control.
# These pairs hold EVIDENCE_ACTIVATION_ENABLED=0 on BOTH sides so the only
# variable is the detection basis.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\onkar\Documents\intersection-counter"

foreach ($v in @("V2_DEMOTION", "V2_MERGE_RESCUE", "CONSERVE_ON_ACTIVATION",
                 "ORIGIN_POSTERIOR_ENABLED", "V2_TIMELOCAL", "V2_GATE_AXIS",
                 "ORIGIN_EVIDENCE_GATE_ENABLED", "ORIGIN_CLAIM_VETO",
                 "APPLY_GATE", "TWO_PASS_ENABLED")) {
    Remove-Item "Env:\$v" -ErrorAction SilentlyContinue
}
$env:EVIDENCE_ACTIVATION_ENABLED = "0"   # the ONE deliberate non-default

$scratch = "data\projects\97a7849a\_replay_scratch\e4_ft2"
$copyPy = "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()"

$arms = @(
    @{v="study_0700";     tag="e4ctrlx"}, @{v="ft2_study_0700"; tag="e4ft2x"},
    @{v="study_1100";     tag="e4ctrlx"}, @{v="ft2_study_1100"; tag="e4ft2x"},
    @{v="study_1600";     tag="e4ctrlx"}, @{v="ft2_study_1600"; tag="e4ft2x"}
)
foreach ($x in $arms) {
    $v = $x.v; $tag = $x.tag
    $w = $v -replace "^ft2_", ""
    $wd = "$scratch\x_${tag}_${w}"
    New-Item -ItemType Directory -Force $wd | Out-Null
    Write-Output "=== E4X $tag cam2 $v ==="
    Remove-Item -Force -ErrorAction SilentlyContinue `
        "$wd\twopass_cam2_${v}.db", "$wd\twopass_cam2_${v}.stats.json"
    py -X utf8 scripts/v2_run_pass2.py --camera 2 --variant $v --workdir $wd
    if ($LASTEXITCODE -ne 0) { Write-Output "E4X_WINDOW_FAILED $tag $v"; continue }
    $src = "$wd\twopass_cam2_${v}.db"
    $dst = "$wd\${tag}_cam2_${w}.db"
    py -X utf8 -c $copyPy $src $dst
    if ($LASTEXITCODE -ne 0) { Write-Output "E4X_COPY_FAILED $tag $v"; continue }
    py -X utf8 scripts/v2_score_dev.py $dst
    if ($LASTEXITCODE -ne 0) { Write-Output "E4X_SCORE_FAILED $tag $v" }
    Remove-Item -Force -ErrorAction SilentlyContinue $src, $dst
}
Write-Output "E4X_CHAIN_DONE"
