# FM51 held-out chain (apply-gate block, out-of-sample test) — the G-A3
# recipe verbatim on the HELD-OUT site: project 0acb12c0, camera 2
# (FM51-CORD4699), its two study windows. Control (base dump, flags OFF)
# then treatment (v2c extended dump, bundle flags ON) per window; controls
# copied aside as fm51ctrl_cam2_{V}.db. Scratch only (apply=False) —
# production tables untouched, per the block's scope guard.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\onkar\Documents\intersection-counter"
$proj = "0acb12c0"
$scratch = "data\projects\$proj\_replay_scratch\v2_week1"
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
$c = 2
foreach ($v in @("ftv2n_am", "ftv2n_pm")) {
    Write-Output "=== FM51 cam$c $v ==="
    # control: base dump, flags off
    Remove-Item -Force -ErrorAction SilentlyContinue "$scratch\twopass_cam${c}_${v}.db", "$scratch\twopass_cam${c}_${v}.stats.json"
    $env:V2_DEMOTION = "0"; $env:V2_MERGE_RESCUE = "0"
    py -X utf8 scripts/v2_run_pass2.py --project $proj --camera $c --variant $v
    Copy-Item -Force "$scratch\twopass_cam${c}_${v}.db" "$scratch\fm51ctrl_cam${c}_${v}.db"
    Copy-Item -Force "$scratch\twopass_cam${c}_${v}.stats.json" "$scratch\fm51ctrl_cam${c}_${v}.stats.json"
    # extension build (same constants ledger, zero per-site edits)
    py -X utf8 scripts/v2_extend_dump.py --project $proj --camera $c --variant $v --cache $v --directions both
    # treatment: v2c dump, bundle flags on
    Remove-Item -Force -ErrorAction SilentlyContinue "$scratch\twopass_cam${c}_v2c_${v}.db", "$scratch\twopass_cam${c}_v2c_${v}.stats.json"
    $env:V2_DEMOTION = "1"; $env:V2_MERGE_RESCUE = "1"
    py -X utf8 scripts/v2_run_pass2.py --project $proj --camera $c --variant "v2c_${v}"
}
Write-Output "FM51_CHAIN_DONE"
