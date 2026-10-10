from datetime import timedelta
from sqlalchemy import select
from app.models import Camera,User,utcnow
from test_api import fixture,connect,frame,login

def test_archive_retains_history_revokes_key_and_frees_capacity(fixture):
    client,_,app,_=fixture
    created,p=connect(client)
    for _ in range(3): result=frame(client,p).json()
    event=result['event'];identity=p['camera_id']
    assert event['candidate_label']=='fire' and event['camera_location']=='테스트'
    assert client.post('/api/cameras',json={'name':'second'}).status_code==201
    assert client.post('/api/cameras',json={'name':'full'}).status_code==409
    assert client.post(f'/api/cameras/{identity}/archive').json()['history_preserved']
    assert identity not in [c['id'] for c in client.get('/api/cameras').json()]
    assert client.get('/api/cameras/archived').json()[0]['id']==identity
    assert frame(client,p).status_code==401
    assert client.post(f'/api/cameras/{identity}/pairing').status_code==404
    assert client.get(event['snapshot_url']).status_code==200
    assert client.get('/api/events').json()['items'][0]['id']==event['id']
    assert client.post('/api/cameras',json={'name':'replacement'}).status_code==201
    assert client.post(f'/api/cameras/{identity}/restore').status_code==409

def test_restore_is_disabled_and_does_not_restore_old_publisher(fixture):
    client,_,app,_=fixture
    _,p=connect(client);identity=p['camera_id']
    client.post(f'/api/cameras/{identity}/archive')
    assert client.post(f'/api/cameras/{identity}/restore').status_code==200
    restored=next(c for c in client.get('/api/cameras').json() if c['id']==identity)
    assert not restored['enabled'] and not restored['online']
    assert frame(client,p).status_code==401
    assert client.patch(f'/api/cameras/{identity}',json={'enabled':True}).status_code==200
    assert frame(client,p).status_code==401

def test_archive_is_owner_scoped_and_authenticated(fixture):
    client,_,app,_=fixture
    _,p=connect(client)
    with app.state.sessions() as db:
        camera=db.get(Camera,p['camera_id']);original=camera.owner_id
        from app.security import hash_password
        outsider=User(name='other',password_hash=hash_password('testing-other-password'))
        db.add(outsider);db.commit();camera.owner_id=outsider.id;db.commit()
    assert client.post(f'/api/cameras/{p["camera_id"]}/archive').status_code==404
    client.post('/api/auth/logout')
    assert client.get('/api/cameras/archived').status_code==401
    assert client.post(f'/api/cameras/{p["camera_id"]}/archive').status_code==401

def test_old_preview_is_marked_stale_not_live(fixture):
    client,_,app,_=fixture
    _,p=connect(client);assert frame(client,p).status_code==200
    with app.state.sessions() as db:
        db.get(Camera,p['camera_id']).last_seen=utcnow()-timedelta(seconds=60);db.commit()
    camera=next(c for c in client.get('/api/cameras').json() if c['id']==p['camera_id'])
    assert not camera['online'] and camera['preview_stale']
    assert client.get(camera['preview_url']).status_code==200

def test_sustained_smoke_creates_smoke_alert_not_fire(fixture):
    client,detector,app,_=fixture
    original=detector.predict
    def smoke(data):
        result=original(data);result['fire_candidate']=False;result['smoke_candidate']=True
        result['detections']=[{'class_id':0,'label':'smoke','score':.8,'xyxy':[0,0,16,16],'box':[0,0,.25,.25]}]
        return result
    detector.predict=smoke
    _,p=connect(client)
    assert frame(client,p).json()['event'] is None
    assert frame(client,p).json()['event'] is None
    result=frame(client,p).json()
    assert result['event']['candidate_label']=='smoke'
    assert result['smoke_temporal']['trigger'] and not result['temporal']['trigger']
    assert frame(client,p).json()['event'] is None

def test_stream_lookup_never_without_auth(fixture):
    client,*_=fixture
    assert client.get('/api/cameras/unknown/stream').status_code==401
    login(client)
    assert client.get('/api/cameras/unknown/stream').status_code==404

def test_old_schema_migration_retains_existing_alerts(tmp_path):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine,text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.db import Base
    engine=create_engine(f'sqlite:///{tmp_path}/migration.db')
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE cameras DROP COLUMN archived_at'))
        connection.execute(text('ALTER TABLE alerts DROP COLUMN candidate_label'))
        connection.execute(text("INSERT INTO users (id,name,password_hash) VALUES ('u','test','test-only')"))
        connection.execute(text("INSERT INTO cameras (id,owner_id,name,location,kind,enabled,created_at,last_signal,frames) VALUES ('c','u','camera','','browser',1,'2026-10-10','offline',0)"))
        connection.execute(text("INSERT INTO alerts (id,owner_id,camera_id,camera_name,kind,state,created_at,confidence,model_sha256,policy_sha256,detections,note) VALUES ('a','u','c','camera','live','new','2026-10-10',0.8,'m','p','[]','')"))
        path=Path(__file__).resolve().parents[1]/'migrations/versions/0004_camera_archive.py'
        spec=importlib.util.spec_from_file_location('camera_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade();module.upgrade()  # Existing columns are safe on repeated invocation.
        assert connection.execute(text('SELECT candidate_label FROM alerts WHERE id="a"')).scalar()=='fire'
        assert connection.execute(text('SELECT archived_at FROM cameras WHERE id="c"')).scalar() is None
