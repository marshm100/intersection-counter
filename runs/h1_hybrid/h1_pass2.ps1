# Block H1 phase 2 — six pass-2 arms (h1base x3 + h1oc x3), default flags
# (activation ON — the d1ctrl basis). One workdir per arm; WAL-safe copies;
# twopass_ originals deleted; the h1base/h1oc ARM COPIES ARE KEPT (the
# merge consumes them in phase 4). docs/plan_h1_hybrid_2026-08-12.md.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\onkar\Documents\intersection-counter"

foreach ($v in @("V2_DEMOTION", "V2_MERGE_RESCUE", "EVIDENCE_ACTIVATION_ENABLED",
                 "CONSERVE_ON_ACTIVATION", "ORIGIN_POSTERIOR_ENABLED",
                 "V2_TIMELOCAL", "V2_GATE_AXIS", "ORIGIN_EVIDENCE_GATE_ENABLED",
                 "ORIGIN_CLAIM_VETO", "APPLY_GATE", "TWO_PASS_ENABLED",
                 "CHAIN_ARBITRATION_EVIDENCE")) {
    Remove-Item "Env:\$v" -ErrorAction SilentlyContinue
}

$scratch = "data\projects\97a7849a\_replay_scratch\h1_hybrid"
$copyPy = "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()"

$arms = @(
    @{v="study_0700";    tag="h1base"}, @{v="study_1100";    tag="h1base"},
    @{v="study_1600";    tag="h1base"},
    @{v="oc_study_0700"; tag="h1oc"},   @{v="oc_study_1100"; tag="h1oc"},
    @{v="oc_study_1600"; tag="h1oc"}
)
foreach ($x in $arms) {
    $v = $x.v; $tag = $x.tag
    $w = $v -replace "^oc_", ""
    $wd = "$scratch\${tag}_${w}"
    New-Item -ItemType Directory -Force $wd | Out-Null
    Write-Output "=== H1P2 $tag cam2 $v ==="
    Remove-Item -Force -ErrorAction SilentlyContinue `
        "$wd\twopass_cam2_${v}.db", "$wd\twopass_cam2_${v}.stats.json"
    py -X utf8 scripts/v2_run_pass2.py --camera 2 --variant $v --workdir $wd
    if ($LASTEXITCODE -ne 0) { Write-Output "H1P2_WINDOW_FAILED $tag $v"; continue }
    $src = "$wd\twopass_cam2_${v}.db"
    $dst = "$wd\${tag}_cam2_${w}.db"
    py -X utf8 -c $copyPy $src $dst
    if ($LASTEXITCODE -ne 0) { Write-Output "H1P2_COPY_FAILED $tag $v"; continue }
    py -X utf8 scripts/v2_score_dev.py $dst
    if ($LASTEXITCODE -ne 0) { Write-Output "H1P2_SCORE_FAILED $tag $v" }
    Remove-Item -Force -ErrorAction SilentlyContinue $src
}
Write-Output "H1P2_CHAIN_DONE"
