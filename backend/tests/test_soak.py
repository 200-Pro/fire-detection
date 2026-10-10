import time
from datetime import timedelta
from io import BytesIO
from PIL import Image
import httpx
from sqlalchemy import select
from test_api import fixture, login
from app.models import Monitor, MonitorTrial, TrialEvidence, User, Camera, Alert, utcnow
from app.soak import TrialMetrics, expire_trials, cleanup_evidence

def four_catalog(app, monkeypatch):
    monkeypatch.setenv("ITS_API_KEY", "test-only")
    monkeypatch.setenv("EMBER_STREAM_ALLOWED_HOSTS", "video.example.org")
    app.state.settings.max_cameras=4
    app.state.settings.cctv_ai_approved=True
    rows=[{"cctvname":str(i),"coordx":128.6+i*.01,"coordy":35.8,
        "cctvurl":f"https://video.example.org/{i}.m3u8"} for i in range(4)]
    app.state.providers.transport=httpx.MockTransport(lambda r:httpx.Response(200,json={"response":{"data":rows}}))

def test_four_camera_trial_without_player_and_deadline(fixture,monkeypatch):
    c,_,app,_=fixture
    four_catalog(app,monkeypatch)
    login(c)
    svc=app.state.monitoring
    counts={}
    def frames(identity,url):
        counts[identity]=counts.get(identity,0)+1
        out=BytesIO();Image.new("RGB",(64,64),(counts[identity]%250,20,90)).save(out,format="JPEG")
        svc.reader.stats[identity]={"video_http_attempts":counts[identity]*2,"video_success_bytes":counts[identity]*1000}
        return out.getvalue()
    monkeypatch.setattr(svc.reader,"read",frames)
    for item in c.get('/api/cctv/catalog').json()['items']:
        r=c.put(f'/api/cctv/{item["id"]}/monitor',json={"enabled":True,"rights_confirmed":True,
            "approval_reference":"TEST FIXTURE ONLY","interval_seconds":2,"trial_minutes":1})
        assert r.status_code==200
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        rows=c.get('/api/monitoring/trials').json()['items']
        if len(rows)==4 and all(r['report'].get('frames',0)>=2 for r in rows):
            break
        time.sleep(.2)
    assert len(rows)==4 and all(r['report'].get('frames',0)>=2 for r in rows)
    assert all(r['report']['video_http_attempts']>=2 for r in rows)
    with app.state.sessions() as db:
        for t in db.scalars(select(MonitorTrial)):
            t.deadline=utcnow()-timedelta(seconds=1)
        db.commit()
    time.sleep(2)
    assert all(not r['enabled'] for r in c.get('/api/monitoring').json()['items'])
    assert all(r['state']=='completed' for r in c.get('/api/monitoring/trials').json()['items'])
    before=dict(counts);time.sleep(2.1)
    assert counts==before

def test_trial_listing_requires_login(fixture):
    c,*_=fixture
    assert c.get('/api/monitoring/trials').status_code==401
    login(c)
    assert c.get('/api/monitoring/trials').json()['items']==[]

def test_expired_deadline_applies_without_worker_and_rejects_current(fixture,monkeypatch):
    c,_,app,_=fixture
    four_catalog(app,monkeypatch);login(c)
    item=c.get('/api/cctv/catalog').json()['items'][0]
    # Server supervisor is live, but no remote reads should be necessary to enforce a deadline.
    r=c.put(f'/api/cctv/{item["id"]}/monitor',json={"enabled":False})
    identity=r.json()['camera_id']
    with app.state.sessions() as db:
        m=db.get(Monitor,identity);m.enabled=True
        trial=MonitorTrial(camera_id=identity,owner_id=m.owner_id,revision=m.revision,
            deadline=utcnow()-timedelta(seconds=1))
        db.add(trial);db.commit()
    assert app.state.monitoring.current(identity) is None
    expire_trials(app.state.sessions,{})
    with app.state.sessions() as db:
        assert not db.get(Monitor,identity).enabled
        assert db.scalar(select(MonitorTrial)).state=='completed'

def test_metrics_are_bounded_and_means_cumulative():
    m=TrialMetrics()
    for i in range(1000):
        m.observe('cycle_ms',i)
    r=m.report()
    assert len(m.samples['cycle_ms'])==500
    assert r['cycle_ms_mean']==499.5 and r['cycle_ms_recent_p95']==974
    assert not r['accuracy_validated']

def test_evidence_expiry_only_new_enrolled_snapshot(fixture):
    _,_,app,_=fixture
    with app.state.sessions() as db:
        owner=db.scalar(select(User))
        camera=Camera(owner_id=owner.id,name='local test');db.add(camera);db.flush()
        trial=MonitorTrial(camera_id=camera.id,owner_id=owner.id,revision=1,deadline=utcnow())
        db.add(trial);db.flush()
        alerts=[]
        for _ in range(2):
            a=Alert(owner_id=owner.id,camera_id=camera.id,camera_name=camera.name,confidence=.7,
                model_sha256='a'*64,policy_sha256='b'*64,detections=[])
            db.add(a);db.flush();a.snapshot_key=app.state.store.put(a.id,b'test-only')
            alerts.append(a)
        db.add(TrialEvidence(alert_id=alerts[0].id,trial_id=trial.id,expires_at=utcnow()-timedelta(seconds=1)))
        keys=[a.snapshot_key for a in alerts];ids=[a.id for a in alerts];db.commit()
    assert cleanup_evidence(app.state.sessions,app.state.store)==1
    assert not (app.state.store.root/keys[0]).exists()
    assert (app.state.store.root/keys[1]).exists()
    with app.state.sessions() as db:
        assert db.get(Alert,ids[0]).snapshot_key is None
        assert db.get(Alert,ids[1]).snapshot_key==keys[1]

