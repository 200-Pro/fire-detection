"""Registered CCTV supervision independent of any browser/video selection."""
import asyncio
from dataclasses import replace
import hashlib
import json
import time
from datetime import timedelta
from typing import Literal
from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, func
from shapely.geometry import Point, Polygon
from .alerts import AlarmGate
from .models import Camera, Monitor, IncidentLocation, AlertReview, AuditLog, MonitorTrial, utcnow
from .security import aware
from .soak import TrialMetrics, active_trial, expire_trials, register_evidence, cleanup_evidence
from .localization import CalibrationInput, fit_calibration, estimate_location
from .policy import box_iou
from .stream_reader import HlsReader, StreamError
from .spread.routes import SimulationInput

class Rules(BaseModel):
    minimum_score: float = Field(default=.25,ge=.25,le=.95,allow_inf_nan=False)
    ignore_polygons: list[list[tuple[float,float]]] = Field(default_factory=list,max_length=10)

    @model_validator(mode="after")
    def polygons(self):
        for p in self.ignore_polygons:
            if not 3<=len(p)<=30 or any(not 0<=v<=1 for point in p for v in point):
                raise ValueError("제외 구역은 0~1 좌표 3~30개여야 합니다.")
            if not Polygon(p).is_valid or Polygon(p).area<=0:
                raise ValueError("제외 구역 다각형이 잘못됐습니다.")
        return self

class MonitorInput(BaseModel):
    enabled: bool = False
    rights_confirmed: bool = False
    approval_reference: str = Field(default="",max_length=300)
    interval_seconds: float = Field(default=3,ge=2,le=10,allow_inf_nan=False)
    rules: Rules = Field(default_factory=Rules)
    auto_spread: bool = False
    research_acknowledged: bool = False
    trial_minutes: int | None = Field(default=None,ge=1,le=1440)
    evidence_hours: int = Field(default=24,ge=1,le=24)

class ReviewInput(BaseModel):
    outcome: Literal["true_fire","false_alarm","uncertain"]
    reason: str = Field(default="",max_length=300)

def apply_rules(result, rules):
    polygons=[Polygon(p) for p in rules.get("ignore_polygons",[])]
    kept=[]
    for d in result["detections"]:
        x,y,w,h=d["box"]
        if any(p.covers(Point(x+w/2,y+h/2)) for p in polygons):
            continue
        if d["label"]=="fire" and d["score"]<rules.get("minimum_score",.25):
            continue
        kept.append(d)
    return {**result,"detections":kept,"fire_candidate":any(d["label"]=="fire" for d in kept),
            "smoke_candidate":any(d["label"]=="smoke" for d in kept)}

def filtered_preview(data,result,cfg):
    from io import BytesIO
    from PIL import ImageDraw
    from .detector import decode_frame
    image=decode_frame(data,cfg)
    draw=ImageDraw.Draw(image)
    for d in result["detections"]:
        color="#ff7048" if d["label"]=="fire" else "#e9b93d"
        draw.rectangle(d["xyxy"],outline=color,width=3)
        draw.text((d["xyxy"][0]+4,max(4,d["xyxy"][1]-15)),
                  f'{d["label"]} {d["score"]:.0%}',fill=color,stroke_width=1,stroke_fill="#121821")
    image.thumbnail((960,960))
    out=BytesIO();image.save(out,format="JPEG",quality=80)
    return out.getvalue()

