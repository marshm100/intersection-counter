"""Device selection: detect CUDA / OpenVINO iGPU, fall back to CPU, pick model size."""


def _openvino_igpu_available() -> bool:
    """True when the OpenVINO runtime is importable AND an Intel GPU is present.

    ~3.7x over PyTorch-CPU on yolo26s@960 (scripts/bench_openvino.py)."""
    try:
        import openvino as ov
        return "GPU" in ov.Core().available_devices
    except Exception:
        return False


def detect_device(override: str | None = None) -> str:
    """Return the detection device: 'cuda', 'openvino', or 'cpu'.

    override accepts 'auto' (or None), 'cuda', 'openvino', or 'cpu':
      - 'cpu'      -> always cpu
      - 'openvino' -> the Intel iGPU iff runtime + GPU present, else cpu
      - 'cuda'     -> cuda, or RuntimeError if unavailable
      - 'auto'     -> cuda if available, else the Intel iGPU via OpenVINO if
                      available, else cpu. Auto-preferring the iGPU means the
                      interactive app uses it WITHOUT a manual DEVICE=openvino.
                      An auto choice is safe: when the OpenVINO export is missing
                      the detector falls back to cpu (only an EXPLICIT
                      DEVICE=openvino fails loudly), so auto never blocks
                      processing.
    Raises RuntimeError only if 'cuda' is explicitly requested but unavailable.
    """
    normalized = (override or "auto").lower().strip()

    if normalized == "cpu":
        return "cpu"

    if normalized == "openvino":
        return "openvino" if _openvino_igpu_available() else "cpu"

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

    # 'auto' or anything unrecognized: prefer CUDA, then the Intel iGPU, then CPU.
    if cuda_ok:
        return "cuda"
    if _openvino_igpu_available():
        return "openvino"
    return "cpu"


def default_model_path(device: str) -> str:
    """Return the recommended YOLO model for the given device.

    GPU: yolov8s.pt (small) — better accuracy, runs fast on CUDA
    CPU: yolov8n.pt (nano)  — minimal compute, acceptable accuracy
    """
    return "yolov8s.pt" if device == "cuda" else "yolov8n.pt"
