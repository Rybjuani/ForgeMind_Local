"""Tests para app.gpu_detect (con mock de subprocess; no requiere GPU real)."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from app.gpu_detect import (
    detect_amd_gpu,
    detect_gpus,
    detect_vulkan,
    detect_vulkan_dll,
    detect_vulkaninfo,
    system_summary,
)


def _ps_response(payload, returncode=0):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = payload
    r.stderr = ""
    return r


class TestDetectGpus:
    @patch("app.gpu_detect._run_ps")
    def test_parses_list(self, mock_run_ps: MagicMock) -> None:
        mock_run_ps.return_value = json.dumps([
            {"Name": "Radeon RX550", "AdapterRAM": 4294967296,
             "DriverVersion": "31.0.21001.45007", "VideoProcessor": "Radeon RX550"},
            {"Name": "Intel UHD 630", "AdapterRAM": 1073741824,
             "DriverVersion": "x", "VideoProcessor": "Intel"},
        ])
        gpus = detect_gpus()
        assert len(gpus) == 2
        assert gpus[0]["name"] == "Radeon RX550"
        assert gpus[0]["adapter_ram_bytes"] == 4294967296

    @patch("app.gpu_detect._run_ps")
    def test_parses_single_dict(self, mock_run_ps: MagicMock) -> None:
        # WMI a veces devuelve un dict suelto si hay un solo GPU
        mock_run_ps.return_value = json.dumps(
            {"Name": "Radeon RX550", "AdapterRAM": 4294967296,
             "DriverVersion": "x", "VideoProcessor": "Radeon"}
        )
        gpus = detect_gpus()
        assert len(gpus) == 1
        assert gpus[0]["name"] == "Radeon RX550"

    @patch("app.gpu_detect._run_ps")
    def test_empty_when_no_output(self, mock_run_ps: MagicMock) -> None:
        mock_run_ps.return_value = None
        assert detect_gpus() == []

    @patch("app.gpu_detect._run_ps")
    def test_malformed_returns_empty(self, mock_run_ps: MagicMock) -> None:
        mock_run_ps.return_value = "this is not json"
        assert detect_gpus() == []


class TestDetectAmdGpu:
    @patch("app.gpu_detect.detect_gpus")
    def test_finds_radeon(self, mock_detect_gpus: MagicMock) -> None:
        mock_detect_gpus.return_value = [
            {"name": "Intel UHD 630", "adapter_ram_bytes": 1024 ** 3,
             "driver_version": "x", "video_processor": "Intel"},
            {"name": "AMD Radeon RX550/550 Series", "adapter_ram_bytes": 4 * 1024 ** 3,
             "driver_version": "y", "video_processor": "Radeon"},
        ]
        amd = detect_amd_gpu()
        assert amd is not None
        assert "Radeon" in amd["name"]
        assert amd["vram_bytes"] == 4 * 1024 ** 3
        assert "4.00 GB" in amd["vram_human"]

    @patch("app.gpu_detect.detect_gpus")
    def test_returns_none_when_no_amd(self, mock_detect_gpus: MagicMock) -> None:
        mock_detect_gpus.return_value = [
            {"name": "Intel UHD 630", "adapter_ram_bytes": 1024 ** 3,
             "driver_version": "x", "video_processor": "Intel"},
        ]
        assert detect_amd_gpu() is None

    @patch("app.gpu_detect.detect_gpus")
    def test_handles_empty(self, mock_detect_gpus: MagicMock) -> None:
        mock_detect_gpus.return_value = []
        assert detect_amd_gpu() is None


class TestDetectVulkan:
    @patch("app.gpu_detect.shutil.which")
    @patch("app.gpu_detect.subprocess.run")
    def test_with_vulkaninfo_json(self, mock_run: MagicMock, mock_which: MagicMock) -> None:
        mock_which.return_value = "/fake/vulkaninfo"
        mock_run.return_value = _ps_response(json.dumps({
            "VulkanAPIVersion": "1.3.0",
            "driverVersion": "999",
            "devices": [{"name": "RADV", "apiVersion": "1.3.0",
                         "driverVersion": "x", "type": "INTEGRATED_GPU"}],
        }))
        info = detect_vulkaninfo()
        assert info is not None
        assert info["available"] is True
        assert info["api_version"] == "1.3.0"

    @patch("app.gpu_detect.shutil.which")
    def test_no_vulkaninfo_returns_none(self, mock_which: MagicMock) -> None:
        mock_which.return_value = None
        assert detect_vulkaninfo() is None

    @patch("app.gpu_detect.shutil.which")
    @patch("app.gpu_detect.subprocess.run")
    def test_vulkaninfo_failure_returns_none(self, mock_run: MagicMock, mock_which: MagicMock) -> None:
        mock_which.return_value = "/fake/vulkaninfo"
        mock_run.return_value = _ps_response("", returncode=1)
        assert detect_vulkaninfo() is None

    @patch("app.gpu_detect.detect_vulkan_dll", return_value=True)
    @patch("app.gpu_detect.detect_vulkaninfo", return_value=None)
    def test_dll_only(self, mock_info: MagicMock, mock_dll: MagicMock) -> None:
        v = detect_vulkan()
        assert v["available"] is True
        assert v["vulkan_dll_present"] is True
        assert v["vulkaninfo_installed"] is False

    @patch("app.gpu_detect.detect_vulkan_dll", return_value=False)
    @patch("app.gpu_detect.detect_vulkaninfo", return_value=None)
    def test_nothing_available(self, mock_info: MagicMock, mock_dll: MagicMock) -> None:
        v = detect_vulkan()
        assert v["available"] is False


class TestSystemSummary:
    @patch("app.gpu_detect.detect_vulkan")
    @patch("app.gpu_detect.detect_gpus")
    def test_shape(self, mock_gpus: MagicMock, mock_vk: MagicMock) -> None:
        mock_gpus.return_value = [{"name": "x", "adapter_ram_bytes": 1024 ** 3,
                                    "driver_version": "v", "video_processor": "p"}]
        mock_vk.return_value = {"available": False, "vulkaninfo_installed": False,
                                 "vulkan_dll_present": False, "info": None}
        s = system_summary()
        assert "gpus" in s
        assert "vulkan" in s
        assert isinstance(s["gpus"], list)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only ctypes probe")
class TestVulkanDll:
    def test_returns_bool(self) -> None:
        v = detect_vulkan_dll()
        assert isinstance(v, bool)
        # No garantizamos True/False porque depende del SDK instalado