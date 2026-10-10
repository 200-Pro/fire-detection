import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import timedelta
import logging
import hashlib
import secrets
import time
from urllib.parse import urlparse
from fastapi import FastAPI, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy import select, func, update, delete
from .config import Settings
from .db import Base, make_database
from .models import User, Camera, Alert, LoginSession, AuditLog, utcnow
from .security import COOKIE, digest, hash_password, verify_password, aware, RateLimiter
from .schemas import LoginInput, PasswordInput, CameraInput, CameraUpdate, PairInput, AlertUpdate
from .alerts import AlarmGate
from .hub import EventHub
from .detector import YoloDetector
from .storage import EvidenceStore
from .spread.routes import register_spread_routes
from .providers import register_provider_routes
from .monitoring import register_monitor_routes, apply_rules, filtered_preview
from .models import Monitor, MonitorTrial

log = logging.getLogger("ember")

def create_app(settings=None, detector=None):
    cfg = settings or Settings.from_env()
    cfg.storage_path.parent.mkdir(parents=True, exist_ok=True)
    engine, sessions = make_database(cfg.database_url)
    model = detector or YoloDetector(cfg)
    hub, limiter, gate = EventHub(), RateLimiter(), AlarmGate(cfg)
    previews, busy = {}, set()
    jobs = set()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="yolo")
    store = EvidenceStore(cfg)
    started = time.monotonic()

    @asynccontextmanager
    async def lifespan(app):
        hub.bind_loop(asyncio.get_running_loop())
        spread.startup()
        if cfg.environment != "production":
            Base.metadata.create_all(engine)
        with sessions() as db:
            if not db.scalar(select(User).where(User.name==cfg.admin_name)):
                db.add(User(name=cfg.admin_name, password_hash=hash_password(cfg.admin_password)))
                db.commit()
        await asyncio.to_thread(model.load)
        if not model.ready:
            log.error("Detector not ready: %s", model.error)
        monitoring.start()
        yield
        await monitoring.close()
        if jobs:
            await asyncio.gather(*tuple(jobs), return_exceptions=True)
        await spread.shutdown()
        await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)
        engine.dispose()

    app = FastAPI(title="Ember Fire Monitoring API", version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs" if cfg.environment!="production" else None,
                  redoc_url=None, openapi_url="/api/openapi.json" if cfg.environment!="production" else None)
    app.state.settings, app.state.sessions, app.state.detector = cfg, sessions, model
    app.state.store, app.state.gate = store, gate
    hostname = urlparse(cfg.public_origin).hostname or "localhost"
    allowed_hosts={hostname,"localhost","127.0.0.1","testserver"} if cfg.environment!="production" else {hostname}
    allowed_origins = {cfg.public_origin.rstrip("/")}
    if cfg.environment != "production" and cfg.local_console_enabled:
        # LAN camera uses HTTPS, while the operator may keep a loopback-only
        # localhost console. Never enable this exception for production.
        allowed_origins.add("http://localhost:5173")

    @app.middleware("http")
    async def security_headers(request, call_next):
        # ALB/container health probes use the target IP as Host. Only the two
        # minimal health endpoints bypass host validation; application routes do not.
        if request.url.path not in ("/health/live","/health/ready") and request.url.hostname not in allowed_hosts:
            return Response("Host not allowed",status_code=400)
        origin = request.headers.get("origin")
        if request.method not in ("GET","HEAD","OPTIONS"):
            if origin and origin.rstrip("/") not in allowed_origins:
                return Response("Origin not allowed", status_code=403)
            if request.cookies.get(COOKIE) and request.headers.get("x-ember-client")!="web" and not request.headers.get("authorization"):
                return Response("Missing CSRF request header", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        return response

    def session_user(token):
        if not token:
            return None
        with sessions() as db:
            session = db.get(LoginSession, digest(token))
            if not session or aware(session.expires_at) <= utcnow():
                return None
            return db.get(User, session.user_id)

    def user(request: Request):
        result = session_user(request.cookies.get(COOKIE))
        if not result:
            raise HTTPException(401, "로그인이 필요합니다.")
        return result

    def owned_camera(db, camera_id, owner):
        camera = db.get(Camera, camera_id)
        if not camera or camera.owner_id != owner.id or camera.archived_at is not None:
            raise HTTPException(404, "카메라를 찾을 수 없습니다.")
        return camera

    def owned_alert(db, event_id, owner):
        alert = db.get(Alert,event_id)
        if not alert or alert.owner_id != owner.id:
            raise HTTPException(404, "알람을 찾을 수 없습니다.")
        return alert

    def spread_event_lookup(event_id, owner):
        with sessions() as db:
            return owned_alert(db, event_id, owner)

    spread = register_spread_routes(app, cfg, user, spread_event_lookup)
    providers = register_provider_routes(app, user, limiter)

    def camera_data(camera):
        age = (utcnow()-aware(camera.last_seen)).total_seconds() if camera.last_seen else 1e12
        state=monitoring.states.get(camera.id,{}) if camera.kind=='its' else {}
        if camera.kind=='its':
            with sessions() as db:
                configured=db.get(Monitor,camera.id)
                if not configured or not configured.enabled:
                    state={'state':'stopped','message':'상시 분석 중지 · 공공 CCTV에서 감시 시험을 시작하세요.'}
        online = camera.enabled and age < (30 if camera.kind=='its' else 12)
        if state.get('state') in ('backoff','stale','stopped','capacity_blocked','approval_required'):
            online=False
        cached=previews.get(camera.id)
        has_preview=cached is not None and time.monotonic()-cached[0]<300
        return {"id":camera.id,"name":camera.name,"location":camera.location,"kind":camera.kind,
                "enabled":camera.enabled,"online":online,"signal":camera.last_signal if online else "offline",
                "last_seen":aware(camera.last_seen).isoformat() if camera.last_seen else None,
                "frames":camera.frames,"latency_ms":camera.latency_ms,
                "preview_url":f"/api/cameras/{camera.id}/preview" if has_preview else None,
                "preview_stale":has_preview and not online,
                "monitor_state":state.get('state'),"monitor_message":state.get('message'),
                "archived_at":aware(camera.archived_at).isoformat() if camera.archived_at else None}

    def alert_data(alert):
        with sessions() as db:
            camera=db.get(Camera,alert.camera_id)
            location=camera.location if camera else ''
        return {"id":alert.id,"camera_id":alert.camera_id,"camera_name":alert.camera_name,"kind":alert.kind,
                "state":alert.state,"created_at":aware(alert.created_at).isoformat(),"confidence":alert.confidence,
                "model_sha256":alert.model_sha256,"policy_sha256":alert.policy_sha256,"detections":alert.detections,
                "snapshot_url":f"/api/events/{alert.id}/snapshot" if alert.snapshot_key else None,"note":alert.note,
                "candidate_label":alert.candidate_label,"camera_location":location}

    def pair_camera(db, camera):
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
        camera.pair_hash = digest(code)
        camera.pair_expires = utcnow()+timedelta(minutes=10)
        db.commit()
        return {"camera_id":camera.id,"code":code,"expires_at":camera.pair_expires.isoformat(),
                "url":cfg.public_origin.rstrip("/")+"/camera?code="+code}

    def publisher(request, camera_id):
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise HTTPException(401,"카메라 전송 키가 필요합니다.")
        with sessions() as db:
            camera = db.get(Camera,camera_id)
            if (not camera or not camera.enabled or not camera.publisher_hash
                or not secrets.compare_digest(camera.publisher_hash,digest(authorization[7:]))
                or not camera.publisher_expires or aware(camera.publisher_expires)<=utcnow()):
                raise HTTPException(401,"카메라 키가 만료되었거나 연결이 해제되었습니다.")
            return camera

    async def process_frame(camera, data, publisher_hash=None, monitor=None):
        if not model.ready:
            raise HTTPException(503,"모델이 준비되지 않았습니다.")
        if camera.id in busy or len(busy)>=cfg.max_cameras:
            raise HTTPException(429,"추론 중입니다. 다음 프레임에서 재시도하세요.")
        busy.add(camera.id)
        task = asyncio.create_task(run_frame(camera, data, publisher_hash, monitor))
        jobs.add(task)

        def finished(job):
            jobs.discard(job)
            # Retrieve background failures if the client disconnected mid-frame.
            if not job.cancelled():
                job.exception()

        task.add_done_callback(finished)
        # Disconnecting a client must not release capacity while CPU inference
        # is still running, nor abandon an alarm already committed to the DB.
        return await asyncio.shield(task)

    async def run_frame(camera, data, publisher_hash, monitor=None):
        try:
            try:
                result = await asyncio.get_running_loop().run_in_executor(executor,model.predict,data)
            except ValueError as exc:
                raise HTTPException(422,str(exc)) from exc
            except Exception as exc:
                log.exception("Frame inference failed for %s",camera.id)
                raise HTTPException(503,"이미지 추론에 실패했습니다. 모델 상태를 확인하세요.") from exc
            event_data = None
            target_gate = monitoring.gate if monitor else gate
            if monitor:
                result = apply_rules(result, monitor.rules)
                result["jpeg"] = await asyncio.to_thread(filtered_preview,data,result,cfg)
                if monitoring.spatial_reset(monitor, result):
                    target_gate.reset(camera.id)
                if monitoring.spatial_reset(monitor, result,'smoke'):
                    target_gate.reset(camera.id+':smoke')
            with target_gate.lock, sessions() as db:
                if monitor and not monitoring.current(camera.id,monitor.revision):
                    raise HTTPException(409,"감시 시험이 종료되었거나 설정이 변경되었습니다.")
                condition = [Camera.id == camera.id, Camera.enabled.is_(True)]
                if monitor:
                    condition.append(select(Monitor.camera_id).where(
                        Monitor.camera_id == camera.id, Monitor.enabled.is_(True),
                        Monitor.revision == monitor.revision).exists())
                if publisher_hash:
                    condition.extend([Camera.publisher_hash == publisher_hash, Camera.publisher_expires > utcnow()])
                changed = db.execute(update(Camera).where(*condition).values(
                    last_seen=utcnow(), frames=Camera.frames+1, latency_ms=result["latency_ms"],
                    last_signal="fire" if result["fire_candidate"] else "smoke" if result["smoke_candidate"] else "clear"))
                if changed.rowcount != 1:
                    raise HTTPException(409,"추론 중 카메라 연결이 해제되었습니다.")
                current = db.get(Camera,camera.id)
                next_state, temporal = target_gate.propose(camera.id,result["fire_candidate"],time.monotonic())
                smoke_candidate=any(d['label']=='smoke' and d['score']>=.5 for d in result['detections'])
                smoke_state, smoke_temporal=target_gate.propose(camera.id+':smoke',smoke_candidate,time.monotonic())
                label='fire' if temporal['trigger'] else 'smoke'
                triggered=temporal['trigger'] or smoke_temporal['trigger']
                if triggered:
                    alert = Alert(owner_id=current.owner_id,camera_id=current.id,camera_name=current.name,
                                  kind="demo" if current.kind=="sample" else "live",
                                  candidate_label=label,
                                  confidence=max(d["score"] for d in result["detections"] if d["label"]==label),
                                  model_sha256=model.model_hash,policy_sha256=monitoring.policy_hash(monitor,model.policy_hash) if monitor else
                                  hashlib.sha256((model.policy_hash+':fire_smoke_temporal_v2:smoke_min_0.5').encode()).hexdigest(),
                                  detections=result["detections"])
                    db.add(alert)
                db.commit()
                target_gate.commit(camera.id, next_state)
                target_gate.commit(camera.id+':smoke',smoke_state)
                if triggered:
                    event_data = alert_data(alert)
                live = camera_data(current)
            # The alarm exists before evidence I/O. Never hold a SQLite write
            # transaction across await: acknowledgement and other cameras remain usable.
            if event_data:
                hub.publish(camera.owner_id,{"type":"alert.created","event":event_data})
                key, note = None, ""
                try:
                    key = await asyncio.to_thread(store.put,event_data["id"],result["jpeg"])
                except Exception:
                    log.exception("Evidence write failed; alert persisted without snapshot")
                    note = "증거 사진 저장 실패. 서버 로그를 확인하세요."
                with sessions() as db:
                    saved = db.get(Alert,event_data["id"])
                    saved.snapshot_key = key
                    if note:
                        saved.note = note
                    db.commit()
                    event_data = alert_data(saved)
                hub.publish(camera.owner_id,{"type":"alert.updated","event":event_data})
                if monitor:
                    monitoring.alert_created(monitor, event_data, result, data)
            with sessions() as db:
                latest = db.get(Camera,camera.id)
                still_connected = latest and latest.enabled and (not publisher_hash or latest.publisher_hash == publisher_hash)
                if still_connected:
                    previews[camera.id] = (time.monotonic(),result["jpeg"])
                    live = camera_data(latest)
            # Avoid retaining preview bytes for disconnected cameras indefinitely.
            for key,(stamp,_) in list(previews.items()):
                if time.monotonic()-stamp>300:
                    previews.pop(key,None)
            if still_connected:
                hub.publish(camera.owner_id,{"type":"camera.frame","camera":live})
            return {**{k:v for k,v in result.items() if k!="jpeg"},"camera_id":camera.id,
                    "temporal":temporal,"smoke_temporal":smoke_temporal,"event":event_data}
        finally:
            busy.discard(camera.id)

    @app.get("/health/live")
    def live():
        return {"status":"alive"}

    @app.get("/health/ready")
    def ready(response: Response):
        with sessions() as db:
            db.execute(select(1))
        if not model.ready:
            response.status_code=503
        return {"ready":model.ready}

    @app.post("/api/auth/login")
    def login(payload: LoginInput,request: Request,response: Response):
        limiter.check("login:"+(request.client.host if request.client else "unknown"),10,60)
        with sessions() as db:
            member = db.scalar(select(User).where(User.name==payload.username))
            if not member or not verify_password(payload.password,member.password_hash):
                raise HTTPException(401,"아이디 또는 비밀번호가 맞지 않습니다.")
            token = secrets.token_urlsafe(32)
            db.add(LoginSession(token_hash=digest(token),user_id=member.id,expires_at=utcnow()+timedelta(hours=cfg.session_hours)))
            db.commit()
        response.set_cookie(COOKIE,token,httponly=True,secure=cfg.secure_cookie,samesite="lax",max_age=cfg.session_hours*3600,path="/")
        return {"username":member.name}

    @app.get("/api/auth/me")
    def me(owner=Depends(user)):
        return {"username":owner.name}

    @app.post("/api/auth/password")
    def change_password(payload: PasswordInput, request: Request, owner=Depends(user)):
        limiter.check("password:"+owner.id,5,60)
        if len(payload.new_password)<16 or payload.new_password=="fire-demo-local":
            raise HTTPException(422,"다른 서비스와 겹치지 않는 16자 이상 비밀번호를 사용하세요.")
        with sessions() as db:
            member=db.get(User,owner.id)
            previous=member.password_hash
            if not verify_password(payload.current_password,previous):
                raise HTTPException(401,"현재 비밀번호가 맞지 않습니다.")
            if verify_password(payload.new_password,previous):
                raise HTTPException(422,"현재 비밀번호와 다른 값을 입력하세요.")
            changed=db.execute(update(User).where(User.id==owner.id,User.password_hash==previous).values(
                password_hash=hash_password(payload.new_password)))
            if changed.rowcount!=1:
                raise HTTPException(409,"비밀번호가 이미 변경되었습니다. 다시 로그인하세요.")
            db.execute(delete(LoginSession).where(LoginSession.user_id==owner.id,
                LoginSession.token_hash!=digest(request.cookies.get(COOKIE,""))))
            db.add(AuditLog(owner_id=owner.id,action="password.changed",target_id=owner.id))
            db.commit()
        return {"ok":True}

    @app.post("/api/auth/logout")
    def logout(request: Request,response: Response,owner=Depends(user)):
        with sessions() as db:
            saved = db.get(LoginSession,digest(request.cookies.get(COOKIE,"")))
            if saved:
                db.delete(saved)
                db.commit()
        response.delete_cookie(COOKIE,path="/")
        return {"ok":True}

    @app.get("/api/system")
    def system(owner=Depends(user)):
        return {"name":"Ember","version":"1.0.0","environment":cfg.environment,"model":model.info,
                "demo_enabled":cfg.demo_enabled,"public_origin":cfg.public_origin,"uptime_seconds":round(time.monotonic()-started),
                "alarm":{"hits":cfg.alarm_hits,"window":cfg.alarm_window,"min_seconds":cfg.alarm_min_seconds,
                         "cooldown_seconds":cfg.alarm_cooldown_seconds},
                "database":"PostgreSQL" if cfg.database_url.startswith("postgresql") else "SQLite (local)",
                "deployment_mode":"single-process","inflight":len(busy),"max_cameras":cfg.max_cameras}

    @app.get("/api/cameras")
    def cameras(owner=Depends(user)):
        with sessions() as db:
            return [camera_data(c) for c in db.scalars(select(Camera).where(Camera.owner_id==owner.id,Camera.archived_at.is_(None)).order_by(Camera.created_at))]

    @app.get('/api/cameras/archived')
    def archived_cameras(owner=Depends(user)):
        with sessions() as db:
            return [camera_data(c) for c in db.scalars(select(Camera).where(Camera.owner_id==owner.id,Camera.archived_at.is_not(None)).order_by(Camera.archived_at.desc()))]

    @app.post('/api/cameras/{camera_id}/archive')
    async def archive_camera(camera_id:str,owner=Depends(user)):
        lock=monitoring.revision_locks.setdefault(camera_id,asyncio.Lock())
        async with lock:
            with sessions() as db:
                camera=owned_camera(db,camera_id,owner)
                if camera.kind=='sample': raise HTTPException(409,'예제 카메라는 제거 대상이 아닙니다.')
                camera.archived_at=utcnow();camera.enabled=False
                camera.publisher_hash=camera.pair_hash=None
                camera.publisher_expires=camera.pair_expires=None
                m=db.get(Monitor,camera_id)
                if m:
                    for trial in db.scalars(select(MonitorTrial).where(MonitorTrial.camera_id==camera_id,MonitorTrial.state=='running')):
                        trial.state='archived';trial.ended_at=utcnow()
                        if camera_id in monitoring.metrics and monitoring.metrics_revisions.get(camera_id)==trial.revision:
                            trial.report=monitoring.metrics[camera_id].report()
                    m.enabled=False;m.revision+=1
                db.add(AuditLog(owner_id=owner.id,action='camera.archived',target_id=camera_id))
                db.commit()
            if camera_id in monitoring.tasks: monitoring.tasks[camera_id].cancel()
            gate.reset(camera_id);monitoring.gate.reset(camera_id);previews.pop(camera_id,None)
            monitoring.anchors.pop(camera_id,None)
        hub.publish(owner.id,{'type':'camera.updated','camera_id':camera_id})
        return {'ok':True,'history_preserved':True}

    @app.post('/api/cameras/{camera_id}/restore')
    def restore_camera(camera_id:str,owner=Depends(user)):
        with sessions() as db:
            camera=db.get(Camera,camera_id)
            if not camera or camera.owner_id!=owner.id: raise HTTPException(404,'카메라를 찾을 수 없습니다.')
            if camera.archived_at is None: raise HTTPException(409,'제거된 카메라가 아닙니다.')
            count=db.scalar(select(func.count()).select_from(Camera).where(Camera.owner_id==owner.id,Camera.kind!='sample',Camera.archived_at.is_(None)))
            if count>=cfg.max_cameras: raise HTTPException(409,'카메라 등록 한도입니다.')
            camera.archived_at=None;camera.enabled=False
            db.add(AuditLog(owner_id=owner.id,action='camera.restored',target_id=camera_id));db.commit()
        hub.publish(owner.id,{'type':'camera.updated','camera_id':camera_id})
        return {'ok':True,'enabled':False}

    @app.get('/api/cameras/{camera_id}/stream')
    async def camera_stream(camera_id:str,owner=Depends(user)):
        with sessions() as db:
            camera=owned_camera(db,camera_id,owner);m=db.get(Monitor,camera_id)
            if camera.kind!='its' or not m: raise HTTPException(409,'공공 CCTV 재생 설정이 없습니다.')
            road,video_type,catalog_id=m.road,m.video_type,m.catalog_id
        limiter.check('stream:'+owner.id,20,60)
        catalog=await providers.catalog(road,video_type)
        item=next((i for i in catalog['items'] if i['id']==catalog_id),None)
        if not item: raise HTTPException(404,'제공기관 목록에 없는 CCTV입니다.')
        return {'url':item['url'],'video_type':video_type,'name':item['name']}

    @app.post("/api/cameras",status_code=201)
    def create_camera(payload: CameraInput,owner=Depends(user)):
        if not payload.name.strip():
            raise HTTPException(422,"카메라 이름을 입력하세요.")
        with sessions() as db:
            count = db.scalar(select(func.count()).select_from(Camera).where(Camera.owner_id==owner.id,Camera.kind!="sample",Camera.archived_at.is_(None)))
            if count>=cfg.max_cameras:
                raise HTTPException(409,"프로토타입의 카메라 등록 한도에 도달했습니다.")
            camera = Camera(owner_id=owner.id,name=payload.name.strip(),location=payload.location.strip(),kind=payload.kind)
            db.add(camera)
            db.commit()
            pair = pair_camera(db,camera)
            db.add(AuditLog(owner_id=owner.id,action="camera.created",target_id=camera.id))
            db.commit()
            return {"camera":camera_data(camera),"pairing":pair}

    @app.post("/api/cameras/{camera_id}/pairing")
    def pairing(camera_id:str,owner=Depends(user)):
        with sessions() as db:
            camera = owned_camera(db,camera_id,owner)
            if not camera.enabled or camera.kind in ("sample","its"):
                raise HTTPException(409,"이 카메라에는 연결 코드를 발급할 수 없습니다.")
            return pair_camera(db,camera)

    @app.patch("/api/cameras/{camera_id}")
    def update_camera(camera_id:str,payload:CameraUpdate,owner=Depends(user)):
        with sessions() as db:
            camera = owned_camera(db,camera_id,owner)
            camera.enabled = payload.enabled
            if not payload.enabled:
                camera.publisher_hash, camera.pair_hash = None,None
                camera.last_seen, camera.last_signal = None,"offline"
            db.add(AuditLog(owner_id=owner.id,action="camera.enabled" if payload.enabled else "camera.disabled",target_id=camera_id))
            db.commit()
            result = camera_data(camera)
        if not payload.enabled:
            gate.reset(camera_id)
            previews.pop(camera_id,None)
        hub.publish(owner.id,{"type":"camera.updated","camera":result})
        return result

    @app.post("/api/publisher/pair")
    def exchange_pair(payload:PairInput,request:Request):
        limiter.check("pair:"+(request.client.host if request.client else "unknown"),10,60)
        with sessions() as db:
            token = secrets.token_urlsafe(32)
            expires = utcnow()+timedelta(hours=24)
            # A single conditional UPDATE consumes the code atomically even
            # when two phones submit it at the same instant.
            consumed = db.execute(update(Camera).where(
                Camera.pair_hash == digest(payload.code), Camera.enabled.is_(True),
                Camera.pair_expires > utcnow()).values(
                publisher_hash=digest(token), publisher_expires=expires,
                pair_hash=None, pair_expires=None))
            if consumed.rowcount != 1:
                raise HTTPException(401,"연결 코드가 만료되었거나 이미 사용되었습니다.")
            db.commit()
            camera = db.scalar(select(Camera).where(Camera.publisher_hash == digest(token)))
            return {"camera_id":camera.id,"name":camera.name,"token":token,"expires_at":expires.isoformat()}

    @app.post("/api/publisher/{camera_id}/frames")
    async def frames(camera_id:str,request:Request):
        camera=publisher(request,camera_id)
        limiter.check("frame:"+camera_id,4,1)
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>cfg.max_frame_bytes:
                raise HTTPException(413,"프레임 크기는 2MB 이하여야 합니다.")
        return await process_frame(camera,bytes(data),camera.publisher_hash)

    @app.post("/api/publisher/{camera_id}/stop")
    def stop_publisher(camera_id:str,request:Request):
        camera=publisher(request,camera_id)
        with sessions() as db:
            changed = db.execute(update(Camera).where(Camera.id==camera_id, Camera.publisher_hash==camera.publisher_hash).values(
                publisher_hash=None, publisher_expires=None, last_seen=None, last_signal="offline"))
            if changed.rowcount != 1:
                raise HTTPException(401,"카메라 전송 키가 이미 변경되었습니다.")
            db.commit()
        gate.reset(camera_id)
        previews.pop(camera_id,None)
        hub.publish(camera.owner_id,{"type":"camera.updated","camera_id":camera_id})
        return {"ok":True}

    @app.get("/api/cameras/{camera_id}/preview")
    def preview(camera_id:str,owner=Depends(user)):
        with sessions() as db:
            owned_camera(db,camera_id,owner)
        data=previews.get(camera_id)
        if not data or time.monotonic()-data[0]>300:
            raise HTTPException(404,"최근 프레임이 없습니다.")
        return Response(data[1],media_type="image/jpeg")

    @app.post("/api/cctv/{identity}/register")
    def register_cctv(identity: str, owner=Depends(user)):
        item = providers.find(identity)
        camera_id = digest(owner.id + ":its:" + identity)[:32]
        with sessions() as db:
            camera = db.get(Camera, camera_id)
            if camera and camera.archived_at is not None:
                raise HTTPException(409,'제거된 카메라입니다. 카메라 관리에서 먼저 복원하세요.')
            if not camera:
                if db.scalar(select(func.count()).select_from(Camera).where(Camera.owner_id==owner.id, Camera.kind!="sample",Camera.archived_at.is_(None))) >= cfg.max_cameras:
                    raise HTTPException(409,"카메라 등록 한도에 도달했습니다.")
                camera = Camera(id=camera_id, owner_id=owner.id, name=item["name"], kind="its",
                                location=f'ITS 설치 좌표 {item["latitude"]:.6f}, {item["longitude"]:.6f} (발화점 아님)')
                db.add(camera)
                db.add(AuditLog(owner_id=owner.id, action="camera.its.register", target_id=camera_id))
                db.commit()
            if not db.get(Monitor,camera_id):
                db.add(Monitor(camera_id=camera_id,owner_id=owner.id,catalog_id=identity,
                               road=item['road'],video_type=item['video_type'],enabled=False))
                db.commit()
            return camera_data(camera)

    @app.post("/api/cctv/cameras/{camera_id}/frames")
    async def cctv_frames(camera_id: str, request: Request, owner=Depends(user)):
        with sessions() as db:
            camera = owned_camera(db, camera_id, owner)
            if camera.kind != "its" or not camera.enabled:
                raise HTTPException(409,"활성화한 ITS 카메라만 분석할 수 있습니다.")
            monitor = db.get(Monitor, camera_id)
            if monitor and monitor.enabled:
                raise HTTPException(409,"서버 상시 감시 중입니다. 브라우저 중복 분석 전 감시를 중지하세요.")
        limiter.check("frame:"+camera_id,2,1)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > cfg.max_frame_bytes:
                raise HTTPException(413,"프레임 크기는 2MB 이하여야 합니다.")
        return await process_frame(camera,bytes(data))

    @app.get("/api/events")
    def events(limit:int=50,before:str|None=None,state:str|None=None,owner=Depends(user)):
        if not 1<=limit<=100 or state not in (None,"new","acknowledged","resolved"):
            raise HTTPException(422,"잘못된 조회 조건입니다.")
        with sessions() as db:
            query=select(Alert).where(Alert.owner_id==owner.id)
            if before:
                prior=owned_alert(db,before,owner)
                from sqlalchemy import or_,and_
                query=query.where(or_(Alert.created_at<prior.created_at,and_(Alert.created_at==prior.created_at,Alert.id<prior.id)))
            if state:
                query=query.where(Alert.state==state)
            items=list(db.scalars(query.order_by(Alert.created_at.desc(),Alert.id.desc()).limit(limit+1)))
            return {"items":[alert_data(a) for a in items[:limit]],"next":items[limit-1].id if len(items)>limit else None}

    @app.get("/api/events/{event_id}/snapshot")
    async def snapshot(event_id:str,owner=Depends(user)):
        with sessions() as db:
            alert=owned_alert(db,event_id,owner)
            if not alert.snapshot_key:
                raise HTTPException(404,"저장된 사진이 없습니다.")
            key=alert.snapshot_key
        try:
            data=await asyncio.to_thread(store.get,key)
        except Exception as exc:
            raise HTTPException(404,"증거 사진을 불러올 수 없습니다.") from exc
        return Response(data,media_type="image/jpeg")

    @app.patch("/api/events/{event_id}")
    def update_event(event_id:str,payload:AlertUpdate,owner=Depends(user)):
        with sessions() as db:
            alert=owned_alert(db,event_id,owner)
            if alert.state=="resolved" and payload.state!="resolved":
                raise HTTPException(409,"종료한 알람은 다시 확인 상태로 바꿀 수 없습니다.")
            alert.state=payload.state
            if payload.state=="acknowledged":
                alert.acknowledged_at=utcnow()
            else:
                alert.resolved_at=utcnow()
            alert.note=payload.note or alert.note
            db.add(AuditLog(owner_id=owner.id,action="alert."+payload.state,target_id=alert.id))
            db.commit()
            result=alert_data(alert)
        hub.publish(owner.id,{"type":"alert.updated","event":result})
        return result

    @app.get("/api/stats")
    def stats(owner=Depends(user)):
        with sessions() as db:
            cs=list(db.scalars(select(Camera).where(Camera.owner_id==owner.id,Camera.kind!="sample",Camera.archived_at.is_(None))))
            active=db.scalar(select(func.count()).select_from(Alert).where(Alert.owner_id==owner.id,Alert.state!="resolved"))
            today=db.scalar(select(func.count()).select_from(Alert).where(Alert.owner_id==owner.id,Alert.created_at>=utcnow()-timedelta(hours=24)))
            latencies=[c.latency_ms for c in cs if camera_data(c)["online"] and c.latency_ms is not None]
            return {"cameras":len(cs),"online":sum(camera_data(c)["online"] for c in cs),
                    "unresolved":active,"events_24h":today,
                    "latency_ms":round(sum(latencies)/len(latencies),1) if latencies else None}

    @app.get("/api/samples/{name}")
    def sample(name:str,owner=Depends(user)):
        if not cfg.demo_enabled or name not in ("fire","clear"):
            raise HTTPException(404)
        path=cfg.samples_path/(name+".jpg")
        if not path.is_file():
            raise HTTPException(404,"샘플이 없습니다.")
        return Response(path.read_bytes(),media_type="image/jpeg")

    @app.post("/api/demo/frame")
    async def demo_frame(request:Request,name:str="fire",owner=Depends(user)):
        if not cfg.demo_enabled or name not in ("fire","clear"):
            raise HTTPException(404)
        limiter.check("demo:"+owner.id,4,1)
        with sessions() as db:
            camera=db.scalar(select(Camera).where(Camera.owner_id==owner.id,Camera.kind=="sample"))
            if not camera:
                camera=Camera(owner_id=owner.id,name="D-Fire 예제 · 실제 모델 추론",kind="sample",location="데모 데이터")
                db.add(camera)
                db.commit()
        path=cfg.samples_path/(name+".jpg")
        if not path.is_file():
            raise HTTPException(404,"샘플이 없습니다.")
        return await process_frame(camera,path.read_bytes())

    @app.websocket("/api/ws/events")
    async def websocket(websocket:WebSocket):
        origin=websocket.headers.get("origin")
        token=websocket.cookies.get(COOKIE)
        owner=session_user(token)
        if not owner or (origin and origin.rstrip("/") not in allowed_origins) or len(hub.clients)>=64:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        queue=hub.subscribe(owner.id)
        try:
            await websocket.send_json({"type":"connected"})
            while True:
                if not session_user(token):
                    await websocket.close(code=1008)
                    break
                try:
                    message=await asyncio.wait_for(queue.get(),timeout=15)
                except asyncio.TimeoutError:
                    message={"type":"heartbeat"}
                await websocket.send_json(message)
        except (WebSocketDisconnect,RuntimeError,OSError):
            pass
        finally:
            hub.remove(queue)
    monitoring = register_monitor_routes(app,cfg,user,sessions,providers,process_frame,spread,hub,previews,owned_alert)
    return app

app=create_app()
