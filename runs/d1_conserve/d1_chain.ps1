# Block D1 — the posterior EXTRAS (census_expecteds + conserve_pass) under
# the ACTIVATION precondition.
#
# BASIS: BASE dumps, all V2 mechanism flags OFF. That is the shipped
# configuration — the extension line is closed, so measuring D1 on v2c dumps
# would price it against a mechanism we retired. cam2 is the whole surface:
# on base dumps it is the only camera whose blind coverage clears 0.45
# (0.485-0.564), which is exactly the camera where the posterior half was
# proven (9.1 -> 3.3-3.5%).
#
# The ONLY variable between arms is CONSERVE_ON_ACTIVATION. Note the extras
# can only bite where the evidence pair is ON: conserve_replay_additions
# rejects only posterior-sourced events (_ADDITIVE), so on an all-direct
# replay it is a strict no-op by design. Activation is what turns the pair
# on at cam2, which is why this is the right surface and not a limitation.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\onkar\Documents\intersection-counter"
$base = "data\projects\97a7849a\_replay_scratch\d1_conserve"
New-Item -ItemType Directory -Force "$base\ctrl" | Out-Null
New-Item -ItemType Directory -Force "$base\treat" | Out-Null

$env:V2_DEMOTION = "0"
$env:V2_MERGE_RESCUE = "0"
Remove-Item Env:\EVIDENCE_ACTIVATION_ENABLED -ErrorAction SilentlyContinue

$wins = @("study_0700", "study_1100", "study_1600")

# --- arm CTRL: today's shipped behaviour (extras never run) ---------------
$env:CONSERVE_ON_ACTIVATION = "0"
foreach ($v in $wins) {
    Write-Output "=== D1CTRL cam2 $v ==="
    Remove-Item -Force -ErrorAction SilentlyContinue `
        "$base\ctrl\twopass_cam2_${v}.db", "$base\ctrl\twopass_cam2_${v}.stats.json"
    py -X utf8 scripts/v2_run_pass2.py --camera 2 --variant $v --workdir "$base\ctrl"
    Copy-Item -Force "$base\ctrl\twopass_cam2_${v}.db" "$base\ctrl\d1ctrl_cam2_${v}.db"
    py -X utf8 scripts/v2_score_dev.py "$base\ctrl\d1ctrl_cam2_${v}.db"
}

# --- arm CONS: extras follow the activation decision ----------------------
$env:CONSERVE_ON_ACTIVATION = "1"
foreach ($v in $wins) {
    Write-Output "=== D1CONS cam2 $v ==="
    Remove-Item -Force -ErrorAction SilentlyContinue `
        "$base\treat\twopass_cam2_${v}.db", "$base\treat\twopass_cam2_${v}.stats.json"
    py -X utf8 scripts/v2_run_pass2.py --camera 2 --variant $v --workdir "$base\treat"
    Copy-Item -Force "$base\treat\twopass_cam2_${v}.db" "$base\treat\d1cons_cam2_${v}.db"
    py -X utf8 scripts/v2_score_dev.py "$base\treat\d1cons_cam2_${v}.db"
}
Write-Output "D1_CHAIN_DONE"
