"""Authenticated official providers. Never fetch caller-supplied URLs or proxy video."""
import asyncio
import hashlib
import ipaddress
import logging
import os
import time
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, HTTPException, Query

# ITS authentication is in the fixed API query. Prevent verbose HTTP client URL logs.
logging.getLogger('httpx').setLevel(logging.WARNING)


class Providers:
    def __init__(self, transport=None):
        self.transport = transport
        self.catalogs = {}
        self.last_attempt = {}
        self.lock = asyncio.Lock()

    @property
    def credentials(self):
        return os.getenv("NAVER_MAPS_CLIENT_ID", ""), os.getenv("NAVER_MAPS_CLIENT_SECRET", "")

    async def request(self, url, *, params, headers=None):
        # Fixed official endpoints only; do not log exception URLs (ITS key in query).
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False, transport=self.transport) as client:
                async with client.stream("GET", url, params=params, headers=headers) as response:
                    if response.status_code != 200:
                        raise HTTPException(502, f"제공기관 응답 오류 ({response.status_code}). 키·권한·사용량을 확인하세요.")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 4_000_000:
                            raise HTTPException(502, "제공기관 응답 크기가 한도를 초과했습니다.")
                    import json
                    return json.loads(content)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, "제공기관 연결 또는 응답 해석 실패입니다. 잠시 후 다시 확인하세요.") from None

    async def geocode(self, path, params):
        key_id, secret = self.credentials
        if not key_id or not secret:
            raise HTTPException(503, "서버에 네이버 지도 ID·Secret 설정이 필요합니다.")
        return await self.request("https://maps.apigw.ntruss.com/" + path, params=params,
                                  headers={"x-ncp-apigw-api-key-id": key_id,
                                           "x-ncp-apigw-api-key": secret, "Accept": "application/json"})

    @staticmethod
    def public_stream(url):
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
                return False
            host = parsed.hostname.lower()
            if host == "localhost" or "." not in host or host.endswith((".local", ".localhost", ".internal")):
                return False
            try:
                if not ipaddress.ip_address(host).is_global:
                    return False
            except ValueError:
                pass
            if parsed.port not in (None, 80, 443, 8080, 8081, 8082, 8443):
                return False
            return True
        except ValueError:
            return False

    async def catalog(self, road, video_type, refresh=False):
        key = (road, video_type)
        async with self.lock:
            now = time.monotonic()
            cached = self.catalogs.get(key)
            if cached and now - cached[0] < 86400 and not refresh:
                return cached[1]
            if now - self.last_attempt.get(key, -1e12) < 60:
                if cached:
                    return cached[1]
                raise HTTPException(429, "CCTV 목록은 같은 조건으로 최소 60초 뒤 재조회하세요.")
            api_key = os.getenv("ITS_API_KEY", "")
            if not api_key:
                raise HTTPException(503, "서버 ITS_API_KEY 설정이 필요합니다.")
            self.last_attempt[key] = now
            payload = await self.request("https://openapi.its.go.kr:9443/cctvInfo", params={
                "apiKey": api_key, "type": road, "cctvType": str(video_type), "getType": "json",
                "minX": "128.35", "maxX": "128.85", "minY": "35.60", "maxY": "36.10"})
            response = payload.get("response", {})
            data = response.get("data")
            if not isinstance(data, list):
                raise HTTPException(502, "ITS 목록 형식이 다릅니다. 인증 승인·응답 상태를 확인하세요.")
            items = []
            for row in data[:1000]:
                try:
                    lng, lat = float(row["coordx"]), float(row["coordy"])
                    name, url = str(row["cctvname"])[:80], str(row["cctvurl"])
                    if not (128.35 <= lng <= 128.85 and 35.60 <= lat <= 36.10):
                        continue
                    if not self.public_stream(url) or api_key in url:
                        continue
                    identity = hashlib.sha256(f"{road}|{video_type}|{name}|{lng}|{lat}".encode()).hexdigest()[:24]
                    items.append({"id": identity, "name": name, "longitude": lng, "latitude": lat,
                                  "video_type": video_type, "road": road, "url": url})
                except (KeyError, TypeError, ValueError):
                    continue
            self.catalogs[key] = (now, {"items": items, "fetched_at": time.time()})
            return self.catalogs[key][1]

    def find(self, identity):
        for stamp, catalog in self.catalogs.values():
            if time.monotonic() - stamp > 86400:
                continue
            for item in catalog["items"]:
                if item["id"] == identity:
                    return item
        raise HTTPException(404, "CCTV 목록을 먼저 조회하세요. 목록은 하루 뒤 만료됩니다.")


