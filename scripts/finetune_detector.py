"""Chunked local-CPU detector fine-tune (plan_detector_finetune_2026-07-16).

Trains in SESSIONS of a few epochs so the laptop stays usable and any
interruption (sleep, kill, crash) costs at most one chunk. Chunks are
sequential WARM-STARTS: chunk k loads the previous chunk's last.pt and
trains --epochs-per-session more epochs at lr0 * gamma^k (a global decay
standing in for a single run's cosine schedule) — deterministic and
restartable, no resume-state edge cases. A manifest JSON in the run dir
tracks cumulative epochs; invoke repeatedly (manually or via a loop) until
--epochs-total is reached.

Usage (one chunk per invocation):
  py scripts/finetune_detector.py --data data/finetune_v1/dataset.yaml
  py scripts/finetune_detector.py --data ... --status     # just report

After the final chunk PASSES the held-out-site gate (the plan's, not this
script's): export for the iGPU with scripts/export_yolo_openvino.py.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="dataset.yaml from prep_finetune_labels")
    ap.add_argument("--base", default="yolo26s.pt")
    ap.add_argument("--run-dir", default="runs/finetune_v1")
    ap.add_argument("--epochs-total", type=int, default=40)
    ap.add_argument("--epochs-per-session", type=int, default=8)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--freeze", type=int, default=10,
                    help="freeze the first N layers (backbone) — the CPU-budget lever")
    ap.add_argument("--lr0", type=float, default=0.005)
    ap.add_argument("--lr-gamma", type=float, default=0.6,
                    help="per-chunk lr0 decay (chunk k trains at lr0*gamma^k)")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_p = run_dir / "manifest.json"
    manifest = (json.loads(manifest_p.read_text()) if manifest_p.exists()
                else {"chunks": [], "epochs_done": 0})

    done = manifest["epochs_done"]
    if args.status or done >= args.epochs_total:
        state = "COMPLETE" if done >= args.epochs_total else "in progress"
        print(f"{args.run_dir}: {done}/{args.epochs_total} epochs "
              f"({len(manifest['chunks'])} chunks) — {state}")
        if done >= args.epochs_total and not args.status:
            print("Nothing to do. Raise --epochs-total to continue, or gate "
                  "the weights (held-out SITE) and export for the iGPU.")
        return 0

    k = len(manifest["chunks"])
    epochs = min(args.epochs_per_session, args.epochs_total - done)
    lr0 = args.lr0 * (args.lr_gamma ** k)
    prev = manifest["chunks"][-1]["last"] if manifest["chunks"] else None
    weights = prev if prev and Path(prev).exists() else args.base
    print(f"chunk {k}: {epochs} epochs from {weights} at lr0={lr0:.5f} "
          f"({done}/{args.epochs_total} done)", flush=True)

    from ultralytics import YOLO
    model = YOLO(weights)
    results = model.train(
        data=args.data, epochs=epochs, imgsz=args.imgsz, batch=args.batch,
        device="cpu", freeze=args.freeze, lr0=lr0, patience=0,
        project=str(run_dir), name=f"chunk{k}", exist_ok=True,
        verbose=True, plots=False, val=True)
    last = str(Path(results.save_dir) / "weights" / "last.pt")
    metrics = {}
    try:
        metrics = {kk: round(float(vv), 4)
                   for kk, vv in results.results_dict.items()}
    except Exception:
        pass
    manifest["chunks"].append({"chunk": k, "epochs": epochs, "lr0": lr0,
                               "weights_in": weights, "last": last,
                               "metrics": metrics})
    manifest["epochs_done"] = done + epochs
    manifest_p.write_text(json.dumps(manifest, indent=1))
    print(f"chunk {k} done -> {last}  "
          f"({manifest['epochs_done']}/{args.epochs_total} epochs total)")
    if manifest["epochs_done"] >= args.epochs_total:
        print("TRAINING TARGET REACHED — next: the held-out-site gate, then "
              "scripts/export_yolo_openvino.py for iGPU inference.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
