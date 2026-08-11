# Block-0 ARM C — the nine INTERACTING windows
# (docs/plan_v2_confound_split_2026-08-11).
#
# Same arm C environment as armC_clean.ps1, but at these windows demotion
# selected cells in arm B, so V2_DEMOTION is NOT inert. Named interaction:
# demotion's trigger includes `posterior_source is None` (pipeline.py:1426)
# and demotion is a SIBLING of the posterior block, not nested in it — so
# with the pair forced OFF fewer tracks carry a posterior source and
# demotion can reach FURTHER here than it did in arm B. Read these AFTER
# the clean windows and report the interaction rather than hiding it.
#
# cam2 is the diagnostic case, not a control: its activation state is the
# only one the confound never varied (already ON in both A and B).
#
# Ordered fastest-and-most-informative first; cam3 study_0600 (~31 min,
# 46388 tracks) runs LAST.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\onkar\Documents\intersection-counter"
$wd = "data\projects\97a7849a\_replay_scratch\v2_confound\armC2"
New-Item -ItemType Directory -Force $wd | Out-Null

$env:V2_DEMOTION = "1"
$env:V2_MERGE_RESCUE = "1"
$env:EVIDENCE_ACTIVATION_ENABLED = "0"

$wins = @(
    @{c=4; v="study_0700"},
    @{c=4; v="study_1600"},
    @{c=5; v="study_1100"},
    @{c=5; v="study_0700"},
    @{c=5; v="study_1600"},
    @{c=2; v="study_0700"},
    @{c=2; v="study_1100"},
    @{c=2; v="study_1600"},
    @{c=3; v="study_0600"}
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
Write-Output "ARMC_INTERACTING_DONE"