def register_provider_routes(app, user, limiter):
    providers = Providers()
    app.state.providers = providers

    @app.get("/api/maps/config")
    def config(owner=Depends(user)):
        key_id, secret = providers.credentials
        # The JS SDK ID is intentionally public. The Secret never leaves the server.
        return {"enabled": bool(key_id), "client_id": key_id,
                "geocoding": bool(key_id and secret), "its": bool(os.getenv("ITS_API_KEY"))}

    @app.get("/api/maps/geocode")
    async def geocode(query: str = Query(min_length=2, max_length=200), owner=Depends(user)):
        limiter.check("geocode:" + owner.id, 20, 60)
        result = await providers.geocode("map-geocode/v2/geocode", {"query": query, "count": 5})
        if result.get("status") != "OK":
            raise HTTPException(502, "주소 검색 응답 오류입니다.")
        return {"items": [{"address": r.get("roadAddress") or r.get("jibunAddress"),
                           "latitude": float(r["y"]), "longitude": float(r["x"])}
                          for r in result.get("addresses", [])]}

    @app.get("/api/maps/reverse")
    async def reverse(latitude: float = Query(ge=33, le=39), longitude: float = Query(ge=124, le=132), owner=Depends(user)):
        limiter.check("reverse:" + owner.id, 20, 60)
        result = await providers.geocode("map-reversegeocode/v2/gc", {
            "coords": f"{longitude},{latitude}", "output": "json", "orders": "legalcode,addr,roadaddr"})
        if result.get("status", {}).get("code") not in (0, 3):
            raise HTTPException(502, "좌표 주소 변환 응답 오류입니다.")
        addresses = []
        for r in result.get("results", []):
            region, land = r.get("region", {}), r.get("land", {})
            parts = [region.get(f"area{i}", {}).get("name", "") for i in range(1, 5)]
            if r.get("name") == "roadaddr":
                parts = parts[:2] + [land.get("name", "")]
            if land.get("number1"):
                parts.append(("산 " if land.get("type") == "2" else "") + land["number1"] +
                             ("-" + land["number2"] if land.get("number2") else ""))
            addresses.append(" ".join(p for p in parts if p))
        return {"address": addresses[-1] if addresses else None}

    @app.get("/api/cctv/catalog")
    async def catalog(road: str = "ex", video_type: int = 4, refresh: bool = False, owner=Depends(user)):
        if road not in ("ex", "its") or video_type not in (1, 2, 4, 5):
            raise HTTPException(422, "지원하지 않는 CCTV 조회 조건입니다.")
        limiter.check("catalog:" + owner.id, 12, 60)
        result = await providers.catalog(road, video_type, refresh)
        return {**result, "items": [{k: v for k, v in i.items() if k != "url"} for i in result["items"]],
                "region": "대구 주변 (행정구역 경계 아님)", "cache_seconds": 86400}

    @app.get("/api/cctv/{identity}/stream")
    def stream(identity: str, owner=Depends(user)):
        limiter.check("stream:" + owner.id, 20, 60)
        item = providers.find(identity)
        return {"url": item["url"], "video_type": item["video_type"], "name": item["name"]}

    return providers
