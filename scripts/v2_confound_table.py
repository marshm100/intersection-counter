"""Block-0 decomposition table — split the G-A3 confound.

docs/plan_v2_confound_split_2026-08-11.md

    A -> C  = the effect of EXTENSION ROWS alone   (evidence pair OFF in both)
    C -> B  = the effect of the ACTIVATION FLIP alone (v2c dump in both)
    A -> B  = the recorded G-A3 delta                (their sum)

SCORING BASIS (this is the whole reason this script exists rather than a
grep). v2_score_dev writes two columns: "v2" = the scratch DB under test,
"production" = whatever the LIVE production table holds at scoring time.
The 2026-08-10 apply rewrote production for cam2 study_0700/1100 and cam3
study_0600, so the production column is NOT a stable control for those
windows — a v2c score file written after the apply reports the applied
table in that column, i.e. itself.

So arm A is read from the frozen replay-isolated ga3ctrl_* runs (base dump,
V2_DEMOTION=0, V2_MERGE_RESCUE=0) for cam1/3/4/5 — the same basis as arms
B and C. cam2 has NO ga3ctrl run (the G-A3 chain skipped it) and its scratch
"control" ran with demotion ON, so cam2 is reported on a DIFFERENT basis and
labelled as such. Do not compare a cam2 row to a cam1 row.
"""
from __future__ import annotations

import json
from pathlib import Path

SCORES = Path("runs/v2_week1")
SCRATCH = Path("data/projects/97a7849a/_replay_scratch")

CLEAN = {(1, "study_0700"), (1, "study_1600"), (4, "study_1100")}

WINDOWS = [
    (1, "study_0700"), (1, "study_1600"),
    (2, "study_0700"), (2, "study_1100"), (2, "study_1600"),
    (3, "study_0600"),
    (4, "study_0700"), (4, "study_1100"), (4, "study_1600"),
    (5, "study_0700"), (5, "study_1100"), (5, "study_1600"),
]


def _pct(path: Path, col: str = "v2") -> tuple[float | None, int | None, int | None]:
    """-> (pct, compliant, cells_scored).

    BOTH halves matter. rule595.score_cells scores the UNION of cells present
    in either source, so a candidate that produces counts in cells Miovision
    does not report EXPANDS its own denominator (a phantom cell must still
    fit +/-5 against a reference of 0). cam1 study_0700 arm A scored 81
    cell-bins and arm C scored 109 — arm C has MORE compliant cell-bins in
    absolute terms (59 vs 49) and a LOWER percentage. The percentage is the
    operator's bar and decides; the fraction says why it moved.
    """
    if not path.exists():
        return None, None, None
    d = json.loads(path.read_text(encoding="utf-8"))
    c = d.get(col) or {}
    return c.get("pct"), c.get("compliant"), c.get("cells_scored")


def arm_a(cam: int, var: str):
    """Base dump, V2 flags OFF, replay-isolated. -> (pct, compliant, scored)."""
    if cam == 2:
        # No ga3ctrl run exists. The v2a score files were written BEFORE the
        # 2026-08-10 apply, so their production column is a frozen snapshot
        # of pre-V2 production — a different basis, flagged in the output.
        return _pct(SCORES / f"score_twopass_cam2_v2a_{var}.json", "production")
    return _pct(SCORES / f"score_ga3ctrl_cam{cam}_{var}.json")


def arm_b(cam: int, var: str):
    return _pct(SCORES / f"score_twopass_cam{cam}_v2c_{var}.json")


def arm_c(cam: int, var: str):
    return _pct(SCORES / f"score_armC_cam{cam}_v2c_{var}.json")


def sidecar(cam: int, var: str, sub: str, stem: str) -> dict:
    p = SCRATCH / sub / f"{stem}.stats.json"
    if not p.exists():
        return {}
    return (json.loads(p.read_text(encoding="utf-8")).get("result") or {})


def main() -> int:
    print("Block-0 confound decomposition  (5/95 %-of-cell-bins vs Miovision)")
    print("  A = base dump, flags OFF, pair OFF     (recorded)")
    print("  C = v2c dump,  flags ON,  pair FORCED OFF (this block)")
    print("  B = v2c dump,  flags ON,  pair ON via activation flip (recorded)")
    print()
    hdr = (f"{'window':17s} {'A':>13s} {'C':>13s} {'B':>13s} "
           f"{'extend':>8s} {'ev-pair':>8s} {'tot A>B':>8s} "
           f"{'dcell':>5s} {'clean':>5s}")
    print(hdr)
    print("-" * len(hdr))
    pend = []
    for cam, var in WINDOWS:
        a, ka, na = arm_a(cam, var)
        b, kb, nb = arm_b(cam, var)
        c, kc, nc = arm_c(cam, var)
        sc = sidecar(cam, var, "v2_week1", f"twopass_cam{cam}_v2c_{var}")
        cells = (sc.get("demotion") or {}).get("cells")
        ncell = "-" if cells is None else str(len(cells))
        clean = "yes" if (cam, var) in CLEAN else ""
        if c is None:
            pend.append(f"cam{cam} {var}")

        def f(p, k, n):
            if p is None:
                return f"{'--':>13s}"
            return f"{p:5.1f} {k:>3d}/{n:<3d}"

        def d(x, y):
            return "      --" if (x is None or y is None) else f"{y - x:+8.1f}"

        # BASIS-AWARE DECOMPOSITION. The evidence pair's state in arm A
        # differs by camera, so the same two columns mean different things:
        #   cam1/3/4/5  A pair OFF (below the 0.45 bar), C OFF, B ON
        #               -> extension = C-A,  pair = B-C
        #   cam2        A pair ON already (coverage .485-.564), C OFF, B ON
        #               -> extension = B-A,  pair = B-C
        # Reading cam2's C-A as "extension" would silently mix an added
        # mechanism with a REMOVED one and invert the sign of the answer.
        if cam == 2:
            ext, pair = d(a, b), d(c, b)
        else:
            ext, pair = d(a, c), d(c, b)
        star = "*" if cam == 2 else ""
        label = f"cam{cam} {var}{star}"
        print(f"{label:17s} {f(a, ka, na)} {f(c, kc, nc)} {f(b, kb, nb)} "
              f"{ext} {pair} {d(a, b)} {ncell:>5s} {clean:>5s}")
    print()
    print("Each cell: 5/95 %  compliant/scored. The scored count is NOT fixed —")
    print("score_cells scores the UNION of cells in either source, so a candidate")
    print("that counts where Miovision reports nothing enlarges its own denominator.")
    print("* cam2 arm A is a live-legacy pre-apply snapshot, NOT a")
    print("  replay-isolated run — a DIFFERENT BASIS. cam2's activation state")
    print("  is also the one the confound never varied (already ON in A and B),")
    print("  so its arm C is diagnostic only, never a control for this block.")
    if pend:
        print()
        print(f"PENDING arm C ({len(pend)}): " + ", ".join(pend))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
