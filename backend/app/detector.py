from hashlib import sha256
from io import BytesIO
import json
import os
import time
import warnings
from PIL import Image, ImageDraw, ImageOps
from .policy import filter_predictions

def file_hash(path):
    h = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            h.update(chunk)
    return h.hexdigest()

def decode_frame(data, settings):
    if not data or len(data) > settings.max_frame_bytes:
        raise ValueError("이미지 크기는 2MB 이하여야 합니다.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in ("JPEG", "PNG", "WEBP"):
                    raise ValueError("JPEG, PNG, WebP 이미지만 지원합니다.")
                w, h = image.size
                if w*h > settings.max_pixels or max(w,h) > 4096 or min(w,h) < 16:
                    raise ValueError("이미지 해상도가 허용 범위를 벗어났습니다.")
                return ImageOps.exif_transpose(image).convert("RGB")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("이미지를 읽을 수 없습니다.") from exc

class YoloDetector:
    def __init__(self, settings):
        self.settings = settings
        self.model = None
        self.ready = False
        self.error = None
        self.info = {}

    def load(self):
        try:
            if not self.settings.model_path.is_file():
                raise ValueError("models/best.pt 파일이 없습니다.")
            config = json.loads(self.settings.policy_path.read_text(encoding="utf-8"))
            self.model_hash = file_hash(self.settings.model_path)
            self.policy_hash = file_hash(self.settings.policy_path)
            if self.model_hash != config["model_sha256"]:
                raise ValueError("모델과 후처리 설정 해시가 다릅니다. 새 모델 검증 후 설정을 갱신하세요.")
            raw = config["raw_predict"]
            if raw["conf"] > config["filter"]["weak_conf"]:
                raise ValueError("예측 후보 기준이 후처리 기준보다 높습니다.")
            os.environ.setdefault("YOLO_CONFIG_DIR", str(self.settings.storage_path.parent / "ultralytics"))
            from ultralytics import YOLO, settings as yolo_settings
            yolo_settings.update({"sync": False, "clearml": False, "comet": False, "mlflow": False, "wandb": False})
            import torch
            torch.set_num_threads(self.settings.torch_threads)
            self.model = YOLO(str(self.settings.model_path))
            if self.model.names != {0: "smoke", 1: "fire"}:
                raise ValueError("0=smoke, 1=fire 모델만 지원합니다.")
            self.config = config
            self.model.predict(Image.new("RGB", (640,480)), device=self.settings.device, verbose=False, **raw)
            self.ready = True
            self.info = {"ready": True, "name": "YOLO11n · fire/smoke", "model_sha256": self.model_hash,
                         "policy_sha256": self.policy_hash, "policy_version": config["version"],
                         "classes": self.model.names, "input_size": raw["imgsz"], "device": self.settings.device,
                         "filter": config["filter"], "validation": config.get("validation")}
        except Exception as exc:
            self.error = str(exc)
            self.info = {"ready": False, "error": self.error}

    def predict(self, data):
        if not self.ready:
            raise RuntimeError("모델 준비가 완료되지 않았습니다.")
        start = time.perf_counter()
        image = decode_frame(data, self.settings)
        result = self.model.predict(image, device=self.settings.device, verbose=False, **self.config["raw_predict"])[0]
        predictions = [{"class_id": int(b[5]), "score": float(b[4]), "xyxy": b[:4]} for b in result.boxes.data.cpu().tolist()]
        indices = filter_predictions(predictions, self.config["filter"], result.orig_shape)
        h, w = result.orig_shape
        detections = []
        for i in indices:
            p = predictions[i]
            detections.append({"class_id": p["class_id"], "label": self.model.names[p["class_id"]],
                               "score": round(p["score"], 5), "xyxy": p["xyxy"],
                               "box": [p["xyxy"][0]/w, p["xyxy"][1]/h,
                                       (p["xyxy"][2]-p["xyxy"][0])/w, (p["xyxy"][3]-p["xyxy"][1])/h]})
        draw = ImageDraw.Draw(image)
        for d in detections:
            color = "#ff7048" if d["label"] == "fire" else "#e9b93d"
            draw.rectangle(d["xyxy"], outline=color, width=3)
            draw.text((d["xyxy"][0]+4, max(4,d["xyxy"][1]-15)), f'{d["label"]} {d["score"]:.0%}', fill=color, stroke_width=1, stroke_fill="#121821")
        image.thumbnail((960,960))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        return {"detections": detections, "width": w, "height": h,
                "fire_candidate": any(d["label"]=="fire" for d in detections),
                "smoke_candidate": any(d["label"]=="smoke" for d in detections),
                "latency_ms": round((time.perf_counter()-start)*1000, 1), "jpeg": buffer.getvalue()}
