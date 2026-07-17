"""Tests for device selection (GPU/CPU)."""

from unittest.mock import patch

import pytest

from backend.services.device import default_model_path, detect_device


class TestDetectDevice:
    def test_cpu_explicit(self):
        assert detect_device("cpu") == "cpu"

    def test_auto_with_cuda_available(self):
        with patch("torch.cuda.is_available", return_value=True):
            assert detect_device("auto") == "cuda"

    def test_auto_without_cuda_or_igpu(self):
        with patch("torch.cuda.is_available", return_value=False), \
             patch("backend.services.device._openvino_igpu_available",
                   return_value=False):
            assert detect_device("auto") == "cpu"

    def test_auto_prefers_igpu_when_no_cuda(self):
        # No CUDA but an Intel iGPU + OpenVINO present -> auto picks the iGPU so
        # the interactive app uses it without a manual DEVICE=openvino.
        with patch("torch.cuda.is_available", return_value=False), \
             patch("backend.services.device._openvino_igpu_available",
                   return_value=True):
            assert detect_device("auto") == "openvino"

    def test_openvino_explicit_with_igpu(self):
        with patch("backend.services.device._openvino_igpu_available",
                   return_value=True):
            assert detect_device("openvino") == "openvino"

    def test_openvino_explicit_without_igpu_falls_back_to_cpu(self):
        with patch("backend.services.device._openvino_igpu_available",
                   return_value=False):
            assert detect_device("openvino") == "cpu"

    def test_cuda_explicit_with_cuda_available(self):
        with patch("torch.cuda.is_available", return_value=True):
            assert detect_device("cuda") == "cuda"

    def test_cuda_explicit_without_cuda_raises(self):
        with patch("torch.cuda.is_available", return_value=False):
            with pytest.raises(RuntimeError, match="CUDA is not available"):
                detect_device("cuda")

    def test_none_acts_as_auto(self):
        with patch("torch.cuda.is_available", return_value=False), \
             patch("backend.services.device._openvino_igpu_available",
                   return_value=False):
            assert detect_device(None) == "cpu"

    def test_unknown_acts_as_auto(self):
        with patch("torch.cuda.is_available", return_value=True):
            assert detect_device("nonsense") == "cuda"


class TestDefaultModelPath:
    def test_gpu_uses_small_model(self):
        assert default_model_path("cuda") == "yolov8s.pt"

    def test_cpu_uses_nano_model(self):
        assert default_model_path("cpu") == "yolov8n.pt"
