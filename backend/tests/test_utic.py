import asyncio
import base64
from io import BytesIO
import json
import time
from xml.sax.saxutils import escape
import zipfile

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select
from app.models import Alert, Camera
from app.utic import UticProvider, read_catalog, player_source
from fastapi import HTTPException
from test_api import fixture, login

KEY = 'utic-fake-test-key'
STREAM = 'https://carcctv.daegu.go.kr/live3/_definst_/ch206.stream/playlist.m3u8'
ITEM = {'id':'E100002','name':'가창삼거리','center':'대구교통정보센터',
        'longitude':128.622411,'latitude':35.801472,'provider':'utic'}


def book(path, rows):
    headers=['RN','CCTVID','CCTVNAME','CENTERNAME','XCOORD','YCOORD']
    cells=[]
    for i, values in enumerate([headers]+rows, 1):
        cells.append('<row r="'+str(i)+'">'+''.join(
            f'<c r="{chr(65+j)}{i}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'
            for j,v in enumerate(values))+'</row>')
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="sheet2" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(cells)+'</sheetData></worksheet>')


def setup_provider(provider, monkeypatch, requests, *, failure=False):
    monkeypatch.setenv('UTIC_API_KEY',KEY)
    monkeypatch.setattr('app.utic.read_catalog',lambda path:([ITEM],3,1))
    def handler(req):
        requests.append(req)
        assert req.url.host=='www.utic.go.kr'
        if failure:raise httpx.ConnectError(str(req.url))
        if req.url.path.endswith('cctvOpenData.do'):
            assert req.url.params['key']==KEY
            return httpx.Response(200,text='<a href="javascript:test(\'E100002\')">1.가창삼거리</a>',
                                  headers={'set-cookie':'JSESSIONID=fixture-session; Path=/; Secure'})
        assert 'fixture-session' in req.headers.get('cookie','')
        assert req.headers['X-Requested-With']=='XMLHttpRequest'
        if req.url.path.endswith('getCctvInfoById.do'):
            return httpx.Response(200,json={'CCTVID':'E100002','CCTVNAME':'가창삼거리','KIND':'H','MOVIE':'Y',
                                           'CCTVIP':'fixture-ip','CH':1,'ID':206,'PASSWD':'metadata-secret','PORT':443})
        assert req.url.path.endswith('openDataCctvStream.jsp')
        assert req.url.params['key']==KEY
        return httpx.Response(200,text=f"<script>var videoSrc = '{STREAM}';</script>")
    provider.transport=httpx.MockTransport(handler)


def test_xlsx_ids_coordinates_and_daegu_filter(tmp_path):
    path=tmp_path/'catalog.xlsx'
    book(path,[[1,'E100002','가창삼거리','대구교통정보센터',128.622411,35.801472],
               [2,'E100003','좌표 오류','대구교통정보센터',128.6,128.6],
               [3,'L280068','거제','거제교통정보센터',128.6,34.8]])
    records,total,invalid=read_catalog(path)
    assert records==[ITEM] and total==3 and invalid==1
    assert len(path.read_bytes())>0


def test_catalog_and_stream_are_cached_and_keep_key_metadata_private(monkeypatch):
    p=UticProvider();requests=[];setup_provider(p,monkeypatch,requests)
    async def run():
        catalog=await p.catalog()
        assert catalog['items']==[ITEM] and not catalog['ai_enabled']
        stream=await p.stream('E100002')
        assert stream['url']==STREAM and stream['max_preview_seconds']==60
        await p.catalog();await p.catalog(True);await p.stream('E100002')
        assert len(requests)==3
        assert KEY not in json.dumps(catalog) and KEY not in json.dumps(stream)
        assert 'metadata-secret' not in json.dumps(stream)
    asyncio.run(run())


def test_failure_is_redacted_and_catalog_retry_is_bounded(monkeypatch):
    p=UticProvider();requests=[];setup_provider(p,monkeypatch,requests,failure=True)
    async def run():
        with pytest.raises(HTTPException) as e:await p.catalog()
        assert e.value.status_code==502 and KEY not in e.value.detail
        with pytest.raises(HTTPException) as e:await p.catalog()
        assert e.value.status_code==429 and len(requests)==1
    asyncio.run(run())


@pytest.mark.parametrize('source',[
    'http://carcctv.daegu.go.kr/live3/_definst_/ch206.stream/playlist.m3u8',
    'https://127.0.0.1/live3/_definst_/ch206.stream/playlist.m3u8',
    STREAM+'?key='+KEY,
    'https://carcctv.daegu.go.kr:8443/live3/_definst_/ch206.stream/playlist.m3u8',
    'https://carcctv.daegu.go.kr/unrelated/playlist.m3u8'])
def test_arbitrary_or_credential_bearing_media_rejected(source):
    with pytest.raises(HTTPException):player_source(f"var videoSrc = '{source}';",KEY)


def test_catalog_membership_and_expired_source_cannot_be_reused(monkeypatch):
    p=UticProvider();requests=[];setup_provider(p,monkeypatch,requests)
    async def run():
        await p.catalog()
        with pytest.raises(HTTPException) as e:await p.stream('not-in-issued-list')
        assert e.value.status_code==404 and len(requests)==1
        await p.stream('E100002')
        stamp,result=p.streams['E100002'];p.streams['E100002']=(stamp-56,result)
        with pytest.raises(HTTPException) as e:await p.stream('E100002')
        assert e.value.status_code==429 and len(requests)==3
    asyncio.run(run())


def test_routes_require_auth_and_probe_has_no_camera_alarm_or_evidence(fixture,monkeypatch):
    client,_,app,cfg=fixture
    assert client.get('/api/utic/config').status_code==401
    assert client.get('/api/utic/catalog').status_code==401
    assert client.post('/api/utic/E100002/probe').status_code==401
    requests=[];setup_provider(app.state.utic,monkeypatch,requests)
    out=BytesIO();Image.new('RGB',(64,64),'black').save(out,format='JPEG')
    monkeypatch.setattr('app.utic.probe_frame',lambda identity,url:{'decoded':True,'width':64,'height':64,
        'jpeg_bytes':len(out.getvalue()),'frame_base64':base64.b64encode(out.getvalue()).decode(),
        'http_requests':3,'ai_analysis':False,'evidence_saved':False})
    login(client)
    assert KEY not in client.get('/api/utic/config').text
    assert client.get('/api/utic/catalog').json()['items']==[ITEM]
    result=client.post('/api/utic/E100002/probe')
    assert result.status_code==200 and not result.json()['ai_analysis'] and not result.json()['evidence_saved']
    assert KEY not in result.text and 'metadata-secret' not in result.text
    assert client.post('/api/utic/E100002/probe').status_code==429
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Alert))==0
        assert db.scalar(select(func.count()).select_from(Camera))==0
    assert not cfg.storage_path.exists() or not list(cfg.storage_path.rglob('*.jpg'))
