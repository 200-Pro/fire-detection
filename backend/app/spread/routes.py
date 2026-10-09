"""Authenticated, owner-isolated jobs with durable state and a dedicated CPU process."""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import json
import multiprocessing
from pathlib import Path
import threading
from typing import Literal
from uuid import uuid4
import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pyproj import Transformer
from rasterio.transform import Affine
from .weather import WeatherClient
from .nifos import DangerClient
from .terrain import load_manifest
from .engine import run_simulation


class ManualWeather(BaseModel):
    temperature_c: float = Field(default=20, ge=-50, le=60, allow_inf_nan=False)
    humidity_pct: float = Field(default=40, ge=0, le=100, allow_inf_nan=False)
    wind_speed_ms: float = Field(default=3, ge=0, le=40, allow_inf_nan=False)
    wind_from_deg: float = Field(default=270, ge=0, lt=360, allow_inf_nan=False)
    rain_mm: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)


class SimulationInput(BaseModel):
    latitude: float = Field(ge=33, le=39, allow_inf_nan=False)
    longitude: float = Field(ge=124, le=132, allow_inf_nan=False)
    event_id: str | None = Field(default=None, max_length=32, pattern="^[a-f0-9]{32}$")
    location_confirmed: bool = False
    horizon_min: Literal[10, 30, 60] = 30
    model: Literal["circle", "ellipse", "ca"] = "ca"
    weather_mode: Literal["kma", "manual"] = "kma"
    manual_weather: ManualWeather | None = None
    runs: int = Field(default=30, ge=10, le=100)
    seed: int = Field(default=42, ge=0, le=2147483647)
    base_ros_m_min: float = Field(default=6, ge=1, le=30, allow_inf_nan=False)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class SpreadService:
    def __init__(self, data_dir, jobs_dir):
        self.data_dir = Path(data_dir)
        self.jobs_dir = Path(jobs_dir)
        self.weather = WeatherClient()
        self.danger = DangerClient()
        self.tasks = set()
        self.lock = threading.RLock()
        self.pool = None
        self.inflight = 0

    def startup(self):
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        # API restart cannot silently claim an abandoned calculation is running.
        for path in self.jobs_dir.glob("*/job.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data["state"] in ("queued", "running"):
                    data.update(state="failed", finished_at=utcnow(), message="서버가 재시작되어 계산이 중단됐습니다. 다시 실행하세요.")
                    self.write_job(data)
            except (OSError, ValueError, KeyError):
                continue

    async def shutdown(self):
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        if self.pool:
            await asyncio.to_thread(self.pool.shutdown, wait=True, cancel_futures=True)

    async def submit_request(self, payload, owner_id, context=None):
        self.validate_point(payload.latitude, payload.longitude)
        if self.inflight >= 3:
            raise HTTPException(429, "계산 대기열이 가득 찼습니다.")
        self.inflight += 1
        try:
            if payload.weather_mode == "kma":
                weather = await self.weather.observation(payload.latitude, payload.longitude)
                if not weather.get("available") or not weather.get("fresh"):
                    raise HTTPException(503, "유효한 최신 기상이 없습니다. 자동 계산을 보류합니다.")
            else:
                if payload.manual_weather is None:
                    raise HTTPException(422, "수동 기상 입력이 필요합니다.")
                weather = {**payload.manual_weather.model_dump(), "source":"manual",
                           "observed_at":None, "fetched_at":utcnow(), "fresh":False, "quality":"synthetic"}
            request = payload.model_dump(exclude={"manual_weather","weather_mode"})
            request["weather"] = weather
            request["location_source"] = "automatic_calibrated_estimate" if (context or {}).get("origin")=="automatic_calibrated_estimate" else "manual_scenario"
            job = {"id":uuid4().hex,"owner_id":owner_id,"state":"queued","created_at":utcnow(),
                   "request":request,"research_only":True,
                   "context":{"nifos":self.danger.snapshot(),"nifos_used_in_spread":False,**(context or {})}}
            self.write_job(job)
            task=asyncio.create_task(self.calculate(job))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            return job
        except Exception:
            self.inflight -= 1
            raise

    def write_job(self, job):
        directory = self.jobs_dir / job["id"]
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "job.next.json"
        with self.lock:
            temporary.write_text(json.dumps(job, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            temporary.replace(directory / "job.json")

    def get_job(self, job_id, owner_id):
        if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            raise HTTPException(404, "시뮬레이션을 찾을 수 없습니다.")
        try:
            with self.lock:
                job = json.loads((self.jobs_dir / job_id / "job.json").read_text(encoding="utf-8"))
            if job["owner_id"] != owner_id:
                raise HTTPException(404, "시뮬레이션을 찾을 수 없습니다.")
            return job
        except (OSError, ValueError, KeyError):
            raise HTTPException(404, "시뮬레이션을 찾을 수 없습니다.")

    def manifest(self):
        try:
            return load_manifest(self.data_dir)
        except (OSError, ValueError):
            raise HTTPException(503, "지도 전처리가 필요합니다. scripts/prepare-spread-data.py를 실행하세요.")

    def validate_point(self, lat, lon):
        manifest = self.manifest()
        x, y = Transformer.from_crs(4326, manifest["crs"], always_xy=True).transform(lon, lat)
        col, row = (~Affine(*manifest["transform"])) * (x, y)
        row, col = int(np.floor(row)), int(np.floor(col))
        with np.load(self.data_dir / "grid.npz", allow_pickle=False) as data:
            valid = data["valid"]
            if not (0 <= row < valid.shape[0] and 0 <= col < valid.shape[1]) or not valid[row, col]:
                raise HTTPException(422, "발화점이 사용 가능한 숲 격자 밖입니다. 숲 내부를 선택하세요.")

    def validate_uncertainty(self,lat,lon,radius):
        from shapely.geometry import Point,mapping
        from rasterio.features import rasterize
        manifest=self.manifest()
        affine=Affine(*manifest["transform"])
        x,y=Transformer.from_crs(4326,manifest["crs"],always_xy=True).transform(lon,lat)
        disk=Point(x,y).buffer(radius,quad_segs=64)
        col0,row0=(~affine)*(x-radius,y+radius)
        col1,row1=(~affine)*(x+radius,y-radius)
        with np.load(self.data_dir/"grid.npz",allow_pickle=False) as grid:
            valid=grid["valid"]
            if col0<0 or row0<0 or col1>=valid.shape[1] or row1>=valid.shape[0]:
                raise HTTPException(422,"위치 가정 오차 영역이 자료 밖입니다. 자동 확산을 보류합니다.")
            mask=rasterize([(mapping(disk),1)],out_shape=valid.shape,transform=affine,all_touched=True).astype(bool)
            if np.any(mask & ~valid):
                raise HTTPException(422,"위치 가정 오차 영역에 미확인 숲 격자가 있습니다. 자동 확산을 보류합니다.")

    async def calculate(self, job):
        try:
            job.update(state="running", started_at=utcnow())
            self.write_job(job)
            if self.pool is None:
                self.pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
            result = await asyncio.get_running_loop().run_in_executor(self.pool, run_simulation, job["request"], str(self.data_dir))
            path = self.jobs_dir / job["id"] / "result.geojson"
            def save_result():
                temporary = path.with_suffix(".next.geojson")
                temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
                temporary.replace(path)
            await asyncio.to_thread(save_result)
            job.update(state="completed", finished_at=utcnow(), summary=result["summary"])
        except Exception:
            # Never serialize raw exception text: external URLs may contain credentials.
            job.update(state="failed", finished_at=utcnow(), message="확산 계산에 실패했습니다. 지도 자료와 입력 조건을 확인하세요.")
        finally:
            try:
                self.write_job(job)
            finally:
                # A full disk must not permanently consume queue capacity.
                self.inflight -= 1


def register_spread_routes(app, cfg, user_dependency, event_lookup):
    service = SpreadService(cfg.spread_data_path, cfg.spread_jobs_path)
    app.state.spread = service
    router = APIRouter(prefix="/api", tags=["Research spread"])

    @router.get("/spread/status")
    def status(owner=Depends(user_dependency)):
        try:
            manifest = service.manifest()
            return {"ready": True, "manifest": manifest, "inflight": service.inflight,
                    "nifos": {"message": "국립산림과학원 대구 시도 위험지수는 별도 참고 정보로 조회합니다. 확산 속도에는 적용하지 않습니다."}}
        except HTTPException:
            return {"ready": False, "message": "지도 전처리가 필요합니다."}

    @router.get("/spread/forest")
    def forest(owner=Depends(user_dependency)):
        service.manifest()
        return json.loads((service.data_dir / "forest.geojson").read_text(encoding="utf-8"))

    @router.get("/spread/terrain")
    def terrain(owner=Depends(user_dependency)):
        service.manifest()
        return json.loads((service.data_dir / "terrain.geojson").read_text(encoding="utf-8"))

    @router.get("/weather")
    async def weather(latitude: float, longitude: float, owner=Depends(user_dependency)):
        if not (33 <= latitude <= 39 and 124 <= longitude <= 132):
            raise HTTPException(422, "대한민국 범위의 좌표가 필요합니다.")
        return await service.weather.observation(latitude, longitude)

    @router.post("/simulations", status_code=202)
    async def submit(payload: SimulationInput, owner=Depends(user_dependency)):
        if not payload.location_confirmed:
            raise HTTPException(422, "가상 발화점을 직접 지정·확인해야 합니다. 카메라 위치를 자동 발화점으로 사용하지 않습니다.")
        if payload.event_id:
            event_lookup(payload.event_id, owner)
        return await service.submit_request(payload, owner.id)

    @router.get("/simulations")
    def listing(owner=Depends(user_dependency)):
        # Ownership filter is applied before returning any private request or result.
        items = []
        for path in service.jobs_dir.glob("*/job.json"):
            try:
                with service.lock:
                    data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("owner_id") == owner.id:
                    items.append(data)
            except (OSError, ValueError):
                continue
        return {"items": sorted(items, key=lambda x: x["created_at"], reverse=True)[:30]}

    @router.get("/fire-danger")
    async def fire_danger(owner=Depends(user_dependency)):
        return await service.danger.observation()

    @router.get("/simulations/{job_id}")
    def detail(job_id: str, owner=Depends(user_dependency)):
        return service.get_job(job_id, owner.id)

    @router.get("/simulations/{job_id}/perimeters")
    def perimeters(job_id: str, owner=Depends(user_dependency)):
        job = service.get_job(job_id, owner.id)
        if job["state"] != "completed":
            raise HTTPException(409, "아직 계산 결과가 없습니다.")
        return json.loads((service.jobs_dir / job_id / "result.geojson").read_text(encoding="utf-8"))

    app.include_router(router)
    return service
