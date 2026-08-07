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

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from backend.database import get_connection                    # noqa: E402
from backend.services.apply_gate import adjudicate_apply       # noqa: E402
from backend.services.two_pass import gate_census_inputs       # noqa: E402

RUNS = Path("runs/v2_week1")

# (label, incumbent, candidate, binding) — incumbent/candidate DB stems;
# candidate variant carries the v2c_ prefix (base-census mapping exercised).
CORRIDOR_PAIRS = [
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

# FM51-CORD4699 (Wise County) — the HELD-OUT site: zero corridor
# knowledge, same frozen bundle, same gate constants. This is the
# out-of-sample test the apply-gate plan pre-committed to.
FM51_PAIRS = [
    ("cam2 ftv2n_am", "fm51ctrl_cam2_ftv2n_am", "twopass_cam2_v2c_ftv2n_am", True),
    ("cam2 ftv2n_pm", "fm51ctrl_cam2_ftv2n_pm", "twopass_cam2_v2c_ftv2n_pm", True),
]

SITES = {
    "97a7849a": {"pairs": CORRIDOR_PAIRS, "out": "apply_gate_validation.json"},
    "0acb12c0": {"pairs": FM51_PAIRS, "out": "apply_gate_validation_fm51.json"},
}


def scratch_dir(project: str) -> Path:
    return Path(f"data/projects/{project}/_replay_scratch/v2_week1")


def sidecar(project: str, name: str):
    d = json.loads((scratch_dir(project) / f"{name}.stats.json").read_text())
    r = d["result"]
    f_lo, f_hi = d["dump_meta"]["frames"]
    fps = (f_hi - f_lo) / r["window_seconds"]
    return r["camera_id"], r["variant"], f_lo, f_hi, fps


def chash_for(project: str, camera_id: int) -> str:
    conn = get_connection(project)
    try:
        return conn.execute(
            "SELECT content_hash FROM videos WHERE camera_id = ? "
            "ORDER BY sort_order LIMIT 1", (camera_id,)).fetchone()[0]
    finally:
        conn.close()


def pct(stem: str) -> float:
    return json.load(open(RUNS / f"{stem}.json"))["v2"]["pct"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a",
                    help="site id (default: the Sunnyvale corridor)")
    args = ap.parse_args()
    project = args.project
    site = SITES[project]
    S = scratch_dir(project)
    records, ok_binding, n_binding, ok_all = [], 0, 0, 0
    for label, inc, cand, binding in site["pairs"]:
        cam, cand_variant, f_lo, f_hi, fps = sidecar(project, cand)
        census, confusion = gate_census_inputs(
            project, cam, chash_for(project, cam), cand_variant, fps)
        verdict = adjudicate_apply(
            project, cam, cand_variant,
            incumbent_db=S / f"{inc}.db", candidate_db=S / f"{cand}.db",
            t_lo=f_lo / fps, t_hi=f_hi / fps,
            census=census, confusion=confusion, record=False)
        # ---- everything below is verdict CHECKING (Mio scores), not input
        inc_pct = pct(f"score_{inc}")
        cand_pct = pct(f"score_{cand}")
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
    n_pairs = len(site["pairs"])
    summary = {"project": project, "binding_correct": ok_binding,
               "binding_total": n_binding, "all_correct": ok_all,
               "all_total": n_pairs}
    print(f"\nGATE-AG1: {ok_binding}/{n_binding} binding "
          f"({ok_all}/{n_pairs} incl. dev)")
    RUNS.mkdir(parents=True, exist_ok=True)
    out = RUNS / site["out"]
    out.write_text(json.dumps({"summary": summary, "pairs": records}, indent=1))
    print(f"wrote {out}")
    return 0 if ok_binding == n_binding else 1


if __name__ == "__main__":
    raise SystemExit(main())
