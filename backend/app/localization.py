"""Planar image-ground approximation; never camera-installation = ignition.
Not suitable for steep terrain, aerial flame, PTZ or uncorrected lens distortion.
"""
import base64
import hashlib
import json
import cv2
import numpy as np
from pyproj import Transformer
from shapely.geometry import Point, Polygon
from pydantic import BaseModel, Field

class GroundPoint(BaseModel):
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    latitude: float = Field(ge=33, le=39, allow_inf_nan=False)
    longitude: float = Field(ge=124, le=132, allow_inf_nan=False)

class CalibrationInput(BaseModel):
    reference_sha256: str | None = Field(default=None,min_length=64,max_length=64,pattern="^[a-f0-9]{64}$")
    points: list[GroundPoint] = Field(min_length=4, max_length=20)
    checks: list[GroundPoint] = Field(min_length=2, max_length=10)
    uncertainty_m: float = Field(ge=90, le=1000, allow_inf_nan=False)
    fixed_planar_view_confirmed: bool = False
    reference_note: str = Field(min_length=5, max_length=300)

to_m = Transformer.from_crs(4326, 5179, always_xy=True)
to_geo = Transformer.from_crs(5179, 4326, always_xy=True)

def image_features(data):
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None or min(image.shape) < 32:
        raise ValueError("보정용 프레임을 읽을 수 없습니다.")
    h,w = image.shape
    image = cv2.resize(image, (640, max(32,round(h*640/w))))
    keys,desc = cv2.ORB_create(nfeatures=700).detectAndCompute(image,None)
    if desc is None or len(keys)<40:
        raise ValueError("고정 배경 특징이 부족합니다. 선명한 기준 프레임이 필요합니다.")
    return np.array([k.pt for k in keys],np.float32),desc,image.shape

def fit_calibration(payload, reference):
    if not payload.fixed_planar_view_confirmed:
        raise ValueError("고정 시야·평면 근사·렌즈 왜곡 보정 조건을 확인해야 합니다.")
    src=np.array([[p.x,p.y] for p in payload.points],np.float64)
    dst=np.array([to_m.transform(p.longitude,p.latitude) for p in payload.points],np.float64)
    hull=Polygon(src).convex_hull
    if hull.area<.01 or len(set(map(tuple,src)))!=len(src):
        raise ValueError("기준점은 중복 없이 충분한 화면 영역에 분산돼야 합니다.")
    if Polygon(dst).convex_hull.area<25:
        raise ValueError("지도 기준점도 실제로 분리된 지면 위치여야 합니다.")
    checks=np.array([[p.x,p.y] for p in payload.checks])
    if any(np.linalg.norm(a-b)<.01 for i,a in enumerate(checks) for b in checks[i+1:]):
        raise ValueError("독립 검사점도 서로 떨어진 위치여야 합니다.")
    origin=dst.mean(axis=0)
    matrix,_=cv2.findHomography(src,dst-origin,method=0)
    if matrix is None or not np.isfinite(matrix).all() or abs(np.linalg.det(matrix))<1e-8:
        raise ValueError("보정 행렬을 계산하지 못했습니다.")
    def project(x,y):
        a=matrix @ [x,y,1]
        if abs(a[2])<1e-8:
            raise ValueError("보정이 불안정합니다.")
        return a[:2]/a[2]+origin
    fit_error=max(float(np.linalg.norm(project(p.x,p.y)-d)) for p,d in zip(payload.points,dst))
    errors=[]
    for p in payload.checks:
        if any(np.linalg.norm(a-[p.x,p.y])<.01 for a in src):
            raise ValueError("검사점은 보정 기준점과 독립된 위치여야 합니다.")
        if not hull.covers(Point(p.x,p.y)):
            raise ValueError("검사점은 기준점 볼록 영역 안이어야 합니다.")
        errors.append(float(np.linalg.norm(project(p.x,p.y)-to_m.transform(p.longitude,p.latitude))))
    if max(errors)>50 or fit_error>50:
        raise ValueError("보정 오차가 50m를 초과합니다. 기준점을 다시 확인하세요.")
    keys,desc,shape=image_features(reference)
    result={**payload.model_dump(),"matrix":matrix.tolist(),"origin":origin.tolist(),
            "hull":list(hull.exterior.coords),"max_check_error_m":max(errors),"fit_error_m":fit_error,
            "reference_sha256":hashlib.sha256(reference).hexdigest(),"reference_shape":list(shape),
            "keys":keys.tolist(),"descriptors":base64.b64encode(desc.tobytes()).decode(),
            "uncertainty_m":max(payload.uncertainty_m,2*max(errors),90),
            "method":"planar_homography_bottom_center_v1"}
    result["sha256"]=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
    return result

def stable_view(c, frame):
    try:
        keys,desc,shape=image_features(frame)
        if list(shape)!=c["reference_shape"]:
            return False
        reference=np.frombuffer(base64.b64decode(c["descriptors"]),np.uint8).reshape(-1,32)
        pairs=cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(reference,desc,k=2)
        good=[a for pair in pairs if len(pair)==2 for a,b in [pair] if a.distance<.7*b.distance]
        if len(good)<25:
            return False
        src=np.float32([c["keys"][m.queryIdx] for m in good])
        dst=np.float32([keys[m.trainIdx] for m in good])
        h,mask=cv2.findHomography(src,dst,cv2.RANSAC,2)
        if h is None or int(mask.sum())<20 or float(mask.mean())<.55:
            return False
        height,width=shape
        probes=np.float32([[[width*.2,height*.2],[width*.8,height*.2],
                           [width*.2,height*.8],[width*.8,height*.8]]])
        moved=cv2.perspectiveTransform(probes,h)
        return bool(np.max(np.linalg.norm(moved-probes,axis=2))<5)
    except (ValueError,KeyError,cv2.error):
        return False

def estimate_location(c, detections, frame):
    if not c:
        return {"available":False,"reason":"화면–지도 보정 없음. 카메라 좌표로 대체하지 않습니다."}
    if not stable_view(c,frame):
        return {"available":False,"reason":"시야 변경·특징 부족. 회전/줌/야간 등 보정을 재확인하세요."}
    points=[]
    for d in detections:
        if d["label"]!="fire":
            continue
        x,y,w,h=d["box"]
        anchor=[x+w/2,y+h]
        if not Polygon(c["hull"]).covers(Point(*anchor)):
            continue
        out=np.array(c["matrix"]) @ [*anchor,1]
        if abs(out[2])<1e-8:
            continue
        east,north=out[:2]/out[2]+c["origin"]
        lon,lat=to_geo.transform(east,north)
        if np.isfinite([lon,lat]).all():
            points.append({"latitude":lat,"longitude":lon,"easting":east,"northing":north,"score":d["score"]})
    if not points:
        return {"available":False,"reason":"불꽃의 지면 접점이 보정 구역 밖입니다."}
    a=max(points,key=lambda p:p["score"])
    if any(np.hypot(p["easting"]-a["easting"],p["northing"]-a["northing"])>150 for p in points):
        return {"available":False,"reason":"분리된 불꽃 후보가 있어 단일 발화점을 선택하지 않습니다."}
    return {"available":True,"latitude":a["latitude"],"longitude":a["longitude"],
            "uncertainty_m":c["uncertainty_m"],"method":c["method"],"calibration_sha256":c["sha256"],
            "research_only":True,"warning":"박스 아래 중심의 평면 근사입니다. 최초 발화점·화재 확정·실측 오차 보장이 아닙니다."}
