"""Device selection: detect CUDA, fall back to CPU, pick model size."""


def detect_device(override: str | None = None) -> str:
    """Return 'cuda' if available and override allows, else 'cpu'.

    override accepts 'auto' (or None), 'cuda', or 'cpu'.
    Raises RuntimeError if 'cuda' is explicitly requested but unavailable.
    """
    normalized = (override or "auto").lower().strip()

    if normalized == "cpu":
        return "cpu"

    # Lazy torch import — avoid loading torch at module-import time so tests
    # that don't need it stay fast.
    try:
        import torch
        cuda_ok = bool(torch.cuda.is_available())
    except Exception:
        cuda_ok = False

    if normalized == "cuda":
        if not cuda_ok:
            raise RuntimeError(
                "DEVICE=cuda was requested but CUDA is not available. "
                "Install a CUDA-enabled torch build or set DEVICE=cpu/auto."
            )
        return "cuda"

    # 'auto' or anything unrecognized
    return "cuda" if cuda_ok else "cpu"


def default_model_path(device: str) -> str:
    """Return the recommended YOLO model for the given device.

    GPU: yolov8s.pt (small) — better accuracy, runs fast on CUDA
    CPU: yolov8n.pt (nano)  — minimal compute, acceptable accuracy
    """
    return "yolov8s.pt" if device == "cuda" else "yolov8n.pt"
