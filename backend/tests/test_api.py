from io import BytesIO
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from PIL import Image
from app.main import create_app
from app.config import Settings
from app.models import Camera,User,LoginSession,utcnow
from app.detector import decode_frame

class FakeDetector:
    def __init__(self,settings):
        self.settings=settings
        self.ready=True
        self.error=None
        self.fire=True
        self.model_hash='a'*64
        self.policy_hash='b'*64
        self.info={'ready':True,'name':'TEST INJECTION ONLY'}
    def load(self):
        pass
    def predict(self,data):
        image=decode_frame(data,self.settings)
        out=BytesIO();image.save(out,format='JPEG')
        detection={'class_id':1,'label':'fire','score':.8,'xyxy':[0,0,16,16],'box':[0,0,.25,.25]}
        return {'detections':[detection] if self.fire else [],'width':64,'height':64,
                'fire_candidate':self.fire,'smoke_candidate':False,'latency_ms':1,'jpeg':out.getvalue()}

@pytest.fixture
def fixture(tmp_path):
    settings=Settings(environment='testing',database_url=f'sqlite:///{tmp_path}/test.db',
                      storage_path=tmp_path/'evidence',samples_path=tmp_path/'samples',alarm_min_seconds=0,
                      max_cameras=2,spread_jobs_path=tmp_path/'spread-jobs')
    detector=FakeDetector(settings)
    app=create_app(settings,detector)
    with TestClient(app) as client:
        client.headers['X-Ember-Client']='web'
        yield client,detector,app,settings

def login(client):
    assert client.post('/api/auth/login',json={'username':'admin','password':'fire-demo-local'}).status_code==200

def connect(client):
    login(client)
    created=client.post('/api/cameras',json={'name':'테스트 카메라','location':'테스트'}).json()
    code=created['pairing']['code']
    p=client.post('/api/publisher/pair',json={'code':code})
    assert p.status_code==200
    return created,p.json()

def frame(client,p):
    data=BytesIO();Image.new('RGB',(64,64),'orange').save(data,format='JPEG')
    return client.post(f'/api/publisher/{p["camera_id"]}/frames',content=data.getvalue(),headers={'Authorization':'Bearer '+p['token']})

def test_auth_is_required_and_bad_password_rejected(fixture):
    client,*_=fixture
    assert client.get('/api/cameras').status_code==401
    assert client.post('/api/auth/login',json={'username':'admin','password':'wrong'}).status_code==401
    login(client)
    assert client.get('/api/auth/me').json()['username']=='admin'
    assert 'httponly' in client.cookies.get('ember_session','') or client.cookies.get('ember_session')
    assert client.post('/api/auth/logout').status_code==200
    assert client.get('/api/auth/me').status_code==401

def test_origin_and_csrf_header_are_checked(fixture):
    client,*_=fixture
    login(client)
    assert client.post('/api/cameras',json={'name':'x'},headers={'Origin':'https://evil.example'}).status_code==403
    client.headers.pop('X-Ember-Client')
    assert client.post('/api/cameras',json={'name':'x'}).status_code==403

def test_pairing_is_single_use_and_expired_codes_rejected(fixture):
    client,_,app,_=fixture
    created,p=connect(client)
    assert client.post('/api/publisher/pair',json={'code':created['pairing']['code']}).status_code==401
    code=client.post(f'/api/cameras/{p["camera_id"]}/pairing').json()['code']
    with app.state.sessions() as db:
        db.get(Camera,p['camera_id']).pair_expires=utcnow()-timedelta(seconds=1);db.commit()
    assert client.post('/api/publisher/pair',json={'code':code}).status_code==401

def test_expired_publisher_is_rejected(fixture):
    client,_,app,_=fixture
    _,p=connect(client)
    with app.state.sessions() as db:
        db.get(Camera,p['camera_id']).publisher_expires=utcnow()-timedelta(seconds=1);db.commit()
    assert frame(client,p).status_code==401

