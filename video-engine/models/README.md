# Object detection models

The engine looks for a YOLO-style ONNX model at `MODEL_PATH`
(default `/models/yolov8n.onnx`). **If the file is missing the engine logs a
warning once and runs motion-only** — nothing breaks.

## Getting yolov8n.onnx (CPU / default)

```bash
pip install ultralytics
yolo export model=yolov8n.pt format=onnx imgsz=640
# produces yolov8n.onnx — copy it here (video-engine/models/) before building
# the image, or mount it into the container:
#   volumes:
#     - ./video-engine/models/yolov8n.onnx:/models/yolov8n.onnx:ro
```

Any YOLOv5/v8/v11 export with the standard `(1, 84, 8400)` output layout and
COCO-80 classes works. Input size is read from the model (640 default).
Detected classes are mapped to the contract labels: `person`, `car`
(car/truck/bus/motorcycle/bicycle), `animal` (cat/dog/bird/horse/...).

## Accelerator variants

The engine picks ONNX Runtime execution providers automatically from the
hardware report (`horus/engine/hardware`):

| Hardware        | Install (see requirements.txt)        | Provider used                |
|-----------------|----------------------------------------|------------------------------|
| NVIDIA GPU      | `onnxruntime-gpu` (+ `tensorrt`)       | TensorRT → CUDA → CPU        |
| Intel CPU/iGPU  | `onnxruntime-openvino` + `openvino`    | OpenVINO → CPU               |
| Anything        | `onnxruntime` (default)                | CPU                          |
| Coral EdgeTPU   | detected, but requires a *tflite* model (`yolov8n_edgetpu.tflite`) and a pycoral backend — not wired yet; falls back to CPU |

No model conversion is needed for TensorRT/OpenVINO: they consume the same
`.onnx` file through their execution providers. For FP16/INT8 quantized
variants, export with `half=True` / `int8=True` and point `MODEL_PATH` at the
resulting file.