def test_trial_metrics_revision_isolation(fixture):
    _,_,app,_=fixture
    with app.state.sessions() as db:
        owner=db.scalar(select(User));camera=Camera(owner_id=owner.id,name='test');db.add(camera);db.flush()
        m=Monitor(camera_id=camera.id,owner_id=owner.id,catalog_id='c',road='ex',video_type=4,enabled=True,revision=2)
        t=MonitorTrial(camera_id=camera.id,owner_id=owner.id,revision=2,deadline=utcnow()+timedelta(minutes=1))
        db.add_all([m,t]);db.commit();identity=camera.id
    expire_trials(app.state.sessions,{identity:{'revision':1,'report':{'frames':999}}})
    with app.state.sessions() as db:
        assert db.scalar(select(MonitorTrial)).report=={}

def test_redirect_same_host_bounded_and_counted(monkeypatch):
    import app.stream_reader as reader
    from urllib.parse import urlsplit
    import pytest
    responses=[]
    class Response:
        def __init__(self,status,location=None,body=b''):
            self.status,self.location,self.body=status,location,body
        def getheader(self,name):
            return self.location if name=='Location' else None
        def read(self,size):
            body,self.body=self.body[:size],self.body[size:]
            return body
    class Connection:
        def __init__(self,*args,**kwargs):
            pass
        def request(self,*args,**kwargs):
            pass
        def getresponse(self):
            return responses.pop(0)
        def close(self):
            pass
    monkeypatch.setattr(reader,'safe_target',lambda url,hosts:(urlsplit(url),'8.8.8.8'))
    monkeypatch.setattr(reader.socket,'create_connection',lambda *args,**kwargs:object())
    monkeypatch.setattr(reader.http.client,'HTTPConnection',Connection)
    responses.extend([Response(302,'/new'),Response(200,body=b'hello')])
    stats={'video_http_attempts':0,'video_success_bytes':0}
    assert reader.fetch_bytes('http://video.example.org/old',{'video.example.org'},100,stats=stats)==b'hello'
    assert stats=={'video_http_attempts':2,'video_success_bytes':5}
    responses.extend([Response(302,'http://other.example.org/a')])
    with pytest.raises(reader.StreamError):
        reader.fetch_bytes('http://video.example.org/old',{'video.example.org','other.example.org'},100)
    responses.extend([Response(302,'/a'),Response(302,'/b'),Response(302,'/c')])
    with pytest.raises(reader.StreamError):
        reader.fetch_bytes('http://video.example.org/old',{'video.example.org'},100)

def test_relative_segment_uses_final_manifest_url(monkeypatch):
    import app.stream_reader as reader
    urls=[]
    def fetch(url,hosts,limit,stats=None,metadata=None):
        urls.append(url)
        metadata['url']='https://video.example.org:8082/live/playlist.m3u8' if len(urls)==1 else url
        return b'#EXTM3U\n#EXTINF:2,\nseg.ts' if len(urls)==1 else b'segment'
    monkeypatch.setenv('EMBER_STREAM_ALLOWED_HOSTS','video.example.org')
    monkeypatch.setattr(reader,'fetch_bytes',fetch)
    monkeypatch.setattr(reader,'decode_segment',lambda value:b'JPEG TEST ONLY')
    assert reader.HlsReader().read('x','https://video.example.org/old')==b'JPEG TEST ONLY'
    assert urls[1]=='https://video.example.org:8082/live/seg.ts'

def test_active_media_playlist_reused_instead_of_entry_ticket(monkeypatch):
    import app.stream_reader as reader
    urls=[]
    def fetch(url,hosts,limit,stats=None,metadata=None):
        urls.append(url)
        if url.endswith('.ts'):
            metadata['url']=url
            return b'segment'
        metadata['url']='https://video.example.org:8082/live/media.m3u8'
        return b'#EXTM3U\n#EXTINF:2,\nseg.ts'
    monkeypatch.setenv('EMBER_STREAM_ALLOWED_HOSTS','video.example.org')
    monkeypatch.setattr(reader,'fetch_bytes',fetch)
    monkeypatch.setattr(reader,'decode_segment',lambda value:b'JPEG TEST ONLY')
    hls=reader.HlsReader()
    assert hls.read('x','https://video.example.org/ticket')
    assert hls.read('x','https://video.example.org/ticket') is None
    assert urls==['https://video.example.org/ticket','https://video.example.org:8082/live/seg.ts',
                 'https://video.example.org:8082/live/media.m3u8']

def test_stream_error_phase_sanitized_and_reader_forget(monkeypatch):
    import app.stream_reader as reader
    import pytest
    monkeypatch.setenv('EMBER_STREAM_ALLOWED_HOSTS','video.example.org')
    def fail(*args,**kwargs):
        raise reader.StreamError('제공기관 영상 응답 오류 (403)',status_code=403,retry_after=120)
    monkeypatch.setattr(reader,'fetch_bytes',fail)
    hls=reader.HlsReader();hls.playlists['c']=('https://video.example.org/ticket','https://video.example.org/media');hls.last['c']='old'
    with pytest.raises(reader.StreamError) as captured:
        hls.read('c','https://video.example.org/ticket')
    assert captured.value.stage=='playlist' and captured.value.status_code==403
    assert captured.value.retry_after==120 and 'https' not in str(captured.value)
    hls.forget('c');assert 'c' not in hls.playlists and 'c' not in hls.last

def test_retry_after_date_and_seconds():
    from app.stream_reader import retry_seconds
    from email.utils import format_datetime
    assert retry_seconds('120')==120
    assert retry_seconds('invalid')==0
    assert 110<=retry_seconds(format_datetime(utcnow()+timedelta(seconds=120)))<=121
