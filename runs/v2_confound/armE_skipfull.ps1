# ARM E — extension GATED to non-full tracks (the confound-split fix).
# docs/plan_v2_confound_split_2026-08-11.md, "RESOLVED — it is
# MISATTRIBUTION, not duplication".
#
# Rule under test: extension may not alter the gate-crossing set of a track
# already tag `full` in the BASE dump. Same tag gate track_chains uses
# ("a full journey never chains").
#
# Arm E uses ARM C's EXACT environment (V2_DEMOTION=1, V2_MERGE_RESCUE=1,
# EVIDENCE_ACTIVATION_ENABLED=0) so E vs C isolates --skip-full and nothing
# else.
#
# SCOPE — three windows only, and the reason is a real constraint, not a
# preference: with V2_DEMOTION=1 the demotion census strips the variant
# prefix to find the BASE dump (two_pass.py:1046), and that tuple does not
# yet contain "v2e_". At these three windows demotion selected ZERO cells in
# arm B, so the census is never consulted and the omission cannot bite.
# cam5 study_1600 — the one window where extension is POSITIVE (+1.7) and
# the most interesting test of the rule — selects 3 demotion cells, so it
# needs "v2e_" added to that tuple first. Deferred to Block 1, where that
# helper (base_variant) is planned WITH characterization tests.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\onkar\Documents\intersection-counter"
$wd = "data\projects\97a7849a\_replay_scratch\v2_confound\armE"
New-Item -ItemType Directory -Force $wd | Out-Null

$wins = @(
    @{c=1; v="study_0700"},
    @{c=1; v="study_1600"},
    @{c=4; v="study_1100"}
)

# 1. build the gated dumps (v2e_), default path untouched
foreach ($w in $wins) {
    Write-Output "=== BUILD v2e cam$($w.c) $($w.v) ==="
    py -X utf8 scripts/v2_extend_dump.py --camera $w.c --variant $w.v `
        --cache $w.v --directions both --skip-full
}

# 2. pass 2 under ARM C's environment
$env:V2_DEMOTION = "1"
$env:V2_MERGE_RESCUE = "1"
$env:EVIDENCE_ACTIVATION_ENABLED = "0"
foreach ($w in $wins) {
    $c = $w.c; $v = $w.v
    Write-Output "=== ARME cam$c v2e_$v ==="
    Remove-Item -Force -ErrorAction SilentlyContinue `
        "$wd\twopass_cam${c}_v2e_${v}.db", "$wd\twopass_cam${c}_v2e_${v}.stats.json"
    py -X utf8 scripts/v2_run_pass2.py --camera $c --variant "v2e_${v}" --workdir $wd
    Copy-Item -Force "$wd\twopass_cam${c}_v2e_${v}.db" "$wd\armE_cam${c}_v2e_${v}.db"
    py -X utf8 scripts/v2_score_dev.py "$wd\armE_cam${c}_v2e_${v}.db"
}
Write-Output "ARME_DONE"
