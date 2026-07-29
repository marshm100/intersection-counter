"""Stage 3.1 GATE — the star rating vs the six known sites
(plan_stage3_star_rating_2026-07-29, amended gate table).

Rates every corpus camera through the REAL service (production basis:
pass-1 dumps + operator gates + production vehicle_events) and checks
the pre-declared classes:

    cam4 3* and cam5 3* (same-cell echo over the frozen threshold);
    cam1, cam2, cam3, FM51 4*; everyone capped <=4* by resolution.

If a site's event join is invalid on the production table (legacy-era
events that never came from the on-disk dumps), the row reports tier B
honestly AND a supplementary classification from its phase-0 replay
census (basis named) — never a silent pass.
Evidence -> runs/stage3_star/rating_gate.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.footage_rating import classify_metrics, rate_camera

OUT = Path("runs/stage3_star/rating_gate.json")

SITES = [
    ("97a7849a", 1, "cam1", 4),
    ("97a7849a", 2, "cam2", 4),
    ("97a7849a", 3, "cam3", 4),
    ("97a7849a", 4, "cam4", 3),
    ("97a7849a", 5, "cam5", 3),
    ("0acb12c0", 2, "fm51", 4),
]

# phase-0 replay-basis censuses (runs/cam5_wall/chain_census*.json) for
# the supplementary row when a legacy production table cannot join
PHASE0 = {
    "cam1": "runs/cam5_wall/chain_census_97a7_c1.json",
    "cam2": "runs/cam5_wall/chain_census_97a7_c2.json",
    "cam3": "runs/cam5_wall/chain_census_97a7_c3.json",
    "cam4": "runs/cam5_wall/chain_census_97a7_c4.json",
    "cam5": "runs/cam5_wall/chain_census_97a7_c5.json",
    "fm51": "runs/cam5_wall/chain_census_fm51.json",
}


def phase0_echo(name: str) -> dict | None:
    """same-cell / flip excess shares from a phase-0 census JSON
    (top-8 cellpair table; single-cell keys = same-cell echo)."""
    p = Path(PHASE0[name])
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    same = flip = ev = 0
    for w in d.values():
        ev += w.get("n_events", 0)
        for key, n in w.get("excess_by_cellpair_top", {}).items():
            cells = key.split("+")
            if len(cells) == 1:
                same += n
            elif len(cells) == 2:
                a, b = cells
                if a.split(">")[::-1] == b.split(">"):
                    flip += n
    if not ev:
        return None
    return {"echo_share": round(same / ev, 4),
            "flip_share": round(flip / ev, 4), "n_events": ev}


def main() -> int:
    result = {}
    ok = True
    for pid, cid, name, want in SITES:
        t0 = time.time()
        r = rate_camera(pid, cid)
        cens = r["metrics"]["census"] or {}
        row = {
            "stars": r["stars"], "want": want, "tier": r["tier"],
            "label": r["label"],
            "echo_share": cens.get("echo_share"),
            "flip_share": cens.get("flip_share"),
            "entry_coverage": cens.get("entry_coverage"),
            "multi_chain_share": cens.get("multi_chain_share"),
            "event_join_unmapped_share": cens.get("event_join_unmapped_share"),
            "variants": cens.get("variants"),
            "night_share": (r["metrics"]["video"] or {}).get("night_share"),
            "reasons": r["reasons"], "seconds": round(time.time() - t0, 1),
        }
        if r["tier"] != "C":
            p0 = phase0_echo(name)
            if p0:
                row["phase0_replay_basis"] = p0
                sup = dict(cens or {})
                sup.update(event_join_valid=True, **{
                    k: p0[k] for k in ("echo_share", "flip_share")})
                sup.setdefault("entry_coverage", None)
                sup.setdefault("multi_chain_share", None)
                v = r["metrics"]["video"]
                row["phase0_stars"] = classify_metrics(v, sup)["stars"]
        got = row["stars"] if row["tier"] == "C" else row.get("phase0_stars")
        row["effective_stars"] = got
        row["pass"] = (got == want)
        ok = ok and row["pass"]
        result[name] = row
        print(f"[GATE] {name}: stars={row['stars']} tier={row['tier']} "
              f"(effective {got}, want {want}) echo={row['echo_share']} "
              f"flip={row['flip_share']} unmapped="
              f"{row['event_join_unmapped_share']} "
              f"{'PASS' if row['pass'] else 'FAIL'} "
              f"[{row['seconds']}s]", flush=True)
    result["_verdict"] = {"pass": ok}
    print(f"[GATE] VERDICT: {'PASS' if ok else 'FAIL'}", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("RATING GATE DONE", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
