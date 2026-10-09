"""Audit current coverage and saved misses without modifying sources or weights."""
import argparse,csv,json,sys
from pathlib import Path
from collections import Counter
import numpy as np
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/"backend"))
from app.research_metrics import coverage_audit
from app.spread.terrain import load_manifest,digest_file

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--misses",type=Path);p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    directory=root/"runtime"/"spread-data"
    manifest=load_manifest(directory)
    if digest_file(directory/"grid.npz")!=manifest["grid_sha256"]:
        raise ValueError("Grid hash mismatch; do not audit unverified data.")
    with np.load(directory/"grid.npz",allow_pickle=False) as grid:
        result={"coverage":coverage_audit(grid,manifest),"model_changed":False,"retrained":False}
    if args.misses:
        with args.misses.open(encoding="utf-8-sig",newline="") as handle:
            rows=list(csv.DictReader(handle))
        areas=np.array([float(r["area_fraction"]) for r in rows])
        result["prior_validation_misses"]={"source_sha256":digest_file(args.misses),"boxes":len(rows),
            "images":len({r["file_name"] for r in rows}),"hints":dict(Counter(r["hint"] for r in rows)),
            "area_fraction_quantiles":dict(zip(["q25","median","q75"],np.quantile(areas,[.25,.5,.75]).tolist())),
            "fraction_below_0_01_image_area":float((areas<.01).mean()),
            "warning":"기존 validation conf=0.25 미탐 자료. 실제 CCTV 미탐률이나 이번 성능 개선 수치 아님."}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