def test_three_frames_create_one_alert_and_evidence(fixture):
    client,detector,*_=fixture
    _,p=connect(client)
    assert frame(client,p).json()['event'] is None
    assert frame(client,p).json()['event'] is None
    event=frame(client,p).json()['event']
    assert event['kind']=='live' and event['state']=='new'
    assert frame(client,p).json()['event'] is None
    assert client.get('/api/events').json()['items'][0]['id']==event['id']
    evidence=client.get(event['snapshot_url'])
    assert evidence.status_code==200 and evidence.headers['content-type']=='image/jpeg'
    assert client.get('/api/stats').json()['unresolved']==1
    assert client.get(f'/api/cameras/{p["camera_id"]}/preview').status_code==200

def test_fire_absent_frame_does_not_alarm(fixture):
    client,detector,*_=fixture
    detector.fire=False
    _,p=connect(client)
    for _ in range(3):
        assert frame(client,p).json()['event'] is None
    assert client.get('/api/events').json()['items']==[]

def test_stop_and_disable_revoke_publisher(fixture):
    client,*_=fixture
    _,p=connect(client)
    assert client.post(f'/api/publisher/{p["camera_id"]}/stop',headers={'Authorization':'Bearer '+p['token']}).status_code==200
    assert frame(client,p).status_code==401
    assert client.patch(f'/api/cameras/{p["camera_id"]}',json={'enabled':False}).status_code==200
    assert client.post(f'/api/cameras/{p["camera_id"]}/pairing').status_code==409

def test_scoped_camera_token_cannot_read_dashboard(fixture):
    client,*_=fixture
    _,p=connect(client)
    client.cookies.clear()
    assert client.get('/api/events',headers={'Authorization':'Bearer '+p['token']}).status_code==401

def test_alert_ack_resolve_and_cannot_reopen(fixture):
    client,*_=fixture
    _,p=connect(client)
    for _ in range(3):
        response=frame(client,p)
    event=response.json()['event']
    path=f'/api/events/{event["id"]}'
    assert client.patch(path,json={'state':'acknowledged'}).json()['state']=='acknowledged'
    assert client.patch(path,json={'state':'resolved'}).json()['state']=='resolved'
    assert client.patch(path,json={'state':'acknowledged'}).status_code==409

def test_invalid_and_oversized_frames_are_rejected(fixture):
    client,*_=fixture
    _,p=connect(client)
    path=f'/api/publisher/{p["camera_id"]}/frames'
    headers={'Authorization':'Bearer '+p['token']}
    assert client.post(path,content=b'not an image',headers=headers).status_code==422
    assert client.post(path,content=b'0'*2_000_001,headers=headers).status_code==413

def test_camera_limit_and_bad_queries(fixture):
    client,*_=fixture
    login(client)
    for _ in range(2):
        assert client.post('/api/cameras',json={'name':'c'}).status_code==201
    assert client.post('/api/cameras',json={'name':'c'}).status_code==409
    assert client.get('/api/events?limit=10000').status_code==422
    assert client.get('/api/events?state=wrong').status_code==422

def test_ownership_prevents_access(fixture):
    client,_,app,_=fixture
    _,p=connect(client)
    with app.state.sessions() as db:
        other=User(name='other',password_hash='not used');db.add(other);db.flush()
        db.get(Camera,p['camera_id']).owner_id=other.id;db.commit()
    assert client.get(f'/api/cameras/{p["camera_id"]}/preview').status_code==404
    assert client.patch(f'/api/cameras/{p["camera_id"]}',json={'enabled':False}).status_code==404

def test_websocket_delivers_persisted_alert(fixture):
    client,*_=fixture
    _,p=connect(client)
    with client.websocket_connect('/api/ws/events',headers={'origin':'http://localhost:5173'}) as ws:
        assert ws.receive_json()['type']=='connected'
        for _ in range(3):
            assert frame(client,p).status_code==200
        messages=[ws.receive_json() for _ in range(3)]
        assert any(m['type']=='alert.created' for m in messages)

