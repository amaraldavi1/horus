"""Hardware capability detection (decode + inference paths).

Every probe is wrapped so that missing binaries/devices/libraries never crash
the engine: the worst case is plain CPU decode + ONNX CPU inference.

CONTRACTS.md §1.3 — payload shape of `horus/engine/hardware` (retained).
"""
from __future__ import annotations

import glob
import importlib
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

log = logging.getLogger("engine.hardware")

# Preference order, best first.
_DECODE_ORDER = ("nvdec", "qsv", "vaapi", "cpu")
_INFERENCE_ORDER = ("tensorrt", "edgetpu", "openvino", "onnx_cpu")

CORAL_USB_ID = "18d1:9302"


@dataclass
class HardwareReport:
    """Detected capabilities + the paths the engine selected."""

    decode: dict[str, bool] = field(default_factory=dict)
    inference: dict[str, bool] = field(default_factory=dict)
    selected_decode: str = "cpu"
    selected_inference: str = "onnx_cpu"
    gpus: list[str] = field(default_factory=list)

    def to_payload(self) -> dict:
        return {
            "decode": self.decode,
            "inference": self.inference,
            "selected": {"decode": self.selected_decode, "inference": self.selected_inference},
            "gpus": self.gpus,
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }


# ---------------------------------------------------------------------------
# Probes — every one of these must be exception-proof.
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: float = 10.0) -> str:
    """Run a command and return stdout+stderr; '' on any failure."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return (proc.stdout or "") + (proc.stderr or "")
    except Exception:  # noqa: BLE001 - tool missing, timeout, permissions...
        return ""


def ffmpeg_hwaccels() -> set[str]:
    out = _run(["ffmpeg", "-hide_banner", "-hwaccels"])
    accels: set[str] = set()
    for line in out.splitlines():
        token = line.strip().lower()
        if token and " " not in token and token != "hardware":
            accels.add(token)
    return accels


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:  # noqa: BLE001
        return False


def detect_nvidia() -> tuple[bool, list[str]]:
    """(has nvidia device, gpu names)."""
    names: list[str] = []
    out = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    for line in out.splitlines():
        line = line.strip()
        if line and "error" not in line.lower() and "failed" not in line.lower():
            names.append(line)
    has_dev = bool(names) or os.path.exists("/dev/nvidia0")
    return has_dev, names


def detect_vaapi_device() -> bool:
    try:
        return bool(glob.glob("/dev/dri/renderD*"))
    except Exception:  # noqa: BLE001
        return False


def detect_coral() -> bool:
    try:
        if glob.glob("/dev/apex_*"):
            return True
    except Exception:  # noqa: BLE001
        pass
    return CORAL_USB_ID in _run(["lsusb"])


def _other_gpu_names() -> list[str]:
    names: list[str] = []
    out = _run(["lspci"])
    for line in out.splitlines():
        if "VGA compatible controller" in line or "Display controller" in line:
            # "00:02.0 VGA compatible controller: Intel ... UHD Graphics 630"
            names.append(line.split(":", 2)[-1].strip())
    return names


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def pick_best(capabilities: dict[str, bool], order: tuple[str, ...]) -> str:
    for name in order:
        if capabilities.get(name):
            return name
    return order[-1]


def detect_hardware() -> HardwareReport:
    accels = ffmpeg_hwaccels()
    has_nvidia, nvidia_names = detect_nvidia()
    has_render_node = detect_vaapi_device()

    decode = {
        "nvdec": has_nvidia and ("cuda" in accels or "nvdec" in accels),
        "vaapi": has_render_node and "vaapi" in accels,
        "qsv": has_render_node and "qsv" in accels,
        "cpu": True,
    }
    inference = {
        "tensorrt": has_nvidia and _module_available("tensorrt"),
        "edgetpu": detect_coral(),
        "openvino": _module_available("openvino"),
        "onnx_cpu": _module_available("onnxruntime"),
    }

    gpus = nvidia_names + [n for n in _other_gpu_names() if "nvidia" not in n.lower()]

    report = HardwareReport(
        decode=decode,
        inference=inference,
        selected_decode=pick_best(decode, _DECODE_ORDER),
        selected_inference=pick_best(inference, _INFERENCE_ORDER),
        gpus=gpus,
    )
    log.info("Hardware: decode=%s inference=%s gpus=%s",
             report.selected_decode, report.selected_inference, gpus or "none")
    return report


# ---------------------------------------------------------------------------
# Helpers consumed by the workers/recorder
# ---------------------------------------------------------------------------

def ffmpeg_input_hwaccel_args(decode_path: str) -> list[str]:
    """Extra ffmpeg input args for the chosen decode path (remux ignores them,
    but decode-heavy paths may use them)."""
    if decode_path == "nvdec":
        return ["-hwaccel", "cuda"]
    if decode_path == "qsv":
        return ["-hwaccel", "qsv"]
    if decode_path == "vaapi":
        return ["-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128"]
    return []


def opencv_capture_options(decode_path: str) -> str:
    """Value for the OPENCV_FFMPEG_CAPTURE_OPTIONS env var.

    OpenCV's FFMPEG backend reads `key;value|key;value` pairs from this
    variable. We always force RTSP over TCP (lossy UDP corrupts frames) and
    enable hw decode when available.
    """
    opts = ["rtsp_transport;tcp", "stimeout;5000000"]
    hwaccel = {"nvdec": "cuda", "qsv": "qsv", "vaapi": "vaapi"}.get(decode_path)
    if hwaccel:
        opts.append(f"hwaccel;{hwaccel}")
    return "|".join(opts)


def status_decode_name(decode_path: str) -> str:
    """Map internal decode key to CONTRACTS §1.2 vocabulary."""
    return decode_path if decode_path in ("vaapi", "nvdec", "qsv") else "cpu"


def status_detect_name(inference_path: str, objects_enabled: bool) -> str:
    """Map internal inference key to CONTRACTS §1.2 vocabulary."""
    if not objects_enabled:
        return "none"
    return {"onnx_cpu": "onnx-cpu"}.get(inference_path, inference_path)
