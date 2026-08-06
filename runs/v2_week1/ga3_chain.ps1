# G-A3 corridor blind transfer chain (block-2 item 5) — sequential,
# control (base dump, flags OFF) then treatment (v2c dump, flags ON)
# per window. Controls copied aside as ga3ctrl_cam{C}_{V}.db.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\onkar\Documents\intersection-counter"
$scratch = "data\projects\97a7849a\_replay_scratch\v2_week1"
$wins = @(
    @{c=1; v="study_0700"}, @{c=1; v="study_1600"},
    @{c=4; v="study_0700"}, @{c=4; v="study_1100"}, @{c=4; v="study_1600"},
    @{c=5; v="study_0700"}, @{c=5; v="study_1100"}, @{c=5; v="study_1600"},
    @{c=3; v="study_0600"}
)
foreach ($w in $wins) {
    $c = $w.c; $v = $w.v
    Write-Output "=== GA3 cam$c $v ==="
    # control: base dump, flags off
    Remove-Item -Force -ErrorAction SilentlyContinue "$scratch\twopass_cam${c}_${v}.db", "$scratch\twopass_cam${c}_${v}.stats.json"
    $env:V2_DEMOTION = "0"; $env:V2_MERGE_RESCUE = "0"
    py -X utf8 scripts/v2_run_pass2.py --camera $c --variant $v
    Copy-Item -Force "$scratch\twopass_cam${c}_${v}.db" "$scratch\ga3ctrl_cam${c}_${v}.db"
    Copy-Item -Force "$scratch\twopass_cam${c}_${v}.stats.json" "$scratch\ga3ctrl_cam${c}_${v}.stats.json"
    # extension build
    py -X utf8 scripts/v2_extend_dump.py --camera $c --variant $v --cache $v --directions both
    # treatment: v2c dump, flags on
    Remove-Item -Force -ErrorAction SilentlyContinue "$scratch\twopass_cam${c}_v2c_${v}.db", "$scratch\twopass_cam${c}_v2c_${v}.stats.json"
    $env:V2_DEMOTION = "1"; $env:V2_MERGE_RESCUE = "1"
    py -X utf8 scripts/v2_run_pass2.py --camera $c --variant "v2c_${v}"
}
Write-Output "GA3_CHAIN_DONE"
