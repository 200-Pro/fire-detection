"""Local operator only: bounded official ITS preflight/start/report. No passwords in CLI."""
import argparse
import asyncio
from datetime import timedelta
import json
import hashlib
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from sqlalchemy import select, func

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.config import Settings
from app.db import make_database
from app.models import User,Camera,Monitor,MonitorTrial,AuditLog,utcnow
from app.providers import Providers
from app.security import digest,aware
from app.stream_reader import HlsReader,StreamError

CANDIDATES=["1c0113588aac79489a012319", "73cbb3cb9ac9fa7a9f2d2a2a",
            "8323e733d8c68628446590b8", "32493846d9783f10d6877097"]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=['preflight','start','report'])
    p.add_argument('--rights-confirmed',action='store_true')
    p.add_argument('--minutes',type=int,default=60)
    p.add_argument('--interval',type=float,default=10)
    p.add_argument('--evidence-hours',type=int,default=24)
    p.add_argument('--approval-reference',default='')
    p.add_argument('--allowed-host',action='append',default=[])
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    cfg=Settings.from_env()
    if cfg.environment!='development' or not cfg.database_url.startswith('sqlite:///'):
        p.error('Local development SQLite operator only; production requires authenticated administration.')
    if args.mode!='report' and (not args.rights_confirmed or len(args.approval_reference.strip())<5):
        p.error('Explicit provider rights confirmation and non-secret reference required.')
    if not 1<=args.minutes<=1440 or not 2<=args.interval<=10 or not 1<=args.evidence_hours<=24:
        p.error('Invalid duration/interval/retention')
    if args.mode=='preflight':
        # Exact temporary hosts, affects this single probe process only.
        if args.allowed_host:
            os.environ['EMBER_STREAM_ALLOWED_HOSTS']=','.join(args.allowed_host)
        items=asyncio.run(Providers().catalog('ex',4))['items']
        reader=HlsReader();rows=[]
        for identity in CANDIDATES:
            item=next((i for i in items if i['id']==identity),None)
            row={'catalog_id':identity,'ok':False}
            if not item:
                row['message']='not in current official catalog'
            else:
                row.update(name=item['name'],latitude=item['latitude'],longitude=item['longitude'],host=urlsplit(item['url']).hostname)
                try:
                    frame=reader.read(identity,item['url'])
                    row.update(ok=bool(frame),frame_bytes=len(frame or b''),message='decoded frame in memory; not stored')
                except StreamError as exc:
                    row['message']=str(exc)
                row.update(reader.stats.get(identity,{}))
            rows.append(row)
        result={'kind':'single-sample-preflight','public_video_collected':any(row['ok'] for row in rows),'items':rows,
                'accuracy_validated':False}
    else:
        engine,sessions=make_database(cfg.database_url)
        try:
            with sessions() as db:
                owner=db.scalar(select(User).where(User.name==cfg.admin_name))
                if not owner:
                    p.error('Configured local owner missing; start the server first.')
                if args.mode=='report':
                    trials=list(db.scalars(select(MonitorTrial).where(MonitorTrial.owner_id==owner.id)
                        .order_by(MonitorTrial.started_at.desc()).limit(100)))
                    result={'generated_at':utcnow().isoformat(),'items':[{
                        'id':t.id,'camera_id':t.camera_id,'name':db.get(Camera,t.camera_id).name,
                        'state':t.state,'started_at':aware(t.started_at).isoformat(),
                        'deadline':aware(t.deadline).isoformat(),'evidence_hours':t.evidence_hours,
                        'enabled':db.get(Monitor,t.camera_id).enabled,'report':t.report} for t in trials],
                        'accuracy_validated':False}
                else:
                    if not cfg.cctv_ai_approved:
                        p.error('Server approval configuration is OFF.')
                    if db.scalar(select(func.count()).select_from(Monitor).where(Monitor.enabled.is_(True))):
                        p.error('An existing monitor is active; do not overwrite an ongoing session.')
                    providers=Providers();items=asyncio.run(providers.catalog('ex',4))['items']
                    reader=HlsReader()
                    if cfg.monitor_capacity<4:
                        p.error('Four-camera trial requires capacity >=4.')
                    deadline=utcnow()+timedelta(minutes=args.minutes)
                    result={'kind':'four-camera-trial-start','deadline':deadline.isoformat(),'items':[],
                        'note':'User reported institutional permission; no credentials included. Auto-spread OFF.'}
                    for catalog_id in CANDIDATES:
                        item=next((i for i in items if i['id']==catalog_id),None)
                        if not item or urlsplit(item['url']).hostname not in reader.allowed_hosts:
                            p.error('Candidate missing or video host not allowlisted; transaction not committed.')
                        identity=digest(owner.id+':its:'+catalog_id)[:32]
                        camera=db.get(Camera,identity)
                        if not camera:
                            count=db.scalar(select(func.count()).select_from(Camera).where(Camera.owner_id==owner.id,Camera.kind!='sample'))
                            if count>=cfg.max_cameras:
                                p.error('Registration capacity exceeded; transaction not committed.')
                            camera=Camera(id=identity,owner_id=owner.id,name=item['name'],kind='its',
                                location=f'{item["latitude"]:.5f}, {item["longitude"]:.5f} · installation, not ignition')
                            db.add(camera);db.flush()
                        elif not camera.enabled:
                            p.error('Candidate camera disabled; enable explicitly in camera management.')
                        m=db.get(Monitor,identity)
                        if not m:
                            m=Monitor(camera_id=identity,owner_id=owner.id,catalog_id=catalog_id,road='ex',video_type=4)
                            db.add(m);db.flush()
                        m.enabled=True;m.revision+=1;m.updated_at=utcnow()
                        m.approval_reference=args.approval_reference.strip();m.interval_seconds=args.interval
                        m.rules={'minimum_score':.25,'ignore_polygons':[]};m.auto_spread=False
                        t=MonitorTrial(camera_id=identity,owner_id=owner.id,revision=m.revision,deadline=deadline,
                            evidence_hours=args.evidence_hours,report={"configured_interval_seconds":args.interval,
                                "source":"국토교통부 국가교통정보센터(ITS)",
                                "model_sha256":hashlib.sha256(cfg.model_path.read_bytes()).hexdigest(),
                                "base_policy_sha256":hashlib.sha256(cfg.policy_path.read_bytes()).hexdigest()})
                        db.add(t);db.flush()
                        db.add(AuditLog(owner_id=owner.id,action='monitor.trial_started_local',target_id=t.id))
                        result['items'].append({'name':camera.name,'camera_id':identity,'trial_id':t.id,
                            'interval_seconds':args.interval,'evidence_hours':args.evidence_hours})
                    db.commit()
        finally:
            engine.dispose()
    if args.output:
        out=args.output.resolve()
        if not out.is_relative_to((ROOT/'runtime').resolve()) or out.exists():
            p.error('Output must be a NEW file inside runtime.')
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__':
    main()
