import asyncio
from dataclasses import replace
from io import BytesIO
import socket
import time
import cv2
import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select
from test_api import fixture,login
from app.models import Alert,Monitor
from app.monitoring import Rules,apply_rules
from app.localization import CalibrationInput,fit_calibration,estimate_location,to_geo,stable_view
from app.stream_reader import safe_target,media_segment,StreamError,decode_segment

def catalog(app):
    from app.providers import Providers
    import httpx
    rows=[{"cctvname":str(i),"coordx":128.6+i*.01,"coordy":35.8,
           "cctvurl":f"https://video.example.org/{i}.m3u8"} for i in range(2)]
    app.state.providers.transport=httpx.MockTransport(lambda r:httpx.Response(200,json={"response":{"data":rows}}))

def test_approval_gate_and_disabled_configuration(fixture,monkeypatch):
    c,_,app,_=fixture
    monkeypatch.setenv("ITS_API_KEY","test-key");catalog(app);login(c)
    item=c.get("/api/cctv/catalog").json()["items"][0]
    assert c.put(f'/api/cctv/{item["id"]}/monitor',json={"enabled":True,"rights_confirmed":True,"approval_reference":"test approval"}).status_code==409
    r=c.put(f'/api/cctv/{item["id"]}/monitor',json={})
    assert r.status_code==200 and not r.json()["enabled"]
    assert c.get("/api/monitoring").json()["items"][0]["state"]=="stopped"
    assert c.put(f'/api/cctv/{item["id"]}/monitor',json={"auto_spread":True,"research_acknowledged":True}).status_code==422
    registered=c.post(f'/api/cctv/{item["id"]}/register').json()
    assert registered["id"]==r.json()["camera_id"]

def test_workers_analyze_two_cameras_without_player_and_stop(fixture,monkeypatch):
    c,detector,app,cfg=fixture
    cfg.cctv_ai_approved=True
    monkeypatch.setenv("ITS_API_KEY","test-key")
    monkeypatch.setenv("EMBER_STREAM_ALLOWED_HOSTS","video.example.org")
    catalog(app);login(c)
    svc=app.state.monitoring;svc.gate.settings.alarm_min_seconds=0
    counts={}
    def frames(identity,url):
        counts[identity]=counts.get(identity,0)+1
        out=BytesIO();Image.new("RGB",(64,64),(counts[identity]%250,120,0)).save(out,format="JPEG")
        return out.getvalue()
    monkeypatch.setattr(svc.reader,"read",frames)
    ids=[]
    for item in c.get("/api/cctv/catalog").json()["items"]:
        r=c.put(f'/api/cctv/{item["id"]}/monitor',json={"enabled":True,"rights_confirmed":True,
                   "approval_reference":"TEST INJECTION ONLY","interval_seconds":2})
        assert r.status_code==200
        ids.append(r.json()["camera_id"])
    deadline=time.monotonic()+12
    while time.monotonic()<deadline:
        with app.state.sessions() as db:
            alerts=list(db.scalars(select(Alert)))
        if len(alerts)==2:
            break
        time.sleep(.2)
    assert {a.camera_id for a in alerts}==set(ids)
    assert all(a.policy_sha256!=detector.policy_hash for a in alerts)
    for identity in ids:
        assert counts[identity]>=3
        assert c.post(f"/api/monitoring/{identity}/stop").status_code==200
    time.sleep(.3)
    before=counts.copy();time.sleep(2.2)
    assert counts==before
    assert all(not m["enabled"] for m in c.get("/api/monitoring").json()["items"])

def test_rules_and_spatial_persistence(fixture):
    _,_,app,_=fixture
    d={"label":"fire","score":.7,"box":[.1,.1,.1,.1]}
    result={"detections":[d],"fire_candidate":True,"smoke_candidate":False}
    assert not apply_rules(result,{"minimum_score":.8})["fire_candidate"]
    assert not apply_rules(result,{"ignore_polygons":[[[0,0],[.5,0],[.5,.5],[0,.5]]]})["fire_candidate"]
    m=Monitor(camera_id="x",rules={})
    assert not app.state.monitoring.spatial_reset(m,result)
    assert not app.state.monitoring.spatial_reset(m,result)
    shifted={**result,"detections":[{**d,"box":[.8,.8,.1,.1]}]}
    assert app.state.monitoring.spatial_reset(m,shifted)
    with pytest.raises(ValueError):
        Rules(ignore_polygons=[[[0,0],[1,1],[1,0],[0,1]]])

