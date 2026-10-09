"""Small, opt-in live verification. Never print keys or credentialed URLs."""
import asyncio
import json
from pathlib import Path
import sys
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.config import Settings
from app.providers import Providers
from fastapi import HTTPException


async def main():
    Settings.from_env()
    p = Providers()
    report = {'naver_id_set': bool(p.credentials[0]), 'naver_secret_set': bool(p.credentials[1]),
              'its_key_set': bool(os.getenv('ITS_API_KEY'))}
    for name, path, params in [
        ('geocode', 'map-geocode/v2/geocode', {'query':'대구광역시 남구 봉덕동','count':1}),
        ('reverse', 'map-reversegeocode/v2/gc', {'coords':'128.592251,35.813648','output':'json','orders':'legalcode,addr'})]:
        try:
            r = await p.geocode(path, params)
            report[name] = {'status':r.get('status'), 'count':len(r.get('addresses', r.get('results', [])))}
        except HTTPException as exc:
            report[name] = {'http_status':exc.status_code,'message':exc.detail}
    try:
        r = await p.catalog('ex', 4)
        report['its_catalog'] = {'count':len(r['items']), 'video_type':4, 'road':'ex', 'region':'Daegu bounding box'}
    except HTTPException as exc:
        report['its_catalog'] = {'http_status':exc.status_code,'message':exc.detail}
    (ROOT / 'runtime' / 'maps-cctv-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    asyncio.run(main())
