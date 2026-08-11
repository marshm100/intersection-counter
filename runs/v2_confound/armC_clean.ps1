# Block-0 ARM C — the v2c dump + V2 flags ON, but the evidence-gate
# ACTIVATION PRECONDITION FORCED OFF (docs/plan_v2_confound_split_2026-08-11).
#
# A (recorded, base dump + flags off)  -> C  = the effect of EXTENSION ROWS
# C                                    -> B  = the effect of the ACTIVATION FLIP
#
# These three windows are the CLEAN ones: demotion selected ZERO cells in
# arm B, so V2_DEMOTION/V2_MERGE_RESCUE are inert and the only live variable
# between C and B is the evidence pair.
#
# Arm C gets its OWN workdir: sidecar_reusable() keys on dump meta +
# calibration + schema and does NOT encode the env flags, so sharing a
# workdir with another arm would silently return that arm's result.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\onkar\Documents\intersection-counter"
$wd = "data\projects\97a7849a\_replay_scratch\v2_confound\armC"
New-Item -ItemType Directory -Force $wd | Out-Null

$env:V2_DEMOTION = "1"
$env:V2_MERGE_RESCUE = "1"
$env:EVIDENCE_ACTIVATION_ENABLED = "0"

$wins = @(
    @{c=1; v="study_0700"},
    @{c=1; v="study_1600"},
    @{c=4; v="study_1100"}
)
foreach ($w in $wins) {
    $c = $w.c; $v = $w.v
    Write-Output "=== ARMC cam$c v2c_$v ==="
    Remove-Item -Force -ErrorAction SilentlyContinue `
        "$wd\twopass_cam${c}_v2c_${v}.db", "$wd\twopass_cam${c}_v2c_${v}.stats.json"
    py -X utf8 scripts/v2_run_pass2.py --camera $c --variant "v2c_${v}" --workdir $wd
    Copy-Item -Force "$wd\twopass_cam${c}_v2c_${v}.db" "$wd\armC_cam${c}_v2c_${v}.db"
    py -X utf8 scripts/v2_score_dev.py "$wd\armC_cam${c}_v2c_${v}.db"
}
Write-Output "ARMC_CLEAN_DONE"
