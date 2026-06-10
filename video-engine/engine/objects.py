"""Optional object detection over a YOLO-style ONNX model.

* Model file at ``MODEL_PATH`` (default ``/models/yolov8n.onnx``).
* If the file is missing, we log once and degrade gracefully to motion-only.
* Accelerators plug in as onnxruntime execution providers selected from the
  hardware report (TensorRT / OpenVINO / CPU). Coral EdgeTPU is not an ORT
  provider — when detected we currently log it and fall back to CPU; a
  tflite/pycoral backend can be added behind the same ``ObjectDetector`` API.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger("engine.objects")

# COCO-80 class names (index = class id of standard YOLO exports).
COCO_CLASSES: tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "stop sign",
    "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag",
    "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon",
    "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot",
    "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
    "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
)

# Contract labels: person | car | animal (CONTRACTS §1.1).
CLASS_GROUPS: dict[str, str] = {
    "person": "person",
    "car": "car", "truck": "car", "bus": "car", "motorcycle": "car", "bicycle": "car",
    "bird": "animal", "cat": "animal", "dog": "animal", "horse": "animal",
    "sheep": "animal", "cow": "animal", "elephant": "animal", "bear": "animal",
    "zebra": "animal", "giraffe": "animal",
}


@dataclass(frozen=True)
class Detection:
    label: str           # contract group: person | car | animal
    raw_class: str       # original COCO class
    confidence: float
    box: tuple[float, float, float, float]  # normalized x1, y1, x2, y2


# ---------------------------------------------------------------------------
# Pure helpers (testable without a model)
# ---------------------------------------------------------------------------

def providers_for(inference_path: str) -> list[str]:
    """onnxruntime provider list for the selected hardware path."""
    if inference_path == "tensorrt":
        return ["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]
    if inference_path == "openvino":
        return ["OpenVINOExecutionProvider", "CPUExecutionProvider"]
    if inference_path == "edgetpu":
        # EdgeTPU needs a tflite/pycoral runtime, not ORT; CPU until plugged.
        log.info("EdgeTPU detected but ORT backend in use; running ONNX on CPU")
        return ["CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def letterbox(image: np.ndarray, size: int = 640) -> tuple[np.ndarray, float, tuple[float, float]]:
    """Resize with unchanged aspect ratio + gray padding. Returns
    (padded_image, scale, (pad_x, pad_y))."""
    h, w = image.shape[:2]
    scale = min(size / w, h and size / h or 1.0)
    new_w, new_h = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = cv2.resize(image, (new_w, new_h))
    pad_x, pad_y = (size - new_w) / 2.0, (size - new_h) / 2.0
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    top, left = int(round(pad_y - 0.1)), int(round(pad_x - 0.1))
    canvas[top:top + new_h, left:left + new_w] = resized
    return canvas, scale, (pad_x, pad_y)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float = 0.45) -> list[int]:
    """Plain numpy non-max suppression; boxes are [x1, y1, x2, y2]."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[i] + areas[order[1:]] - inter
        iou = np.where(union > 0, inter / union, 0.0)
        order = order[1:][iou <= iou_threshold]
    return keep


