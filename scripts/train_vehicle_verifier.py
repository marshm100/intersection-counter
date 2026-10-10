"""Train the car verifier (plan_basis STAGE 1, 2026-10-10). Label-free.

Data: data/verifier/v1/*.crops.npy + .meta.npz (scripts/build_verifier_pairs.py) - short, unambiguous
tracklets of the production dumps, 1-s blocks of the 12 fleet windows, journey-label clips excluded.
Each batch takes one block from each of WINDOWS_PER_BATCH different windows; from each block up to
TRK_PER_BLOCK tracklets x 2 crops. Positives = the other crop of the same tracklet; negatives = every other
tracklet in the batch, including the cars of the same frames (the hard ones). Supervised-contrastive loss.
Augmentation: random down-scaling to far-side sizes (then back up), small shifts / zoom, brightness.
Model: osnet_x1_0 from MSMT17 (backend/services/vehicle_verifier.py), 128 x 128 square crops.
Usage:
  .venv/Scripts/python.exe -X utf8 scripts/train_vehicle_verifier.py OUT.pt [--exclude-cam N] [--iters N]
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.vehicle_verifier import SIZE, build_backbone, embed_tensor, to_tensor  # noqa: E402

DATA = Path("data/verifier/v1")
WINDOWS_PER_BATCH = 4
TRK_PER_BLOCK = 16
TEMP = 0.1
LR = 3e-4
WARMUP = 500
SEED = 0


def load(exclude_cam: int | None):
    wins = []
    for meta in sorted(DATA.glob("*.meta.npz")):
        m = np.load(meta)
        if exclude_cam is not None and int(m["cam"][0]) == exclude_cam:
            continue
        crops = np.load(str(meta).replace(".meta.npz", ".crops.npy"), mmap_mode="r")
        blocks = defaultdict(lambda: defaultdict(list))
        for i, (b, t) in enumerate(zip(m["block"], m["tracklet"])):
            blocks[int(b)][int(t)].append(i)
        blocks = {b: [v for v in ts.values() if len(v) >= 2] for b, ts in blocks.items()}
        blocks = {b: ts for b, ts in blocks.items() if len(ts) >= 2}
        wins.append({"name": meta.name.replace(".meta.npz", ""), "crops": crops, "blocks": list(blocks.values())})
        print(f"  {wins[-1]['name']}: {len(blocks)} blocks, {sum(len(v) for v in blocks.values())} tracklets",
              flush=True)
    return wins


def augment(x: torch.Tensor, rng: np.random.Generator) -> torch.Tensor:
    """x: (N, 3, S, S) normalised. Per sample: zoom/shift, down-scale to a far-side size, brightness."""
    n = x.size(0)
    out = torch.empty_like(x)
    for i in range(n):
        xi = x[i:i + 1]
        z = rng.uniform(0.85, 1.0)
        s = int(round(SIZE * z))
        ox, oy = rng.integers(0, SIZE - s + 1), rng.integers(0, SIZE - s + 1)
        xi = F.interpolate(xi[:, :, oy:oy + s, ox:ox + s], size=(SIZE, SIZE), mode="bilinear", align_corners=False)
        if rng.random() < 0.5:
            d = int(rng.integers(14, 64))
            xi = F.interpolate(F.interpolate(xi, size=(d, d), mode="area"), size=(SIZE, SIZE),
                               mode="bilinear", align_corners=False)
        out[i] = xi[0] * float(rng.uniform(0.85, 1.15)) + float(rng.normal(0, 0.05))
    return out


def supcon(z: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    sim = z @ z.t() / TEMP
    n = z.size(0)
    eye = torch.eye(n, dtype=torch.bool, device=z.device)
    sim = sim.masked_fill(eye, -1e9)
    pos = (labels[:, None] == labels[None, :]) & ~eye
    logp = sim - torch.logsumexp(sim, dim=1, keepdim=True)
    return -(logp * pos).sum(1).div(pos.sum(1).clamp(min=1)).mean()


def main() -> int:
    args = sys.argv[1:]
    out = Path(args[0])
    excl = int(args[args.index("--exclude-cam") + 1]) if "--exclude-cam" in args else None
    iters = int(args[args.index("--iters") + 1]) if "--iters" in args else 12000
    rng = np.random.default_rng(SEED)
    torch.manual_seed(SEED)
    wins = load(excl)
    model = build_backbone().cuda().train()
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=5e-4)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda k: min(1.0, (k + 1) / WARMUP) * 0.5 * (1 + np.cos(np.pi * min(k, iters) / iters)))
    scaler = torch.amp.GradScaler("cuda")
    t0, run = time.time(), []
    for it in range(iters):
        imgs, labs = [], []
        for w_i in rng.choice(len(wins), size=min(WINDOWS_PER_BATCH, len(wins)), replace=False):
            W = wins[int(w_i)]
            trks = W["blocks"][int(rng.integers(len(W["blocks"])))]
            for t_i in rng.permutation(len(trks))[:TRK_PER_BLOCK]:
                idx = rng.choice(trks[int(t_i)], size=2, replace=False)
                for i in idx:
                    imgs.append(W["crops"][int(i)])
                labs += [len(labs) // 2] * 2          # one label per tracklet in this batch
        x = augment(to_tensor(np.stack(imgs)).cuda(), rng)
        y = torch.tensor(labs, device="cuda")
        with torch.autocast("cuda", dtype=torch.float16):
            z = embed_tensor(model, x)
        loss = supcon(z.float(), y)
        opt.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.step(opt)
        scaler.update()
        sched.step()
        run.append(float(loss))
        if (it + 1) % 250 == 0:
            print(f"  iter {it + 1}/{iters} loss {np.mean(run):.3f} lr {sched.get_last_lr()[0]:.2e} "
                  f"{(time.time() - t0) / (it + 1):.3f} s/it", flush=True)
            run = []
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out)
    print(f"saved {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