class MonitorService:
    def __init__(self,cfg,sessions,providers,process_frame,spread,hub,previews):
        self.cfg,self.sessions,self.providers=cfg,sessions,providers
        self.process_frame,self.spread,self.hub,self.previews=process_frame,spread,hub,previews
        self.reader=HlsReader()
        self.tasks,self.states,self.anchors,self.followups={},{},{},set()
        self.stop_event=asyncio.Event()
        self.supervisor=None
        self.decode_slots=asyncio.Semaphore(1)
        self.gate=AlarmGate(replace(cfg,frame_gap_seconds=30,alarm_min_seconds=6))
        self.revision_locks={}
        self.references={}
        self.metrics={}
        self.metrics_revisions={}
        self.cleanup_task=None
        self.last_cleanup=-1e12

    def start(self):
        self.supervisor=asyncio.create_task(self.supervise())

    def policy_hash(self,m,original):
        c=self.gate.settings
        return hashlib.sha256(json.dumps({"base_policy":original,"rules":m.rules,"revision":m.revision,
            "smoke_min_score":.5,
            "temporal":{"version":"fire_smoke_spatial_iou_0.2_v2","hits":c.alarm_hits,"window":c.alarm_window,
                        "gap_seconds":c.frame_gap_seconds,"min_seconds":c.alarm_min_seconds,
                        "cooldown_seconds":c.alarm_cooldown_seconds}},sort_keys=True).encode()).hexdigest()

    async def close(self):
        self.stop_event.set()
        if self.supervisor:
            await self.supervisor
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(),return_exceptions=True)
        if self.followups:
            await asyncio.gather(*tuple(self.followups),return_exceptions=True)
        if self.cleanup_task:
            await asyncio.gather(self.cleanup_task,return_exceptions=True)
        expire_trials(self.sessions,self.reports())

    def reports(self):
        return {identity:{"revision":self.metrics_revisions.get(identity),"report":metrics.report()}
                for identity,metrics in self.metrics.items()}

    def current(self,camera_id,revision=None):
        with self.sessions() as db:
            m=db.get(Monitor,camera_id);c=db.get(Camera,camera_id)
            if not m or not c or not m.enabled or not c.enabled or c.archived_at is not None:
                return None
            if revision is not None and m.revision!=revision:
                return None
            trial=active_trial(db,camera_id,m.revision)
            if trial and aware(trial.deadline)<=utcnow():
                return None
            return m,c

    def status(self,m):
        runtime=self.states.get(m.camera_id,{"state":"stopped","message":"상시 분석 중지"})
        if not m.enabled:
            runtime={**runtime,"state":"stopped","message":"상시 분석 중지"}
        if m.enabled and not self.cfg.cctv_ai_approved:
            runtime={**runtime,"state":"approval_required","message":"기관 허용 확인 후 서버 승인 설정이 필요합니다."}
        return {"camera_id":m.camera_id,"catalog_id":m.catalog_id,"enabled":m.enabled,
                "road":m.road,"video_type":m.video_type,"interval_seconds":m.interval_seconds,
                "approval_reference":m.approval_reference,"rules":m.rules,
                "auto_spread":m.auto_spread,"revision":m.revision,
                "calibration":{k:v for k,v in (m.calibration or {}).items()
                               if k not in ("keys","descriptors","matrix","origin","hull")},
                **runtime}

    def trial_data(self,trial):
        report=self.metrics[trial.camera_id].report() if (trial.state=="running" and
            self.metrics_revisions.get(trial.camera_id)==trial.revision) else trial.report
        return {"id":trial.id,"camera_id":trial.camera_id,"state":trial.state,
                "started_at":aware(trial.started_at).isoformat(),"deadline":aware(trial.deadline).isoformat(),
                "ended_at":aware(trial.ended_at).isoformat() if trial.ended_at else None,
                "evidence_hours":trial.evidence_hours,"report":report}

    def spatial_reset(self,m,result,label='fire'):
        identity=m.camera_id if label=='fire' else m.camera_id+':smoke'
        fires=[d["box"] for d in result["detections"] if d["label"]==label and (label=='fire' or d['score']>=.5)]
        now=time.monotonic()
        prior=self.anchors.get(identity)
        self.anchors[identity]=(now,fires or (prior[1] if prior else []))
        def corners(b):
            x,y,w,h=b;return [x,y,x+w,y+h]
        return bool(fires and prior and prior[1] and (now-prior[0]>30 or
                    not any(box_iou(corners(a),corners(b))>=.2 for a in fires for b in prior[1])))

    async def supervise(self):
        while not self.stop_event.is_set():
            expire_trials(self.sessions,self.reports())
            if time.monotonic()-self.last_cleanup>=60 and (not self.cleanup_task or self.cleanup_task.done()):
                if self.cleanup_task:
                    await asyncio.gather(self.cleanup_task,return_exceptions=True)
                self.last_cleanup=time.monotonic()
                self.cleanup_task=asyncio.create_task(asyncio.to_thread(cleanup_evidence,self.sessions,self.store))
            with self.sessions() as db:
                wanted=list(db.scalars(select(Monitor).join(Camera).where(
                    Monitor.enabled.is_(True),Camera.enabled.is_(True)).order_by(Monitor.camera_id)))
            ids={m.camera_id for m in wanted[:self.cfg.monitor_capacity]}
            for m in wanted[self.cfg.monitor_capacity:]:
                self.states[m.camera_id]={"state":"capacity_blocked","message":"서버 처리 한도 초과. 분석되지 않습니다."}
            for identity,task in list(self.tasks.items()):
                if identity not in ids:
                    task.cancel()
                if task.done():
                    await asyncio.gather(task,return_exceptions=True)
                    self.tasks.pop(identity,None)
            if self.cfg.cctv_ai_approved:
                for m in wanted[:self.cfg.monitor_capacity]:
                    if m.camera_id not in self.tasks:
                        self.tasks[m.camera_id]=asyncio.create_task(self.worker(m.camera_id))
            try:
                await asyncio.wait_for(self.stop_event.wait(),timeout=1)
            except asyncio.TimeoutError:
                pass

    async def worker(self,identity):
        state={"state":"connecting","message":"제공기관 연결 준비","frames":0,"failures":0}
        self.states[identity]=state
        current=self.current(identity)
        if not current:
            return
        with self.sessions() as db:
            trial=active_trial(db,identity,current[0].revision)
            previous=trial.report if trial else {}
        metrics=TrialMetrics(previous)
        self.metrics[identity]=metrics
        self.metrics_revisions[identity]=current[0].revision
        network_previous={key:previous.get(key,0) for key in ("video_http_attempts","video_success_bytes")}
        self.reader.stats.pop(identity,None)
        # A restarted worker must not inherit an expired provider playback session.
        self.reader.forget(identity)
        state["frames"]=previous.get("frames",0)
        state["failures"]=previous.get("failures",0)
        delay=3
        previous_frame=None
        fresh_at=time.monotonic()
        previous_revision=None
        try:
            while not self.stop_event.is_set():
                cycle_started=time.monotonic()
                current=self.current(identity)
                if not current:
                    break
                m,camera=current
                if previous_revision!=m.revision:
                    self.gate.reset(identity);self.anchors.pop(identity,None)
                    previous_revision=m.revision
                try:
                    state.update(state="connecting",message="최신 영상 프레임 대기")
                    catalog=await self.providers.catalog(m.road,m.video_type)
                    item=next((i for i in catalog["items"] if i["id"]==m.catalog_id),None)
                    if not item:
                        raise ValueError("목록에서 사라진 카메라입니다.")
                    wait_started=time.monotonic()
                    async with self.decode_slots:
                        metrics.observe("decode_wait_ms",(time.monotonic()-wait_started)*1000)
                        read_task=asyncio.create_task(asyncio.to_thread(self.reader.read,identity,item["url"]))
                        try:
                            frame=await asyncio.shield(read_task)
                        except asyncio.CancelledError:
                            await asyncio.gather(read_task,return_exceptions=True)
                            raise
                    if not self.current(identity,m.revision):
                        continue
                    if frame is not None:
                        digest=hashlib.sha256(frame).hexdigest()
                        if digest!=previous_frame:
                            fresh_at=time.monotonic();previous_frame=digest
                            state.update(state="analyzing",message="서버 AI 분석 중 · 화면 재생 불필요")
                            result=await self.process_frame(camera,frame,monitor=m)
                            state.update(frames=state["frames"]+1,last_frame=utcnow().isoformat(),
                                         state="running",message="상시 분석 중",latency_ms=result["latency_ms"])
                            metrics.frame()
                            if result.get("event"):
                                metrics.add("alarms")
                    else:
                        metrics.add("unchanged_samples")
                    if time.monotonic()-fresh_at>30:
                        self.gate.reset(identity)
                        state.update(state="stale",message="30초 이상 새로운 프레임 없음. 정상 감시로 취급하지 않습니다.")
                        metrics.add("stale_samples")
                    delay=m.interval_seconds
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.gate.reset(identity)
                    state.update(state="backoff",message="연결·해석·추론 실패. 제한된 간격으로 재시도합니다.",
                                 failures=state["failures"]+1)
                    metrics.add("failures")
                    metrics.totals["last_failure_type"]=type(exc).__name__
                    metrics.totals["last_failure_detail"]=str(exc) if isinstance(exc,StreamError) else "영상/모델 작업 실패 (민감한 예외 내용은 표출하지 않음)"
                    delay=min(300,max(15,delay*2))
                    if isinstance(exc,StreamError):
                        metrics.totals['last_failure_stage']=exc.stage
                        metrics.totals['last_http_status']=exc.status_code
                        if exc.status_code in (401,403,429): delay=max(60,delay)
                        delay=max(delay,exc.retry_after)
                    state['retry_at']=(utcnow()+timedelta(seconds=delay)).isoformat()
                    state['message']=metrics.totals['last_failure_detail']
                metrics.observe("cycle_ms",(time.monotonic()-cycle_started)*1000)
                for key,value in self.reader.stats.get(identity,{}).items():
                    metrics.totals[key]=network_previous.get(key,0)+value
                state["metrics"]=metrics.report()
                await asyncio.sleep(delay)
        finally:
            self.gate.reset(identity);self.anchors.pop(identity,None);self.anchors.pop(identity+':smoke',None)
            self.reader.forget(identity)
            state.update(state="stopped",message="상시 분석 중지")

    def alert_created(self,m,event,result,frame):
        register_evidence(self.sessions,m,event)
        task=asyncio.create_task(self.locate_and_simulate(m,event,result,frame))
        self.followups.add(task)
        def done(t):
            self.followups.discard(t)
            if not t.cancelled():
                t.exception()
        task.add_done_callback(done)

    async def locate_and_simulate(self,m,event,result,frame):
        try:
            estimate=await asyncio.to_thread(estimate_location,m.calibration,result["detections"],frame)
            estimate["monitor_rules"]=m.rules
            estimate["monitor_revision"]=m.revision
            location=IncidentLocation(event_id=event["id"],owner_id=m.owner_id,estimate=estimate,
                                      status="estimated" if estimate["available"] else "unavailable")
            with self.sessions() as db:
                if db.get(IncidentLocation,event["id"]):
                    return
                db.add(location);db.commit()
            message="자동 위치 추정만 저장했습니다. 확산은 별도 설정입니다."
            job=None
            lock=self.revision_locks.setdefault(m.camera_id,asyncio.Lock())
            async with lock:
                if m.auto_spread and estimate["available"] and self.current(m.camera_id,m.revision):
                    if estimate["uncertainty_m"]>150:
                        message="위치 가정 오차가 커 자동 확산을 보류합니다."
                    else:
                        try:
                            payload=SimulationInput(latitude=estimate["latitude"],longitude=estimate["longitude"],
                                                    event_id=event["id"],location_confirmed=True,runs=10)
                            # Validate the whole uncertainty disk, not only its center.
                            self.spread.validate_uncertainty(payload.latitude,payload.longitude,estimate["uncertainty_m"])
                            job=await self.spread.submit_request(payload,m.owner_id,
                                {"origin":"automatic_calibrated_estimate","location_estimate":estimate,
                                 "warning":"중심점 1개 시나리오. 위치 오차 전체 확산 앙상블이나 실제 예측 아님."})
                            message="보정 위치 중심점의 연구용 자동 확산 작업을 생성했습니다."
                        except HTTPException as exc:
                            message=exc.detail
                with self.sessions() as db:
                    saved=db.get(IncidentLocation,event["id"])
                    saved.simulation_id=job["id"] if job else None
                    saved.status="simulation_queued" if job else saved.status
                    saved.message=message;db.commit()
            self.hub.publish(m.owner_id,{"type":"incident.location","event_id":event["id"],
                                         "estimate":estimate,"simulation_id":job["id"] if job else None})
        except Exception:
            # Alarm was already persisted. Follow-up failure must never erase it.
            return

