"""Measure held-out fire images or perimeters. Never optimize using test results.
Inputs are explicit local manifests, never downloads or source label mutations.
"""
import argparse,json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/"backend"))
from app.research_metrics import fire_metrics,perimeter_metrics
from app.detector import YoloDetector,file_hash
from app.config import Settings

def evaluate(manifest_path,kind):
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("items"):
        raise ValueError("No measured samples. Empty manifests are not evaluation results.")
    if manifest.get("split") not in ("validation","held_out_test") or not manifest.get("rights_confirmed"):
        raise ValueError("Explicit evaluation split and data-use confirmation required.")
    results=[]
    if kind=="fire":
        model=YoloDetector(Settings.from_env());model.load()
        if not model.ready:
            raise ValueError("Detector not ready")
        base=manifest_path.parent.resolve()
        for row in manifest["items"]:
            path=(base/row["image"]).resolve()
            if not path.is_relative_to(base):
                raise ValueError("Image must be inside manifest directory")
            out=model.predict(path.read_bytes())
            gt=row["fire_boxes_xyxy"]
            if any(len(b)!=4 or not(0<=b[0]<b[2]<=out["width"] and 0<=b[1]<b[3]<=out["height"]) for b in gt):
                raise ValueError("Invalid ground-truth fire boxes")
            pred=[d for d in out["detections"] if d["label"]=="fire"]
            results.append({"image":row["image"],"image_sha256":file_hash(path),**fire_metrics(pred,gt),
                            "false_alarm_on_negative_image":bool(not gt and pred)})
        tp,fp,fn=[sum(r[k] for r in results) for k in ("tp","fp","fn")]
        summary={"tp":tp,"fp":fp,"fn":fn,"precision":tp/(tp+fp) if tp+fp else None,
                 "recall":tp/(tp+fn) if tp+fn else None,
                 "false_alarm_negative_images":sum(r["false_alarm_on_negative_image"] for r in results),
                 "model_sha256":model.model_hash,"policy_sha256":model.policy_hash}
    else:
        for row in manifest["items"]:
            if not row.get("observed_at") or not row.get("incident_id") or not row.get("observation_source"):
                raise ValueError("Actual incident/time/source metadata required")
            results.append({"incident_id":row["incident_id"],"observed_at":row["observed_at"],
                            **perimeter_metrics(row["predicted_geometry"],row["observed_geometry"])})
        summary={"compared_perimeters":len(results),"warning":"시간 대응·사건 독립 분할·관측 경계 품질은 별도 검토."}
    return {"split":manifest["split"],"manifest_sha256":file_hash(manifest_path),
            "kind":kind,"results":results,"summary":summary,"training_or_tuning_performed":False}

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("kind",choices=["fire","spread"]);p.add_argument("manifest",type=Path)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();result=evaluate(a.manifest,a.kind)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result["summary"],ensure_ascii=False))
