"""TRAIN THE FAILURE PREDICTOR (2026-10-15; plan proud-wiggling-swan step 2). On the C instances (counted
journeys) of the DEV clips only; the held-out clips (_m50, FM 51) are scored once, at the end, by --final.
p(error) where error = WRONG / DOUBLE / PHANTOM. Candidates: (i) logistic regression on standardised features,
(ii) a small gradient-boosted model - (ii) kept only if it beats (i) on every leave-one-camera-out fold.
Reported per fold: precision at the review budget (REVIEW_BUDGET_MIN_PER_H at REVIEW_S per instance, scaled to the
clip's length), recall of the clip's errors at that budget, average precision, calibration by decile.
Writes data/models/failure_v1.json (the logistic model as plain numbers: no pickle) + failure_v1_report.json.
Usage: .venv/Scripts/python.exe -X utf8 scripts/train_failure_model.py [STEM] [--final]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

BUDGET_MIN_PER_H = 15
REVIEW_S = 10
CLIP_S = 180
SEED = 0
META = {"type", "truth", "project", "clip", "part", "cam", "tid", "event_id"}


def per_clip_budget() -> int:
    return int(round(BUDGET_MIN_PER_H * 60 / REVIEW_S * CLIP_S / 3600))


def at_budget(df, p):
    """Pull the top-k per clip by p; precision of the pulls and recall of the clips' errors."""
    k = per_clip_budget()
    hit = pulled = errs = 0
    for _, g in df.assign(p=p).groupby(["project", "clip"]):
        top = g.sort_values("p", ascending=False).head(k)
        hit += int(top["y"].sum())
        pulled += len(top)
        errs += int(g["y"].sum())
    return hit, pulled, errs


def calib(y, p, bins=10):
    q = np.quantile(p, np.linspace(0, 1, bins + 1))
    out = []
    for i in range(bins):
        m = (p >= q[i]) & (p <= q[i + 1]) if i == bins - 1 else (p >= q[i]) & (p < q[i + 1])
        if m.sum():
            out.append((int(m.sum()), float(p[m].mean()), float(y[m].mean())))
    return out


def models():
    return {"logistic": lambda: LogisticRegression(C=1.0, max_iter=2000),
            "boosted": lambda: HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05,
                                                              random_state=SEED)}


def fit_predict(name, Xtr, ytr, Xte):
    if name == "logistic":
        mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
        m = models()[name]().fit((Xtr - mu) / sd, ytr)
        return m.predict_proba((Xte - mu) / sd)[:, 1], (m, mu, sd)
    m = models()[name]().fit(Xtr, ytr)
    return m.predict_proba(Xte)[:, 1], (m, None, None)


def main() -> int:
    stem = next((a for a in sys.argv[1:] if not a.startswith("--")), "mm1")
    final = "--final" in sys.argv
    df = pd.read_parquet(f"runs/v2_week1/failure_dataset_{stem}.parquet")
    df = df[df["type"] == "C"].copy()
    df["y"] = (df["truth"] != "OK").astype(int)
    feats = [c for c in df.columns if c not in META | {"y"} and df[c].notna().any()]
    df[feats] = df[feats].fillna(0.0)
    dev = df[df["part"] == "dev"]
    print(f"DEV: {len(dev)} counted journeys, {dev['y'].sum()} errors ({100 * dev['y'].mean():.1f}%); "
          f"{len(feats)} features; budget {per_clip_budget()} pulls per 3-min clip "
          f"({BUDGET_MIN_PER_H} min/h at {REVIEW_S} s)")
    report = {"features": feats, "folds": {}}
    summary = {}
    for name in models():
        oof = np.zeros(len(dev))
        print(f"\n== {name} (leave one camera out) ==")
        for cam in sorted(dev["cam"].unique()):
            tr, te = dev["cam"] != cam, dev["cam"] == cam
            p, _ = fit_predict(name, dev.loc[tr, feats].to_numpy(float), dev.loc[tr, "y"].to_numpy(),
                               dev.loc[te, feats].to_numpy(float))
            oof[te.to_numpy()] = p
            sub = dev[te]
            h, k, e = at_budget(sub, p)
            ap = average_precision_score(sub["y"], p) if sub["y"].sum() else float("nan")
            print(f"  cam{cam}: {len(sub)} journeys, {e} errors | pulled {k}: {h} real ({100 * h / max(k, 1):.0f}% precision), "
                  f"{100 * h / max(e, 1):.0f}% of errors | avg precision {ap:.2f} (base rate {sub['y'].mean():.2f})")
            report["folds"][f"{name}_cam{cam}"] = {"pulled": k, "hit": h, "errors": e, "ap": ap}
        h, k, e = at_budget(dev, oof)
        ap = average_precision_score(dev["y"], oof)
        summary[name] = (h, k, e, ap)
        print(f"  ALL: pulled {k}: {h} real ({100 * h / k:.0f}% precision), {100 * h / e:.0f}% of errors; "
              f"avg precision {ap:.2f} (base {dev['y'].mean():.2f})")
        print("  calibration (n, predicted, observed): " +
              "  ".join(f"({n},{a:.2f},{o:.2f})" for n, a, o in calib(dev["y"].to_numpy(), oof)))
    # (ii) only if it beats (i) on EVERY fold (plan): average precision per held-out camera
    cams = sorted(dev["cam"].unique())
    every = all(report["folds"][f"boosted_cam{c}"]["ap"] > report["folds"][f"logistic_cam{c}"]["ap"] for c in cams)
    choice = "boosted" if every else "logistic"
    print(f"\nCHOICE: {choice}")
    # the shipped model: logistic as plain numbers (fit on all dev clips)
    p, (m, mu, sd) = fit_predict("logistic", dev[feats].to_numpy(float), dev["y"].to_numpy(),
                                 dev[feats].to_numpy(float))
    model = {"version": "failure_v1", "type": "logistic", "features": feats, "mean": mu.tolist(), "std": sd.tolist(),
             "coef": m.coef_[0].tolist(), "intercept": float(m.intercept_[0]),
             "trained_on": f"{stem} dev clips ({len(dev)} counted journeys)", "positive": "WRONG|DOUBLE|PHANTOM"}
    Path("data/models/failure_v1.json").write_text(json.dumps(model, indent=1))
    coefs = sorted(zip(feats, m.coef_[0]), key=lambda x: -abs(x[1]))[:12]
    print("strongest features (standardised coef): " + ", ".join(f"{f} {c:+.2f}" for f, c in coefs))
    report["choice"] = choice
    report["summary"] = {k: dict(zip(("hit", "pulled", "errors", "ap"), v)) for k, v in summary.items()}
    if final:
        for part in ("heldout", "fm51"):
            sub = df[df["part"] == part]
            if not len(sub):
                print(f"FINAL {part}: no labelled clips yet")
                continue
            z = (sub[feats].to_numpy(float) - mu) / sd
            p = 1 / (1 + np.exp(-(z @ m.coef_[0] + m.intercept_[0])))
            h, k, e = at_budget(sub, p)
            print(f"FINAL {part}: {len(sub)} journeys, {e} errors | pulled {k}: {h} real "
                  f"({100 * h / max(k, 1):.0f}% precision), {100 * h / max(e, 1):.0f}% of errors; "
                  f"avg precision {average_precision_score(sub['y'], p):.2f} (base {sub['y'].mean():.2f})")
            report[f"final_{part}"] = {"pulled": k, "hit": h, "errors": e}
    Path("data/models/failure_v1_report.json").write_text(json.dumps(report, indent=1, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
