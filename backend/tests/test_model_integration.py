"""Optional real-model test, separate from deterministic injected service tests."""
import os
import json
import time
from pathlib import Path
import pytest
from app.config import ROOT,Settings
from app.detector import YoloDetector
from app.main import create_app
from fastapi.testclient import TestClient

@pytest.mark.skipif(os.getenv('EMBER_RUN_MODEL_TEST')!='1',reason='Enable explicit real-model integration test')
def test_actual_model_fire_clear_and_web_alarm(tmp_path):
    settings=Settings(environment='testing',database_url=f'sqlite:///{tmp_path}/real.db',storage_path=tmp_path/'evidence',alarm_min_seconds=0,
        spread_jobs_path=tmp_path/'spread-jobs')
    detector=YoloDetector(settings)
    with TestClient(create_app(settings,detector)) as client:
        client.headers['X-Ember-Client']='web'
        assert detector.ready,detector.error
        assert client.post('/api/auth/login',json={'username':'admin','password':'fire-demo-local'}).status_code==200
        for _ in range(3):
            response=client.post('/api/demo/frame?name=fire')
            assert response.status_code==200,response.text
            assert response.json()['fire_candidate']
        event=response.json()['event']
        assert event and event['kind']=='demo'
        assert client.get(event['snapshot_url']).status_code==200
        # Compare an actual independently decoded negative sample; no forced outputs.
        result=detector.predict((ROOT/'samples'/'clear.jpg').read_bytes())
        assert not result['fire_candidate']
        assert detector.model_hash=='57c133a489976dc2f7341381b12cf160622e0bbaff33aeffdee4926e2093611d'

        # Exercise the same authenticated publisher endpoint used by phones,
        # using an actual model and a temporary database, not a forced signal.
        created=client.post('/api/cameras',json={'name':'real-model publisher'}).json()
        publisher=client.post('/api/publisher/pair',json={'code':created['pairing']['code']}).json()
        headers={'Authorization':'Bearer '+publisher['token'],'Content-Type':'image/jpeg'}
        for _ in range(3):
            response=client.post(f'/api/publisher/{publisher["camera_id"]}/frames',
                content=(ROOT/'samples'/'fire.jpg').read_bytes(),headers=headers)
            assert response.status_code==200,response.text
            assert response.json()['fire_candidate']
        live_event=response.json()['event']
        assert live_event and live_event['kind']=='live'
        assert client.get(live_event['snapshot_url']).status_code==200
        assert client.post(f'/api/publisher/{publisher["camera_id"]}/stop',headers=headers).status_code==200

        # Actual YOLO publisher alarm -> real process-pool CA -> durable linked result.
        manifest=client.get('/api/spread/status').json()['manifest']
        response=client.post('/api/simulations',json={**manifest['default_ignition'],
            'event_id':live_event['id'],'location_confirmed':True,'weather_mode':'manual',
            'manual_weather':{},'model':'ca','horizon_min':10,'runs':10,'seed':42})
        assert response.status_code==202,response.text
        job_id=response.json()['id']
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            job=client.get('/api/simulations/'+job_id).json()
            if job['state'] in ('completed','failed'):
                break
            time.sleep(.05)
        assert job['state']=='completed',job
        saved=json.loads((settings.spread_jobs_path/job_id/'job.json').read_text(encoding='utf-8'))
        assert saved['request']['event_id']==live_event['id']
        assert saved['state']=='completed'
        assert saved['summary']['data_sha256']==manifest['data_sha256']
        geometry=client.get('/api/simulations/'+job_id+'/perimeters')
        assert geometry.status_code==200
        assert geometry.json()['features']
        assert not (settings.spread_jobs_path/job_id/'result.next.geojson').exists()

        # ITS browser frame route, using the existing consented sample, not public video.
        from app.models import Camera, User
        from sqlalchemy import select
        with client.app.state.sessions() as db:
            owner=db.scalar(select(User).where(User.name=='admin'))
            camera=Camera(owner_id=owner.id,name='ITS route / private sample verification',kind='its')
            db.add(camera);db.commit();its_camera_id=camera.id
        for _ in range(3):
            time.sleep(.6)
            response=client.post(f'/api/cctv/cameras/{its_camera_id}/frames',
                content=(ROOT/'samples'/'fire.jpg').read_bytes(),headers={'Content-Type':'image/jpeg'})
            assert response.status_code==200,response.text
            assert response.json()['fire_candidate']
        assert response.json()['event']['kind']=='live'
        assert client.get(response.json()['event']['snapshot_url']).status_code==200

def test_lan_origin_keeps_loopback_console_but_rejects_other_origins(tmp_path):
    from test_api import FakeDetector
    settings=Settings(environment='testing',database_url=f'sqlite:///{tmp_path}/lan.db',
        storage_path=tmp_path/'evidence',public_origin='https://192.168.0.6:8443')
    with TestClient(create_app(settings,FakeDetector(settings))) as client:
        payload={'username':'admin','password':'fire-demo-local'}
        assert client.post('/api/auth/login',json=payload,headers={'Origin':'https://192.168.0.6:8443'}).status_code==200
        assert client.post('/api/auth/login',json=payload,headers={'Origin':'http://localhost:5173','X-Ember-Client':'web'}).status_code==200
        assert client.post('/api/auth/login',json=payload,headers={'Origin':'http://192.168.0.6:5173'}).status_code==403
        assert client.get('/api/system',headers={'Host':'attacker.example'}).status_code==400