def calibration():
    image=np.random.default_rng(42).integers(0,256,(480,640),dtype=np.uint8)
    frame=cv2.imencode(".jpg",image)[1].tobytes()
    def point(x,y):
        lon,lat=to_geo.transform(1110000+x*500,1760000+y*500)
        return {"x":x,"y":y,"latitude":lat,"longitude":lon}
    payload=CalibrationInput(points=[point(.1,.1),point(.9,.1),point(.9,.9),point(.1,.9)],
                             checks=[point(.4,.4),point(.6,.6)],uncertainty_m=90,
                             fixed_planar_view_confirmed=True,reference_note="synthetic planar fixture")
    return payload,frame

def test_calibration_stable_view_and_abstention():
    p,frame=calibration();cal=fit_calibration(p,frame)
    assert cal["max_check_error_m"]<.1
    d={"label":"fire","score":.8,"box":[.4,.3,.2,.2]}
    r=estimate_location(cal,[d],frame)
    assert r["available"] and r["uncertainty_m"]==90
    assert not estimate_location(None,[d],frame)["available"]
    assert not estimate_location(cal,[{**d,"box":[.95,.95,.02,.02]}],frame)["available"]
    image=cv2.imdecode(np.frombuffer(frame,np.uint8),0)
    moved=cv2.warpAffine(image,np.float32([[1,0,25],[0,1,0]]),(640,480))
    assert not stable_view(cal,cv2.imencode(".jpg",moved)[1].tobytes())
    p.checks[0]=p.points[0]
    with pytest.raises(ValueError):
        fit_calibration(p,frame)

def test_safe_stream_dns_and_nested_manifest(monkeypatch):
    monkeypatch.setattr(socket,"getaddrinfo",lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,"",("127.0.0.1",443))])
    with pytest.raises(StreamError):
        safe_target("https://video.example.org/a",{"video.example.org"})
    monkeypatch.setattr(socket,"getaddrinfo",lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,"",("8.8.8.8",443))])
    assert safe_target("https://video.example.org/a",{"video.example.org"})[1]=="8.8.8.8"
    with pytest.raises(StreamError):
        safe_target("https://other.example.org/a",{"video.example.org"})
    assert media_segment("#EXTM3U\n#EXTINF:2,\nseg.ts","https://video.example.org/a")[1].endswith("/seg.ts")
    for tag in ("#EXT-X-KEY:METHOD=AES-128","#EXT-X-MAP:URI=foo","#EXT-X-ENDLIST"):
        with pytest.raises(StreamError):
            media_segment("#EXTM3U\n"+tag+"\n#EXTINF:2,\nseg.ts","https://video.example.org/a")

def test_real_pipe_decoder_no_network():
    import imageio_ffmpeg,subprocess
    binary=imageio_ffmpeg.get_ffmpeg_exe()
    result=subprocess.run([binary,"-hide_banner","-loglevel","error","-f","lavfi",
                          "-i","color=c=orange:s=160x120:r=2","-t","1",
                          "-c:v","mpeg2video","-f","mpegts","pipe:1"],
                         stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=10)
    frame=decode_segment(result.stdout)
    assert Image.open(BytesIO(frame)).format=="JPEG"

def test_review_and_location_require_owner(fixture):
    c,_,app,_=fixture;login(c)
    assert c.get("/api/events/"+("a"*32)+"/location").status_code==404
    assert c.put("/api/events/"+("a"*32)+"/review",json={"outcome":"false_alarm"}).status_code==404
    assert c.get("/api/reviews").json()["items"]==[]

def test_reference_capture_bound_to_frame_and_owner(fixture,monkeypatch):
    c,_,app,_=fixture
    monkeypatch.setenv("ITS_API_KEY","test-key");catalog(app);login(c)
    item=c.get("/api/cctv/catalog").json()["items"][0]
    m=c.put(f'/api/cctv/{item["id"]}/monitor',json={}).json()
    identity=m["camera_id"]
    assert c.post(f"/api/monitoring/{identity}/reference").status_code==409
    payload,frame=calibration()
    app.state.monitoring.previews[identity]=(time.monotonic(),frame)
    ref=c.post(f"/api/monitoring/{identity}/reference").json()
    assert c.get(f"/api/monitoring/{identity}/reference").content==frame
    bad=c.put(f"/api/monitoring/{identity}/calibration",json=payload.model_dump())
    assert bad.status_code==409
    payload.reference_sha256=ref["sha256"]
    assert c.put(f"/api/monitoring/{identity}/calibration",json=payload.model_dump()).status_code==200

