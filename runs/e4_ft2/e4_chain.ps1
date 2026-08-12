# Block E4 — ft2 re-test chain (docs/plan_v2_e4_ft2_2026-08-12.md)
# armC pattern: one workdir per arm; env vars REMOVED to guarantee defaults;
# WAL-safe copies via sqlite3 backup; distinct e4ft2 stems; DBs deleted
# after scoring (score JSON + .stats.json are the evidence).
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\onkar\Documents\intersection-counter"

foreach ($v in @("V2_DEMOTION", "V2_MERGE_RESCUE", "EVIDENCE_ACTIVATION_ENABLED",
                 "CONSERVE_ON_ACTIVATION", "ORIGIN_POSTERIOR_ENABLED",
                 "V2_TIMELOCAL", "V2_GATE_AXIS", "ORIGIN_EVIDENCE_GATE_ENABLED",
                 "ORIGIN_CLAIM_VETO", "APPLY_GATE", "TWO_PASS_ENABLED")) {
    Remove-Item "Env:\$v" -ErrorAction SilentlyContinue
}

$scratch = "data\projects\97a7849a\_replay_scratch\e4_ft2"
$copyPy = "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()"

$wins = @(
    @{c=2; w="study_0700"}, @{c=2; w="study_1100"}, @{c=2; w="study_1600"},
    @{c=4; w="study_0700"}, @{c=4; w="study_1100"}, @{c=4; w="study_1600"},
    @{c=5; w="study_0700"}, @{c=5; w="study_1100"}, @{c=5; w="study_1600"},
    @{c=1; w="study_0700"}
)
foreach ($x in $wins) {
    $c = $x.c; $w = $x.w
    $wd = "$scratch\cam${c}_${w}"
    New-Item -ItemType Directory -Force $wd | Out-Null
    Write-Output "=== E4 cam$c ft2_$w ==="
    Remove-Item -Force -ErrorAction SilentlyContinue `
        "$wd\twopass_cam${c}_ft2_${w}.db", "$wd\twopass_cam${c}_ft2_${w}.stats.json"
    py -X utf8 scripts/v2_run_pass2.py --camera $c --variant "ft2_${w}" --workdir $wd
    if ($LASTEXITCODE -ne 0) { Write-Output "E4_WINDOW_FAILED cam$c ft2_$w"; continue }
    $src = "$wd\twopass_cam${c}_ft2_${w}.db"
    $dst = "$wd\e4ft2_cam${c}_${w}.db"
    py -X utf8 -c $copyPy $src $dst
    if ($LASTEXITCODE -ne 0) { Write-Output "E4_COPY_FAILED cam$c ft2_$w"; continue }
    py -X utf8 scripts/v2_score_dev.py $dst
    if ($LASTEXITCODE -ne 0) { Write-Output "E4_SCORE_FAILED cam$c ft2_$w" }
    Remove-Item -Force -ErrorAction SilentlyContinue $src, $dst
}
Write-Output "E4_CHAIN_DONE"
