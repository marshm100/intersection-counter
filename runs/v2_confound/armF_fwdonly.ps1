# ARM F — FORWARD-ONLY extension.
# docs/plan_v2_confound_split_2026-08-11.md, successor to the LEDGERED
# --skip-full arm.
#
# A BACKWARD walk changes a track's FIRST gate crossing (its ORIGIN);
# a FORWARD walk changes its LAST (its DESTINATION). Measured at cam1
# study_1600, the reclassification flows split ~116 origin-changes vs ~69
# dest-changes, so forward-only removes the larger share BY CONSTRUCTION
# rather than by threshold — which is why it is a better-shaped rule than
# --skip-full, whose tag gate never applied to the damaged population.
#
# Known and bounded cost: the day-5 addendum measured forward-only keeping
# most of the NB-left recall gain (348 -> 380 of 413 vs both-directions),
# so this trades a slice of recall for the origin-manufacture class.
#
# Same three zero-demotion windows and arm C's exact environment, so
# F vs C vs E are directly comparable.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\onkar\Documents\intersection-counter"
$wd = "data\projects\97a7849a\_replay_scratch\v2_confound\armF"
New-Item -ItemType Directory -Force $wd | Out-Null

$wins = @(
    @{c=1; v="study_0700"},
    @{c=1; v="study_1600"},
    @{c=4; v="study_1100"}
)

foreach ($w in $wins) {
    Write-Output "=== BUILD v2f cam$($w.c) $($w.v) ==="
    py -X utf8 scripts/v2_extend_dump.py --camera $w.c --variant $w.v `
        --cache $w.v --directions fwd --out-prefix v2f_
}

$env:V2_DEMOTION = "1"
$env:V2_MERGE_RESCUE = "1"
$env:EVIDENCE_ACTIVATION_ENABLED = "0"
foreach ($w in $wins) {
    $c = $w.c; $v = $w.v
    Write-Output "=== ARMF cam$c v2f_$v ==="
    Remove-Item -Force -ErrorAction SilentlyContinue `
        "$wd\twopass_cam${c}_v2f_${v}.db", "$wd\twopass_cam${c}_v2f_${v}.stats.json"
    py -X utf8 scripts/v2_run_pass2.py --camera $c --variant "v2f_${v}" --workdir $wd
    Copy-Item -Force "$wd\twopass_cam${c}_v2f_${v}.db" "$wd\armF_cam${c}_v2f_${v}.db"
    py -X utf8 scripts/v2_score_dev.py "$wd\armF_cam${c}_v2f_${v}.db"
}
Write-Output "ARMF_DONE"