def test_frame_authentication_and_missing_evidence(fixture):
    client,*_=fixture
    _,p=connect(client)
    assert client.post(f'/api/publisher/{p["camera_id"]}/frames',content=b'').status_code==401
    assert client.get('/api/events/nonexistent/snapshot').status_code==404

def test_concurrent_pairing_has_exactly_one_winner(fixture):
    client,*_=fixture
    login(client)
    created=client.post('/api/cameras',json={'name':'one code'}).json()
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses=list(pool.map(lambda _:client.post('/api/publisher/pair',json={'code':created['pairing']['code']}),range(6)))
    assert sorted(r.status_code for r in responses)==[200,401,401,401,401,401]

def test_slow_evidence_write_does_not_lock_acknowledgement(fixture,monkeypatch):
    client,_,app,_=fixture
    _,p=connect(client)
    frame(client,p);frame(client,p)
    started,release,acknowledged=Event(),Event(),Event()
    put=app.state.store.put
    def slow_put(*args):
        started.set()
        assert release.wait(5)
        return put(*args)
    monkeypatch.setattr(app.state.store,'put',slow_put)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending=pool.submit(frame,client,p)
        try:
            assert started.wait(2)
            event=client.get('/api/events').json()['items'][0]
            def ack():
                response=client.patch(f'/api/events/{event["id"]}',json={'state':'acknowledged'})
                acknowledged.set()
                return response
            update=pool.submit(ack)
            assert acknowledged.wait(2),'Evidence I/O must not hold a database write transaction'
            assert update.result().status_code==200
        finally:
            release.set()
        assert pending.result().json()['event']['state']=='acknowledged'

def test_storage_failure_keeps_durable_alarm(fixture,monkeypatch):
    client,_,app,_=fixture
    _,p=connect(client)
    def fail(*args):
        raise OSError('test storage unavailable')
    monkeypatch.setattr(app.state.store,'put',fail)
    frame(client,p);frame(client,p)
    event=frame(client,p).json()['event']
    assert event['snapshot_url'] is None
    assert '저장 실패' in event['note']
    assert client.get('/api/events').json()['items'][0]['id']==event['id']

def test_disabled_camera_during_inference_does_not_create_alert(fixture,monkeypatch):
    client,detector,_,_=fixture
    _,p=connect(client)
    frame(client,p);frame(client,p)
    started,release=Event(),Event()
    predict=detector.predict
    def slow_predict(data):
        started.set()
        assert release.wait(5)
        return predict(data)
    monkeypatch.setattr(detector,'predict',slow_predict)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(frame,client,p)
        try:
            assert started.wait(2)
            assert frame(client,p).status_code==429
            assert client.patch(f'/api/cameras/{p["camera_id"]}',json={'enabled':False}).status_code==200
        finally:
            release.set()
        assert pending.result().status_code==409
    assert client.get('/api/events').json()['items']==[]

def test_password_change_requires_current_and_revokes_other_sessions(fixture):
    client,_,app,_=fixture
    login(client)
    with app.state.sessions() as db:
        member=db.scalar(select(User).where(User.name=='admin'))
        from app.security import digest
        db.add(LoginSession(token_hash=digest('another-session'),user_id=member.id,expires_at=utcnow()+timedelta(hours=1)))
        db.commit()
    new_password='test-only-strong-password-123'
    assert client.post('/api/auth/password',json={'current_password':'wrong','new_password':new_password}).status_code==401
    assert client.post('/api/auth/password',json={'current_password':'fire-demo-local','new_password':'short'}).status_code==422
    assert client.post('/api/auth/password',json={'current_password':'fire-demo-local','new_password':new_password}).status_code==200
    assert client.get('/api/auth/me').status_code==200
    with app.state.sessions() as db:
        assert db.get(LoginSession,digest('another-session')) is None
    client.post('/api/auth/logout')
    assert client.post('/api/auth/login',json={'username':'admin','password':'fire-demo-local'}).status_code==401
    assert client.post('/api/auth/login',json={'username':'admin','password':new_password}).status_code==200