def test_auto_location_missing_calibration_does_not_submit(fixture):
    _,_,app,_=fixture
    with app.state.sessions() as db:
        from app.models import User,Camera
        owner=db.scalar(select(User));camera=Camera(owner_id=owner.id,name="injection",kind="its")
        db.add(camera);db.flush()
        event=Alert(owner_id=owner.id,camera_id=camera.id,camera_name=camera.name,confidence=.8,
                    model_sha256="a"*64,policy_sha256="b"*64,detections=[])
        db.add(event);db.commit()
        m=Monitor(camera_id=camera.id,owner_id=owner.id,calibration=None,rules={},revision=1,auto_spread=True)
        asyncio.run(app.state.monitoring.locate_and_simulate(m,{"id":event.id},{"detections":[]},b""))
    with app.state.sessions() as db:
        from app.models import IncidentLocation
        row=db.get(IncidentLocation,event.id)
        assert not row.estimate["available"] and row.simulation_id is None

def test_calibrated_auto_spread_native_solver_and_dedup(fixture,monkeypatch):
    c,_,app,_=fixture
    svc=app.state.monitoring
    point=svc.spread.manifest()["default_ignition"]
    async def weather(*args):
        return {"available":True,"fresh":True,"source":"kma","temperature_c":20,"humidity_pct":40,
                "wind_speed_ms":3,"wind_from_deg":270,"rain_mm":0}
    monkeypatch.setattr(svc.spread.weather,"observation",weather)
    monkeypatch.setattr("app.monitoring.estimate_location",lambda *args:{
        "available":True,**point,"uncertainty_m":90,"research_only":True,"calibration_sha256":"synthetic"})
    with app.state.sessions() as db:
        from app.models import User,Camera,IncidentLocation
        owner=db.scalar(select(User));camera=Camera(owner_id=owner.id,name="synthetic-auto",kind="its")
        db.add(camera);db.flush()
        event=Alert(owner_id=owner.id,camera_id=camera.id,camera_name=camera.name,confidence=.8,
                    model_sha256="a"*64,policy_sha256="b"*64,detections=[])
        db.add(event)
        m=Monitor(camera_id=camera.id,owner_id=owner.id,catalog_id="x",road="ex",video_type=4,
                  enabled=True,calibration={},rules={},revision=1,auto_spread=True)
        db.add(m);db.commit()
    async def flow():
        await svc.locate_and_simulate(m,{"id":event.id},{"detections":[]},b"synthetic")
        await svc.locate_and_simulate(m,{"id":event.id},{"detections":[]},b"synthetic")
        if svc.spread.tasks:
            await asyncio.gather(*tuple(svc.spread.tasks))
    c.portal.call(flow)
    with app.state.sessions() as db:
        row=db.get(IncidentLocation,event.id)
        assert row.simulation_id is not None,row.message
        job=svc.spread.get_job(row.simulation_id,owner.id)
        assert job["state"]=="completed"
        assert job["request"]["location_source"]=="automatic_calibrated_estimate"
        assert job["context"]["location_estimate"]["uncertainty_m"]==90
        assert len(list(svc.spread.jobs_dir.glob("*/job.json")))==1

def test_stop_during_inference_prevents_late_alert(fixture):
    c,detector,app,_=fixture;login(c)
    from threading import Event
    from concurrent.futures import ThreadPoolExecutor
    from app.models import User,Camera
    entered,release=Event(),Event()
    original=detector.predict
    def blocked(data):
        entered.set();assert release.wait(5);return original(data)
    detector.predict=blocked
    with app.state.sessions() as db:
        owner=db.scalar(select(User));camera=Camera(owner_id=owner.id,name="test",kind="its")
        db.add(camera);db.flush()
        m=Monitor(camera_id=camera.id,owner_id=owner.id,catalog_id="x",road="ex",video_type=4,
                  enabled=True,rules={},revision=1)
        db.add(m);db.commit()
    out=BytesIO();Image.new("RGB",(64,64),"orange").save(out,format="JPEG")
    async def send():
        return await app.state.monitoring.process_frame(camera,out.getvalue(),monitor=m)
    with ThreadPoolExecutor() as pool:
        pending=pool.submit(c.portal.call,send)
        assert entered.wait(3)
        assert c.post(f"/api/monitoring/{camera.id}/stop").status_code==200
        release.set()
        with pytest.raises(HTTPException) as exc:
            pending.result(timeout=5)
        assert exc.value.status_code==409
    with app.state.sessions() as db:
        assert not list(db.scalars(select(Alert)))

def test_restart_configuration_fail_closed_without_approval(fixture):
    c,_,app,_=fixture;login(c)
    from app.models import User,Camera
    with app.state.sessions() as db:
        owner=db.scalar(select(User));camera=Camera(owner_id=owner.id,name="blocked",kind="its")
        db.add(camera);db.flush()
        m=Monitor(camera_id=camera.id,owner_id=owner.id,catalog_id="x",road="ex",video_type=4,
                  enabled=True,rules={},approval_reference="prior approval")
        db.add(m);db.commit()
    time.sleep(1.1)
    assert c.get("/api/monitoring").json()["items"][0]["state"]=="approval_required"
    assert not app.state.monitoring.tasks