def register_monitor_routes(app,cfg,user,sessions,providers,process_frame,spread,hub,previews,owned_alert):
    service=MonitorService(cfg,sessions,providers,process_frame,spread,hub,previews)
    service.store=app.state.store
    app.state.monitoring=service

    @app.get("/api/monitoring")
    def listing(owner=Depends(user)):
        with sessions() as db:
            rows=list(db.scalars(select(Monitor).where(Monitor.owner_id==owner.id)))
            return {"items":[{**service.status(m),"name":db.get(Camera,m.camera_id).name} for m in rows if db.get(Camera,m.camera_id).archived_at is None],
                    "server_approved":cfg.cctv_ai_approved,"capacity":cfg.monitor_capacity,
                    "message":"등록·활성화된 카메라만 분석. 전체 공공 목록 자동 수집 아님. 서버가 켜져 있어야 합니다."}

    @app.get("/api/monitoring/trials")
    def trials(owner=Depends(user)):
        with sessions() as db:
            rows=list(db.scalars(select(MonitorTrial).where(MonitorTrial.owner_id==owner.id)
                .order_by(MonitorTrial.started_at.desc()).limit(100)))
            return {"items":[{**service.trial_data(t),"name":db.get(Camera,t.camera_id).name} for t in rows],
                    "warning":"연결 시험 기록이며 화재 탐지 정확도 검증 결과가 아닙니다. 수신량은 성공 응답만 집계합니다."}

    @app.put("/api/cctv/{catalog_id}/monitor")
    async def configure(catalog_id:str,payload:MonitorInput,owner=Depends(user)):
        item=providers.find(catalog_id)
        if item["video_type"] not in (1,4):
            raise HTTPException(422,"상시 감시는 HLS 유형만 지원합니다.")
        if payload.enabled:
            if not cfg.cctv_ai_approved:
                raise HTTPException(409,"제공기관 허용 확인 전입니다. 상시 수집은 서버에서 차단되어 있습니다.")
            if not payload.rights_confirmed or len(payload.approval_reference.strip())<5:
                raise HTTPException(422,"분석·저장 허용 근거와 확인이 필요합니다.")
            if url_host(item["url"]) not in service.reader.allowed_hosts:
                raise HTTPException(409,"기관 영상 호스트를 서버 허용 목록에 등록해야 합니다.")
        if payload.auto_spread and not payload.research_acknowledged:
            raise HTTPException(422,"자동 확산의 연구용·보정 오차 한계를 확인해야 합니다.")
        from .security import digest
        identity=digest(owner.id+":its:"+catalog_id)[:32]
        lock=service.revision_locks.setdefault(identity,asyncio.Lock())
        async with lock:
            with sessions() as db:
                camera=db.get(Camera,identity)
                if camera and camera.archived_at is not None:
                    raise HTTPException(409,'이 카메라는 목록에서 제거됐습니다. 카메라 관리에서 먼저 복원하세요.')
                if not camera:
                    count=db.scalar(select(func.count()).select_from(Camera).where(
                        Camera.owner_id==owner.id,Camera.kind!="sample",Camera.archived_at.is_(None)))
                    if count>=cfg.max_cameras:
                        raise HTTPException(409,"카메라 등록 한도입니다.")
                    camera=Camera(id=identity,owner_id=owner.id,name=item["name"],kind="its",
                                  location=f'{item["latitude"]:.5f}, {item["longitude"]:.5f} · 설치점, 발화점 아님')
                    db.add(camera);db.flush()
                if payload.enabled and not camera.enabled:
                    raise HTTPException(409,"카메라 관리에서 비활성화된 카메라입니다. 먼저 활성화하세요.")
                m=db.get(Monitor,identity)
                if not m:
                    m=Monitor(camera_id=identity,owner_id=owner.id,catalog_id=catalog_id,
                              road=item["road"],video_type=item["video_type"])
                    db.add(m);db.flush()
                if payload.enabled and not m.enabled:
                    count=db.scalar(select(func.count()).select_from(Monitor).join(Camera).where(Monitor.enabled.is_(True),Camera.enabled.is_(True)))
                    if count>=cfg.monitor_capacity:
                        raise HTTPException(409,"서버 상시 분석 한도입니다. 기존 감시를 중지하세요.")
                if payload.auto_spread and not m.calibration:
                    raise HTTPException(422,"화면–지도 보정을 먼저 등록해야 합니다.")
                m.enabled=payload.enabled;m.approval_reference=payload.approval_reference.strip()
                m.interval_seconds=payload.interval_seconds;m.rules=payload.rules.model_dump()
                m.auto_spread=payload.auto_spread;m.revision+=1;m.updated_at=utcnow()
                # Close any previous trial before enrolling a new revision.
                for prior in db.scalars(select(MonitorTrial).where(MonitorTrial.camera_id==identity,MonitorTrial.state=="running")):
                    prior.state="reconfigured";prior.ended_at=utcnow()
                    if identity in service.metrics:
                        prior.report=service.metrics[identity].report()
                if payload.enabled and payload.trial_minutes is not None:
                    db.add(MonitorTrial(camera_id=identity,owner_id=owner.id,revision=m.revision,
                        deadline=utcnow()+timedelta(minutes=payload.trial_minutes),evidence_hours=payload.evidence_hours,
                        report={"configured_interval_seconds":payload.interval_seconds,
                                "source":"국토교통부 국가교통정보센터(ITS)",
                                "model_sha256":app.state.detector.model_hash,
                                "base_policy_sha256":app.state.detector.policy_hash}))
                db.add(AuditLog(owner_id=owner.id,action="monitor.configured",target_id=identity))
                db.commit()
                response=service.status(m)
            service.gate.reset(identity);service.anchors.pop(identity,None)
            if identity in service.tasks:
                service.tasks[identity].cancel()
            return response

    @app.post("/api/monitoring/{camera_id}/stop")
    async def stop(camera_id:str,owner=Depends(user)):
        lock=service.revision_locks.setdefault(camera_id,asyncio.Lock())
        async with lock:
            with sessions() as db:
                m=db.get(Monitor,camera_id)
                if not m or m.owner_id!=owner.id:
                    raise HTTPException(404,"감시 설정을 찾을 수 없습니다.")
                m.enabled=False;m.revision+=1
                for trial in db.scalars(select(MonitorTrial).where(MonitorTrial.camera_id==camera_id,MonitorTrial.state=="running")):
                    trial.state="stopped";trial.ended_at=utcnow()
                    if camera_id in service.metrics:
                        trial.report=service.metrics[camera_id].report()
                db.add(AuditLog(owner_id=owner.id,action="monitor.stopped",target_id=camera_id))
                db.commit()
            if camera_id in service.tasks:
                service.tasks[camera_id].cancel()
            service.gate.reset(camera_id);previews.pop(camera_id,None)
        return {"ok":True}

    @app.put("/api/monitoring/{camera_id}/calibration")
    async def calibrate(camera_id:str,payload:CalibrationInput,owner=Depends(user)):
        with sessions() as db:
            m=db.get(Monitor,camera_id)
            if not m or m.owner_id!=owner.id:
                raise HTTPException(404,"감시 설정을 찾을 수 없습니다.")
            if m.enabled:
                raise HTTPException(409,"보정 변경 전 상시 감시를 중지하세요.")
        preview=service.references.get(camera_id)
        if not preview or time.monotonic()-preview["stamp"]>900 or preview["revision"]!=m.revision:
            raise HTTPException(409,"기준 프레임이 없거나 만료/설정 변경됐습니다. 기준 프레임을 다시 고정하세요.")
        if payload.reference_sha256!=preview["sha256"]:
            raise HTTPException(409,"화면에서 고정한 기준 프레임과 보정 입력이 다릅니다.")
        try:
            calibration=await asyncio.to_thread(fit_calibration,payload,preview["data"])
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from None
        with sessions() as db:
            m=db.get(Monitor,camera_id)
            if m.enabled or m.revision!=preview["revision"]:
                raise HTTPException(409,"감시 설정이 변경됐습니다.")
            m.calibration=calibration;m.revision+=1;m.auto_spread=False
            db.add(AuditLog(owner_id=owner.id,action="monitor.calibrated",target_id=camera_id))
            db.commit()
        return {"sha256":calibration["sha256"],"max_check_error_m":calibration["max_check_error_m"],
                "uncertainty_m":calibration["uncertainty_m"],"research_only":True}

    @app.post("/api/monitoring/{camera_id}/reference")
    def capture_reference(camera_id:str,owner=Depends(user)):
        with sessions() as db:
            m=db.get(Monitor,camera_id)
            if not m or m.owner_id!=owner.id:
                raise HTTPException(404,"감시 설정을 찾을 수 없습니다.")
            if m.enabled:
                raise HTTPException(409,"기준 프레임 고정 전 상시 감시를 중지하세요.")
            revision=m.revision
        preview=previews.get(camera_id)
        if not preview or time.monotonic()-preview[0]>30:
            raise HTTPException(409,"최근 분석 프레임이 없습니다. 허용된 2분 테스트 후 고정하세요.")
        for key,value in list(service.references.items()):
            if time.monotonic()-value["stamp"]>900:
                service.references.pop(key,None)
        if camera_id not in service.references and len(service.references)>=64:
            raise HTTPException(429,"기준 프레임 보관 한도입니다. 만료 후 다시 시도하세요.")
        sha=hashlib.sha256(preview[1]).hexdigest()
        service.references[camera_id]={"stamp":time.monotonic(),"data":preview[1],"sha256":sha,"revision":revision}
        return {"sha256":sha,"expires_seconds":900,"url":f"/api/monitoring/{camera_id}/reference"}

    @app.get("/api/monitoring/{camera_id}/reference")
    def reference(camera_id:str,owner=Depends(user)):
        with sessions() as db:
            m=db.get(Monitor,camera_id)
            if not m or m.owner_id!=owner.id:
                raise HTTPException(404)
        ref=service.references.get(camera_id)
        if not ref or time.monotonic()-ref["stamp"]>900:
            raise HTTPException(404,"기준 프레임이 만료됐습니다.")
        return Response(ref["data"],media_type="image/jpeg")

    @app.get("/api/events/{event_id}/location")
    def location(event_id:str,owner=Depends(user)):
        with sessions() as db:
            owned_alert(db,event_id,owner)
            saved=db.get(IncidentLocation,event_id)
            return {"estimate":saved.estimate if saved else {"available":False,"reason":"자동 추정 기록 없음"},
                    "simulation_id":saved.simulation_id if saved else None,
                    "status":saved.status if saved else "unavailable","message":saved.message if saved else ""}

    @app.put("/api/events/{event_id}/review")
    def review(event_id:str,payload:ReviewInput,owner=Depends(user)):
        with sessions() as db:
            owned_alert(db,event_id,owner)
            r=db.get(AlertReview,event_id)
            if not r:
                r=AlertReview(event_id=event_id,owner_id=owner.id,**payload.model_dump());db.add(r)
            else:
                r.outcome=payload.outcome;r.reason=payload.reason;r.updated_at=utcnow()
            db.add(AuditLog(owner_id=owner.id,action="alert.reviewed",target_id=event_id))
            db.commit()
        return {"ok":True}

    @app.get("/api/reviews")
    def reviews(owner=Depends(user)):
        from .models import Alert
        with sessions() as db:
            rows=list(db.scalars(select(AlertReview).where(AlertReview.owner_id==owner.id)))
            items=[]
            for r in rows:
                event=db.get(Alert,r.event_id)
                items.append({"event_id":r.event_id,"outcome":r.outcome,"reason":r.reason,
                              "camera_id":event.camera_id,"created_at":event.created_at.isoformat(),
                              "model_sha256":event.model_sha256,"policy_sha256":event.policy_sha256,
                              "snapshot_url":f"/api/events/{event.id}/snapshot" if event.snapshot_key else None,
                              "detections":event.detections})
            return {"items":items,"warning":"사람의 검토 기록입니다. 자동 학습·라벨 수정·실제 미탐률 계산이 아닙니다."}
    return service

def url_host(url):
    from urllib.parse import urlsplit
    return urlsplit(url).hostname.lower()
