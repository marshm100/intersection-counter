"""Apply-gate blind validation (plan_v2_apply_gate_2026-08-07, GATE-AG1).

Runs the SHIPPED adjudicator (backend.services.apply_gate.adjudicate_apply
through backend.services.two_pass.gate_census_inputs — the exact product
path, record=False) over the 12 on-disk validation pairs in
_replay_scratch/v2_week1. NO Miovision reaches the gate: the committed
score JSONs (runs/v2_week1/score_*.json, written by v2_score_dev.py in
prior sessions) are read only AFTERWARD to check each verdict against the
known better side. cam2 study_0700 is the dev window — reported, not
binding; the pre-declared bar is 11/11 on the blind windows.

Usage:
  py -X utf8 scripts/v2_apply_gate_validate.py
Writes runs/v2_week1/apply_gate_validation.json; exits 1 on any binding miss.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from backend.database import get_connection                    # noqa: E402
from backend.services.apply_gate import adjudicate_apply       # noqa: E402
from backend.services.two_pass import gate_census_inputs       # noqa: E402

PROJECT = "97a7849a"
S = Path("data/projects/97a7849a/_replay_scratch/v2_week1")
RUNS = Path("runs/v2_week1")

# (label, incumbent, candidate, binding) — incumbent/candidate DB stems;
# candidate variant carries the v2c_ prefix (base-census mapping exercised).
PAIRS = [
    ("cam1 study_0700", "ga3ctrl_cam1_study_0700", "twopass_cam1_v2c_study_0700", True),
    ("cam1 study_1600", "ga3ctrl_cam1_study_1600", "twopass_cam1_v2c_study_1600", True),
    ("cam2 study_0700", "twopass_cam2_study_0700", "twopass_cam2_v2c_study_0700", False),
    ("cam2 study_1100", "twopass_cam2_study_1100", "twopass_cam2_v2c_study_1100", True),
    ("cam2 study_1600", "twopass_cam2_study_1600", "twopass_cam2_v2c_study_1600", True),
    ("cam3 study_0600", "ga3ctrl_cam3_study_0600", "twopass_cam3_v2c_study_0600", True),
    ("cam4 study_0700", "ga3ctrl_cam4_study_0700", "twopass_cam4_v2c_study_0700", True),
    ("cam4 study_1100", "ga3ctrl_cam4_study_1100", "twopass_cam4_v2c_study_1100", True),
    ("cam4 study_1600", "ga3ctrl_cam4_study_1600", "twopass_cam4_v2c_study_1600", True),
    ("cam5 study_0700", "ga3ctrl_cam5_study_0700", "twopass_cam5_v2c_study_0700", True),
    ("cam5 study_1100", "ga3ctrl_cam5_study_1100", "twopass_cam5_v2c_study_1100", True),
    ("cam5 study_1600", "ga3ctrl_cam5_study_1600", "twopass_cam5_v2c_study_1600", True),
]

SCORE = {  # runs/v2_week1 score-JSON stems per side (verdict check ONLY)
    "ga3ctrl_cam1_study_0700": "score_ga3ctrl_cam1_study_0700",
    "ga3ctrl_cam1_study_1600": "score_ga3ctrl_cam1_study_1600",
    "ga3ctrl_cam3_study_0600": "score_ga3ctrl_cam3_study_0600",
    "ga3ctrl_cam4_study_0700": "score_ga3ctrl_cam4_study_0700",
    "ga3ctrl_cam4_study_1100": "score_ga3ctrl_cam4_study_1100",
    "ga3ctrl_cam4_study_1600": "score_ga3ctrl_cam4_study_1600",
    "ga3ctrl_cam5_study_0700": "score_ga3ctrl_cam5_study_0700",
    "ga3ctrl_cam5_study_1100": "score_ga3ctrl_cam5_study_1100",
    "ga3ctrl_cam5_study_1600": "score_ga3ctrl_cam5_study_1600",
}


def sidecar(name: str):
    d = json.loads((S / f"{name}.stats.json").read_text())
    r = d["result"]
    f_lo, f_hi = d["dump_meta"]["frames"]
    fps = (f_hi - f_lo) / r["window_seconds"]
    return r["camera_id"], r["variant"], f_lo, f_hi, fps


def chash_for(camera_id: int) -> str:
    conn = get_connection(PROJECT)
    try:
        return conn.execute(
            "SELECT content_hash FROM videos WHERE camera_id = ? "
            "ORDER BY sort_order LIMIT 1", (camera_id,)).fetchone()[0]
    finally:
        conn.close()


def pct(stem: str) -> float:
    return json.load(open(RUNS / f"{stem}.json"))["v2"]["pct"]


def main() -> int:
    records, ok_binding, n_binding, ok_all = [], 0, 0, 0
    for label, inc, cand, binding in PAIRS:
        cam, cand_variant, f_lo, f_hi, fps = sidecar(cand)
        census, confusion = gate_census_inputs(
            PROJECT, cam, chash_for(cam), cand_variant, fps)
        verdict = adjudicate_apply(
            PROJECT, cam, cand_variant,
            incumbent_db=S / f"{inc}.db", candidate_db=S / f"{cand}.db",
            t_lo=f_lo / fps, t_hi=f_hi / fps,
            census=census, confusion=confusion, record=False)
        # ---- everything below is verdict CHECKING (Mio scores), not input
        inc_pct = pct(SCORE.get(inc, f"score_{inc}"))
        cand_pct = pct(SCORE.get(cand, f"score_{cand}"))
        expected = "apply" if cand_pct > inc_pct else "stand_down"
        correct = verdict["decision"] == expected
        ok_all += correct
        if binding:
            n_binding += 1
            ok_binding += correct
        records.append({
            "window": label, "binding": binding,
            "decision": verdict["decision"], "reasons": verdict["reasons"],
            "metrics": verdict["metrics"],
            "score_incumbent": inc_pct, "score_candidate": cand_pct,
            "expected": expected, "correct": correct})
        print(f"{label:16} gate={verdict['decision']:10} "
              f"expected={expected:10} {'OK' if correct else 'MISS':4} "
              f"[{','.join(verdict['reasons'])}]  "
              f"(inc {inc_pct} vs cand {cand_pct}"
              f"{'' if binding else '; DEV — not binding'})")
    summary = {"binding_correct": ok_binding, "binding_total": n_binding,
               "all_correct": ok_all, "all_total": len(PAIRS)}
    print(f"\nGATE-AG1: {ok_binding}/{n_binding} binding "
          f"({ok_all}/{len(PAIRS)} incl. dev)")
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / "apply_gate_validation.json").write_text(
        json.dumps({"summary": summary, "pairs": records}, indent=1))
    print(f"wrote {RUNS / 'apply_gate_validation.json'}")
    return 0 if ok_binding == n_binding else 1


if __name__ == "__main__":
    raise SystemExit(main())
