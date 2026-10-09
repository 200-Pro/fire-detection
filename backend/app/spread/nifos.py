"""Official province-level fire danger context; never a calibrated spread input."""
import asyncio
from datetime import datetime, timedelta, timezone
from math import isfinite
import os
import time
from urllib.parse import unquote
import httpx

KST = timezone(timedelta(hours=9))
ENDPOINT = 'https://apis.data.go.kr/1400377/forestPointV2/forestPointListSidoSearchV2'


def parse_danger(body, now=None):
    now = now or datetime.now(timezone.utc)
    unavailable = {'available': False, 'source': 'nifos',
                   'message': '산불위험예보 자료가 없거나 응답이 유효하지 않습니다.'}
    try:
        response = body['response']
        if str(response['header']['resultCode']) != '00':
            return unavailable  # Do not echo resultMsg or key-bearing provider URLs.
        items = response['body']['items']['item']
        if isinstance(items, dict):
            items = [items]
        records = []
        for item in items:
            if int(item['regioncode']) != 27:
                continue
            when = datetime.strptime(str(item['analdate']).strip(), '%Y-%m-%d %H').replace(tzinfo=KST).astimezone(timezone.utc)
            minimum, mean, maximum = [float(item[k]) for k in ('mini', 'meanavg', 'maxi')]
            if not all(isfinite(v) and 0 <= v <= 100 for v in (minimum, mean, maximum)) or not minimum <= mean <= maximum:
                raise ValueError('Invalid index')
            records.append({'valid_at': when.isoformat(), 'minimum': minimum, 'mean': mean,
                            'maximum': maximum, 'future_time': when > now})
        records.sort(key=lambda r: r['valid_at'])
        past = [r for r in records if not r['future_time']]
        if not records:
            return unavailable
        current = past[-1] if past else None
        age = (now - datetime.fromisoformat(current['valid_at'])).total_seconds() / 60 if current else None
        return {'available': True, 'source': 'nifos', 'region_code': 27, 'region': '대구광역시',
                'fetched_at': now.isoformat(), 'current': current,
                'age_minutes': round(age, 1) if age is not None else None,
                'fresh': age is not None and 0 <= age <= 360,
                'forecasts': [r for r in records if r['future_time']],
                'message': '시도 단위 산불위험지수입니다. 화재 확률·확산 속도가 아닙니다. analdate를 자료 기준시각으로 표시하며 공식 발표시각은 제공받지 않았습니다.'}
    except (KeyError, ValueError, TypeError, IndexError, OverflowError):
        return unavailable


class DangerClient:
    def __init__(self):
        self.cache = None
        self.lock = asyncio.Lock()

    def snapshot(self):
        if not self.cache:
            return {'available': False, 'source': 'nifos', 'message': '아직 위험지수를 조회하지 않았습니다.'}
        data = dict(self.cache[1])
        now = datetime.now(timezone.utc)
        if data.get('available'):
            records = ([data['current']] if data.get('current') else []) + data.get('forecasts', [])
            past = [r for r in records if datetime.fromisoformat(r['valid_at']) <= now]
            data['current'] = {**past[-1], 'future_time': False} if past else None
            data['forecasts'] = [r for r in records if datetime.fromisoformat(r['valid_at']) > now]
        if data.get('current'):
            age = (now - datetime.fromisoformat(data['current']['valid_at'])).total_seconds() / 60
            data.update(age_minutes=round(age, 1), fresh=0 <= age <= 360)
        return data

    async def observation(self):
        key = os.getenv('NIFOS_SERVICE_KEY', '').strip()
        if not key:
            return {'available': False, 'source': 'nifos', 'message': '서버 .env의 NIFOS_SERVICE_KEY가 필요합니다.'}
        async with self.lock:
            if self.cache and time.monotonic() - self.cache[0] < 600:
                return {**self.snapshot(), 'cached': True}
            data = {'available': False, 'source': 'nifos', 'message': '산불위험예보 연결 실패입니다. 확산 계산에는 영향을 주지 않습니다.'}
            try:
                async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
                    response = await client.get(ENDPOINT, params={'ServiceKey': unquote(key), 'pageNo': 1,
                        'numOfRows': 100, '_type': 'json', 'localAreas': '27', 'excludeForecast': 0})
                    if response.status_code == 200:
                        data = parse_danger(response.json())
            except (httpx.HTTPError, ValueError):
                pass
            self.cache = time.monotonic(), data
            return data