def postprocess_yolo(output: np.ndarray, scale: float, pad: tuple[float, float],
                     frame_size: tuple[int, int], conf_threshold: float = 0.4,
                     iou_threshold: float = 0.45) -> list[Detection]:
    """Decode YOLOv8 raw output (1, 4+nc, anchors) or (1, anchors, 4+nc)."""
    out = np.squeeze(output)
    if out.ndim != 2:
        return []
    if out.shape[0] < out.shape[1]:  # (84, 8400) -> (8400, 84)
        out = out.T
    boxes_cxcywh = out[:, :4]
    class_scores = out[:, 4:]
    class_ids = class_scores.argmax(axis=1)
    confidences = class_scores[np.arange(len(class_ids)), class_ids]
    mask = confidences >= conf_threshold
    if not mask.any():
        return []
    boxes_cxcywh, class_ids, confidences = boxes_cxcywh[mask], class_ids[mask], confidences[mask]

    # cx,cy,w,h (letterboxed pixels) -> x1,y1,x2,y2 in original frame pixels
    fw, fh = frame_size
    pad_x, pad_y = pad
    x1 = (boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2 - pad_x) / scale
    y1 = (boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2 - pad_y) / scale
    x2 = (boxes_cxcywh[:, 0] + boxes_cxcywh[:, 2] / 2 - pad_x) / scale
    y2 = (boxes_cxcywh[:, 1] + boxes_cxcywh[:, 3] / 2 - pad_y) / scale
    boxes = np.stack([x1, y1, x2, y2], axis=1)

    detections: list[Detection] = []
    for idx in nms(boxes, confidences, iou_threshold):
        class_id = int(class_ids[idx])
        raw_class = COCO_CLASSES[class_id] if class_id < len(COCO_CLASSES) else str(class_id)
        group = CLASS_GROUPS.get(raw_class)
        if group is None:
            continue  # contract only carries person/car/animal
        bx = boxes[idx]
        detections.append(Detection(
            label=group,
            raw_class=raw_class,
            confidence=float(confidences[idx]),
            box=(
                max(0.0, float(bx[0]) / fw), max(0.0, float(bx[1]) / fh),
                min(1.0, float(bx[2]) / fw), min(1.0, float(bx[3]) / fh),
            ),
        ))
    return detections


# ---------------------------------------------------------------------------
# Detector (lazy ORT session, shared across workers)
# ---------------------------------------------------------------------------

class ObjectDetector:
    """Loads the ONNX session lazily and is safe to share between threads."""

    def __init__(self, model_path: str, inference_path: str = "onnx_cpu",
                 input_size: int = 640, conf_threshold: float = 0.4) -> None:
        self._model_path = model_path
        self._inference_path = inference_path
        self._input_size = input_size
        self._conf_threshold = conf_threshold
        self._session = None
        self._input_name: str | None = None
        self._lock = threading.Lock()
        self._failed = False  # log-once guard

    @property
    def available(self) -> bool:
        self._ensure_session()
        return self._session is not None

    def _ensure_session(self) -> None:
        if self._session is not None or self._failed:
            return
        with self._lock:
            if self._session is not None or self._failed:
                return
            import os
            if not os.path.isfile(self._model_path):
                log.warning("Object model not found at %s; running motion-only "
                            "(drop a yolov8n.onnx there — see models/README.md)",
                            self._model_path)
                self._failed = True
                return
            try:
                import onnxruntime as ort
                providers = [p for p in providers_for(self._inference_path)
                             if p in ort.get_available_providers()] or ["CPUExecutionProvider"]
                self._session = ort.InferenceSession(self._model_path, providers=providers)
                self._input_name = self._session.get_inputs()[0].name
                shape = self._session.get_inputs()[0].shape
                if isinstance(shape[-1], int) and shape[-1] > 0:
                    self._input_size = int(shape[-1])
                log.info("Object model %s loaded (providers=%s, input=%d)",
                         self._model_path, providers, self._input_size)
            except Exception:  # noqa: BLE001
                log.exception("Failed to load ONNX model %s; motion-only mode", self._model_path)
                self._failed = True

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        self._ensure_session()
        if self._session is None:
            return []
        try:
            padded, scale, pad = letterbox(frame_bgr, self._input_size)
            blob = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            blob = np.transpose(blob, (2, 0, 1))[np.newaxis]
            with self._lock:  # ORT sessions are thread-safe, but keep ordering simple
                outputs = self._session.run(None, {self._input_name: blob})
            return postprocess_yolo(
                outputs[0], scale, pad,
                (frame_bgr.shape[1], frame_bgr.shape[0]),
                conf_threshold=self._conf_threshold,
            )
        except Exception:  # noqa: BLE001
            log.exception("Object inference failed; continuing motion-only for this frame")
            return []
