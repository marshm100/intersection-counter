# Block H1 phase 1 — cam2 OC-SORT pass-1 dumps from the copied detection
# caches (docs/plan_h1_hybrid_2026-08-12.md). Fresh oc_study_* variants;
# never --resume-less on an existing variant (silent overwrite trap).
# OC-SORT never decodes frames: pure CPU from the cache.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\onkar\Documents\intersection-counter"

$runs = @(
    @{v="oc_study_0700"; hms="07:00:00"},
    @{v="oc_study_1100"; hms="11:00:00"},
    @{v="oc_study_1600"; hms="16:00:00"}
)
foreach ($r in $runs) {
    Write-Output "H1P1_START $($r.v)"
    py -X utf8 scripts/dump_raw_tracks.py --project 97a7849a --camera 2 `
        --variant $r.v --start-hms $r.hms --minutes 120 --backend ocsort
    if ($LASTEXITCODE -ne 0) { Write-Output "H1P1_FAILED $($r.v)" }
    else { Write-Output "H1P1_DONE $($r.v)" }
}
Write-Output "H1P1_CHAIN_DONE"
