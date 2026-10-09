import asyncio
import httpx
import pytest
from fastapi import HTTPException
from test_api import fixture, login
from app.providers import Providers


def sample():
    return {"response": {"data": [
        {"cctvname": "대구 테스트", "coordx": 128.6, "coordy": 35.8, "cctvurl": "https://video.example.org/live.m3u8"},
        {"cctvname": "범위 밖", "coordx": 127.0, "coordy": 37.0, "cctvurl": "https://video.example.org/other"},
        {"cctvname": "사설 IP", "coordx": 128.6, "coordy": 35.8, "cctvurl": "http://127.0.0.1/secret"},
    ]}}


def test_provider_auth_and_input_validation(fixture):
    c, *_ = fixture
    assert c.get('/api/maps/config').status_code == 401
    assert c.get('/api/cctv/catalog').status_code == 401
    login(c)
    assert c.get('/api/maps/geocode?query=x').status_code == 422
    assert c.get('/api/maps/reverse?latitude=999&longitude=128').status_code == 422
    assert c.get('/api/cctv/catalog?road=all').status_code == 422
    assert c.get('/api/cctv/catalog?video_type=9').status_code == 422


def test_maps_never_exposes_secret_and_uses_new_endpoint(fixture, monkeypatch):
    c, _, app, _ = fixture
    monkeypatch.setenv('NAVER_MAPS_CLIENT_ID', 'public-id')
    monkeypatch.setenv('NAVER_MAPS_CLIENT_SECRET', 'private-secret')
    requests = []
    def handler(req):
        requests.append(req)
        if req.url.path.endswith('/gc'):
            return httpx.Response(200, json={'status': {'code': 0}, 'results': [
                {'name': 'legalcode', 'region': {'area1': {'name': '대구광역시'}, 'area2': {'name': '남구'}}}]})
        return httpx.Response(200, json={'status': 'OK', 'addresses': [
            {'roadAddress': '대구광역시 주소', 'x': '128.6', 'y': '35.8'}]})
    app.state.providers.transport = httpx.MockTransport(handler)
    login(c)
    conf = c.get('/api/maps/config')
    assert 'private-secret' not in conf.text and conf.json()['client_id'] == 'public-id'
    assert c.get('/api/maps/geocode?query=대구 주소').json()['items'][0]['latitude'] == 35.8
    assert c.get('/api/maps/reverse?latitude=35.8&longitude=128.6').json()['address'] == '대구광역시 남구'
    assert all(r.url.host == 'maps.apigw.ntruss.com' for r in requests)
    assert requests[0].headers['x-ncp-apigw-api-key'] == 'private-secret'


def test_catalog_cache_filters_and_stream_selection(fixture, monkeypatch):
    c, _, app, _ = fixture
    monkeypatch.setenv('ITS_API_KEY', 'its-private-test-key')
    requests = []
    def handler(req):
        requests.append(req)
        return httpx.Response(200, json=sample())
    app.state.providers.transport = httpx.MockTransport(handler)
    login(c)
    catalog = c.get('/api/cctv/catalog').json()
    assert len(catalog['items']) == 1
    assert 'url' not in catalog['items'][0]
    assert 'its-private-test-key' not in str(catalog)
    identity = catalog['items'][0]['id']
    assert c.get(f'/api/cctv/{identity}/stream').json()['url'].startswith('https://video.')
    c.get('/api/cctv/catalog');c.get('/api/cctv/catalog?refresh=true')
    assert len(requests) == 1
    assert requests[0].url.host == 'openapi.its.go.kr'
    assert requests[0].url.params['maxX'] == '128.85'
    assert c.get('/api/cctv/unknown/stream').status_code == 404
    first = c.post(f'/api/cctv/{identity}/register')
    second = c.post(f'/api/cctv/{identity}/register')
    assert first.json()['id'] == second.json()['id']
    assert first.json()['kind'] == 'its'
    assert '발화점 아님' in first.json()['location']


def test_provider_failure_redacted_and_backed_off(monkeypatch):
    monkeypatch.setenv('ITS_API_KEY', 'sensitive-value')
    def handler(req):
        raise httpx.ConnectError(str(req.url))
    p = Providers(httpx.MockTransport(handler))
    async def run():
        with pytest.raises(HTTPException) as e:
            await p.catalog('ex', 4)
        assert e.value.status_code == 502 and 'sensitive-value' not in e.value.detail
        with pytest.raises(HTTPException) as e:
            await p.catalog('ex', 4)
        assert e.value.status_code == 429
    asyncio.run(run())


@pytest.mark.parametrize('url', ['file:///tmp/x', 'http://localhost/x', 'http://10.0.0.1/x',
                                  'http://169.254.169.254/x', 'http://[::1]/x', 'https://u:p@example.org',
                                  'https://host.local/x', 'https://example.org:9000/x'])
def test_unsafe_stream_urls_rejected(url):
    assert not Providers.public_stream(url)


def test_cctv_frame_requires_owner_and_its_kind(fixture):
    c, _, app, _ = fixture
    assert c.post('/api/cctv/cameras/anything/frames', content=b'x').status_code == 401
    login(c)
    assert c.post('/api/cctv/cameras/anything/frames', content=b'x').status_code == 404
    camera = c.post('/api/cameras', json={'name':'browser'}).json()['camera']['id']
    assert c.post(f'/api/cctv/cameras/{camera}/frames', content=b'x').status_code == 409
