"""Offline measurement with explicit human ground truth; no training/test tuning."""
import numpy as np
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform
from .policy import box_iou

def fire_metrics(predictions, truth, iou=.5):
    matched=set();tp=0
    for p in sorted(predictions,key=lambda p:-p["score"]):
        eligible=[(box_iou(p["xyxy"],g),i) for i,g in enumerate(truth) if i not in matched]
        score,index=max(eligible,default=(0,-1))
        if score>=iou:
            tp+=1;matched.add(index)
    fp,fn=len(predictions)-tp,len(truth)-tp
    return {"tp":tp,"fp":fp,"fn":fn,"precision":tp/(tp+fp) if tp+fp else None,
            "recall":tp/(tp+fn) if tp+fn else None}

def perimeter_metrics(predicted, observed):
    project=Transformer.from_crs(4326,5179,always_xy=True).transform
    p,o=[transform(project,shape(g)) for g in (predicted,observed)]
    if not p.is_valid or not o.is_valid or p.geom_type not in ("Polygon","MultiPolygon") or o.geom_type not in ("Polygon","MultiPolygon"):
        raise ValueError("유효한 WGS84 화재 경계 다각형이 필요합니다.")
    union=p.union(o).area
    overlap=p.intersection(o).area
    return {"iou":overlap/union if union else None,
            "observed_coverage":overlap/o.area if o.area else None,
            "predicted_area_ha":p.area/10000,"observed_area_ha":o.area/10000,
            "relative_area_error":abs(p.area-o.area)/o.area if o.area else None,
            "boundary_hausdorff_m":p.boundary.hausdorff_distance(o.boundary)}

def coverage_audit(grid,manifest):
    valid=grid["valid"]
    known=int(valid.sum())
    elevation=np.isfinite(grid["elevation"])
    seen=np.zeros(valid.shape,bool);components=[]
    for r,c in np.argwhere(valid):
        if seen[r,c]:
            continue
        todo=[(int(r),int(c))];seen[r,c]=True;size=0
        while todo:
            row,col=todo.pop();size+=1
            for dr in (-1,0,1):
                for dc in (-1,0,1):
                    rr,cc=row+dr,col+dc
                    if (dr or dc) and 0<=rr<valid.shape[0] and 0<=cc<valid.shape[1] and valid[rr,cc] and not seen[rr,cc]:
                        seen[rr,cc]=True;todo.append((rr,cc))
        components.append(size)
    return {"grid_m":manifest["grid_m"],"shape":list(valid.shape),"known_forest_cells":known,
            "known_forest_area_ha":known*manifest["grid_m"]**2/10000,
            "valid_dem_cells":int(elevation.sum()),"valid_forest_fraction_of_dem":known/int(elevation.sum()),
            "connected_components":len(components),"largest_component_cells":max(components,default=0),
            "isolated_single_cells":components.count(1),"data_sha256":manifest["data_sha256"],
            "real_fire_accuracy":"not_evaluated","warning":"DEM 중 계산 가능한 숲 비율이며, 대구 산림 전체 커버리지나 정확도 아님."}
