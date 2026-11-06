"""UTIC Daegu preview: authenticated official workflow, no background AI/evidence.

Only the issued catalog and its official per-camera/player endpoints are used.
Provider credentials/cookies/metadata passwords never leave the backend.
"""
import asyncio
import base64
import hashlib
import html
from html.parser import HTMLParser
from io import BytesIO
import json
import logging
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import quote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

import httpx
from fastapi import Depends, HTTPException
from PIL import Image
from .config import ROOT
from .stream_reader import StreamError, fetch_bytes, media_segment, decode_segment

OFFICIAL = "https://www.utic.go.kr"
MEDIA_HOST = "carcctv.daegu.go.kr"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def read_catalog(path):
    """Read the issued local XLSX, not 14k per-camera metadata requests."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 5_000_000:
        raise HTTPException(503, "UTIC 좌표 목록 파일이 없거나 크기 제한을 초과했습니다.")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 100 or sum(i.file_size for i in infos) > 50_000_000:
                raise ValueError("oversized workbook")
            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                strings = ["".join(si.itertext()) for si in root.findall("m:si", NS)]
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            rels = {e.attrib["Id"]: e.attrib["Target"] for e in
                    ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
            records, invalid, seen, total = [], 0, set(), 0
            for sheet in workbook.findall("m:sheets/m:sheet", NS):
                rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
                target = rels[rid].lstrip("/")
                if not target.startswith("xl/"):
                    target = "xl/" + target
                if ".." in target.split("/"):
                    raise ValueError("invalid relationship")
                data = ET.fromstring(archive.read(target))
                headers = None
                for row in data.findall("m:sheetData/m:row", NS):
                    cells = {}
                    for cell in row.findall("m:c", NS):
                        col = re.sub(r"\d", "", cell.attrib["r"])
                        val = cell.find("m:v", NS)
                        value = val.text if val is not None else ""
                        if cell.attrib.get("t") == "s":
                            value = strings[int(value)] if value else ""
                        elif cell.attrib.get("t") == "inlineStr":
                            value = "".join(cell.find("m:is", NS).itertext())
                        cells[col] = value
                    if not any(cells.values()):
                        continue
                    if headers is None:
                        headers = cells
                        if not {"CCTVID", "CCTVNAME", "CENTERNAME", "XCOORD", "YCOORD"} <= set(headers.values()):
                            raise ValueError("missing catalog columns")
                        continue
                    total += 1
                    if total > 30_000:
                        raise ValueError("too many records")
                    source = {headers.get(k, k): v for k, v in cells.items()}
                    try:
                        lng, lat = float(source["XCOORD"]), float(source["YCOORD"])
                        if not (math.isfinite(lng) and math.isfinite(lat) and -180 <= lng <= 180 and -90 <= lat <= 90):
                            raise ValueError("invalid coordinates")
                        identity = source["CCTVID"]
                        if not re.fullmatch(r"E100\d{3}", identity) or source["CENTERNAME"] != "대구교통정보센터":
                            continue
                        if not (128.35 <= lng <= 128.85 and 35.60 <= lat <= 36.10) or identity in seen:
                            invalid += 1
                            continue
                        seen.add(identity)
                        records.append({"id": identity, "name": source["CCTVNAME"][:80],
                                        "center": source["CENTERNAME"], "longitude": lng, "latitude": lat,
                                        "provider": "utic"})
                    except (KeyError, ValueError, TypeError):
                        invalid += 1
            return records, total, invalid
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "UTIC 좌표 목록 형식을 확인하세요. 원본 XLSX는 수정하지 않았습니다.") from None


class CatalogLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.identities = set()

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href", "")
        match = re.fullmatch(r"javascript:test\(['\"]([A-Za-z0-9_-]{1,24})['\"]\);?", href)
        if match:
            self.identities.add(match[1])


def player_source(page, key):
    """Accept exactly the Daegu player's literal videoSrc, never arbitrary JS."""
    sources = re.findall(r"\bvar\s+videoSrc\s*=\s*(['\"])(.*?)\1\s*;", page, re.S)
    if len(sources) != 1:
        raise HTTPException(502, "UTIC 공식 플레이어 형식이 바뀌었거나 이 지점은 지원하지 않습니다.")
    url = html.unescape(sources[0][1])
    try:
        p = urlsplit(url)
        if (p.scheme != "https" or p.hostname != MEDIA_HOST or p.port not in (None, 443)
                or p.username or p.password or p.query or p.fragment or len(url) > 2048
                or not re.fullmatch(r"/live\d+/_definst_/ch\d+\.stream/playlist\.m3u8", p.path)
                or key in url):
            raise ValueError("unsupported source")
    except ValueError:
        raise HTTPException(502, "허용된 대구 HTTPS HLS 형식이 아닙니다. 다른 지점은 아직 지원하지 않습니다.") from None
    return url


def probe_frame(identity, url):
    """Existing pinned-IP/pipe-only decoder, fixed provider host, one frame."""
    stats = {"video_http_attempts": 0, "video_success_bytes": 0}
    hosts = {MEDIA_HOST}
    for _ in range(3):
        metadata = {}
        playlist = fetch_bytes(url, hosts, 512_000, stats=stats, metadata=metadata)
        kind, target = media_segment(playlist.decode("utf-8-sig"), metadata["url"])
        if kind == "segment":
            segment = fetch_bytes(target, hosts, 12_000_000, stats=stats)
            frame = decode_segment(segment)
            with Image.open(BytesIO(frame)) as image:
                width, height = image.size
            return {"decoded": True, "width": width, "height": height, "jpeg_bytes": len(frame),
                    "frame_base64": base64.b64encode(frame).decode("ascii"),
                    "http_requests": stats["video_http_attempts"], "ai_analysis": False,
                    "evidence_saved": False}
        url = target
    raise StreamError("중첩 HLS 목록 한도를 초과했습니다.")


class UticProvider:
    def __init__(self, transport=None):
        self.transport = transport
        self.cookies = httpx.Cookies()
        self.lock = asyncio.Lock()
        self.probe_lock = asyncio.Lock()
        self.catalog_cache = None
        self.catalog_attempt = -1e12
        self.authorized_at = -1e12
        self.fingerprint = None
        self.streams = {}
        self.stream_attempts = {}
        self.probe_attempts = {}

    @property
    def key(self):
        key = os.getenv("UTIC_API_KEY", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
            raise HTTPException(503, "서버 UTIC_API_KEY 설정이 필요합니다. 등록 공인 IP에서 실행하세요.")
        return key

    def synchronize_key(self):
        stamp = hashlib.sha256(self.key.encode()).digest()
        if stamp != self.fingerprint:
            self.fingerprint = stamp
            self.cookies = httpx.Cookies()
            self.catalog_cache = None
            self.authorized_at = -1e12
            self.streams.clear()
            self.stream_attempts.clear()
            self.catalog_attempt = -1e12

    async def request(self, path, params, *, referer=False, limit=2_000_000):
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False, transport=self.transport,
                                         cookies=self.cookies) as client:
                headers = {"User-Agent": "Mozilla/5.0"}
                if referer:
                    headers.update({"Referer": str(httpx.URL(OFFICIAL + "/guide/cctvOpenData.do",
                                              params={"key": self.key})), "X-Requested-With": "XMLHttpRequest"})
                async with client.stream("GET", OFFICIAL + path, params=params, headers=headers) as response:
                    if response.status_code != 200:
                        raise HTTPException(502, f"UTIC 응답 오류 ({response.status_code}). 등록 IP·키·기관 상태를 확인하세요.")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > limit:
                            raise HTTPException(502, "UTIC 응답 크기 한도를 초과했습니다.")
                    self.cookies.update(client.cookies)
                    return bytes(data)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, "UTIC 연결 실패입니다. 등록 공인 IP·기관 상태를 확인하세요.") from None

    async def catalog(self, refresh=False):
        async with self.lock:
            self.synchronize_key()
            now = time.monotonic()
            if self.catalog_cache and now - self.catalog_cache[0] < 86400 and not refresh:
                return self.catalog_cache[1]
            if now - self.catalog_attempt < 60:
                if self.catalog_cache:
                    return self.catalog_cache[1]
                raise HTTPException(429, "UTIC 목록은 최소 60초 뒤 다시 조회하세요.")
            path = Path(os.getenv("UTIC_CATALOG_PATH", str(ROOT / "runtime/external-data/cctv/OpenDataCCTV.xlsx")))
            rows, total, invalid = await asyncio.to_thread(read_catalog, path)
            self.catalog_attempt = now
            raw = await self.request("/guide/cctvOpenData.do", {"key": self.key}, limit=20_000_000)
            parser = CatalogLinks()
            parser.feed(raw.decode("utf-8", errors="replace"))
            if not parser.identities:
                raise HTTPException(502, "UTIC 목록 접근을 확인할 수 없습니다. 키·등록 IP·응답 형식을 확인하세요.")
            items = [r for r in rows if r["id"] in parser.identities]
            result = {"items": items, "fetched_at": time.time(), "source_total": total,
                      "source_invalid_coordinates": invalid, "local_daegu_count": len(rows),
                      "missing_from_live_list": len(rows) - len(items), "provider": "utic",
                      "region": "대구교통정보센터·좌표 목록 범위", "cache_seconds": 86400,
                      "ai_enabled": False, "max_preview_seconds": 60}
            self.authorized_at = time.monotonic()
            self.catalog_cache = (self.authorized_at, result)
            return result

    def find(self, identity):
        if not self.catalog_cache or time.monotonic() - self.catalog_cache[0] >= 86400:
            raise HTTPException(404, "UTIC 대구 목록을 먼저 조회하세요.")
        for item in self.catalog_cache[1]["items"]:
            if item["id"] == identity:
                return item
        raise HTTPException(404, "조회한 대구 목록에 없는 CCTV입니다.")

    async def stream(self, identity):
        async with self.lock:
            self.synchronize_key()
            item = self.find(identity)
            now = time.monotonic()
            cached = self.streams.get(identity)
            if cached and now - cached[0] < 55:
                return {**cached[1], "max_preview_seconds": max(1, int(60 - (now - cached[0])))}
            if now - self.stream_attempts.get(identity, -1e12) < 60:
                raise HTTPException(429, "이 카메라의 재생 확인은 최소 60초 간격입니다.")
            self.stream_attempts[identity] = now
            try:
                meta = json.loads(await self.request("/map/getCctvInfoById.do", {"cctvId": identity}, referer=True))
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(502, "UTIC 카메라 정보 형식이 다릅니다.") from None
            if not isinstance(meta, dict) or meta.get("CCTVID") != identity or meta.get("KIND") != "H" or meta.get("MOVIE") != "Y":
                raise HTTPException(502, "UTIC 대구 재생 정보를 확인할 수 없습니다. 중단·등록 IP·기관 응답을 확인하세요.")
            params = {"key": self.key, "cctvid": identity, "cctvName": quote(str(meta.get("CCTVNAME", ""))),
                      "kind": "H", "cctvip": meta.get("CCTVIP"), "cctvch": meta.get("CH"),
                      "id": meta.get("ID"), "cctvpasswd": meta.get("PASSWD"), "cctvport": meta.get("PORT")}
            raw = await self.request("/jsp/map/openDataCctvStream.jsp",
                                     {k: "null" if v is None else v for k, v in params.items()}, referer=True)
            url = player_source(raw.decode("utf-8", errors="replace"), self.key)
            result = {"url": url, "video_type": 4, "name": item["name"], "provider": "utic",
                      "max_preview_seconds": 60, "ai_enabled": False}
            self.streams[identity] = (time.monotonic(), result)
            return result

    async def probe(self, identity):
        if self.probe_lock.locked():
            raise HTTPException(409, "서버에서 다른 UTIC 단일 프레임을 확인 중입니다.")
        async with self.probe_lock:
            now = time.monotonic()
            if now - self.probe_attempts.get(identity, -1e12) < 60:
                raise HTTPException(429, "단일 프레임 확인은 카메라별 최소 60초 간격입니다.")
            self.probe_attempts[identity] = now
            stream = await self.stream(identity)
            try:
                result = await asyncio.to_thread(probe_frame, identity, stream["url"])
                return {**result, "name": stream["name"], "checked_at": time.time()}
            except Exception:
                raise HTTPException(502, "UTIC 영상 프레임 수신 실패입니다. 기관 연결·형식·IP 제한을 확인하세요. 반복 자동 접속하지 않습니다.") from None


def register_utic_routes(app, user, limiter):
    provider = UticProvider()
    app.state.utic = provider

    @app.get("/api/utic/config")
    def config(owner=Depends(user)):
        return {"configured": bool(os.getenv("UTIC_API_KEY", "").strip()), "ai_enabled": False,
                "max_preview_seconds": 60, "region": "대구교통정보센터"}

    @app.get("/api/utic/catalog")
    async def catalog(refresh: bool = False, owner=Depends(user)):
        limiter.check("utic-catalog:" + owner.id, 6, 60)
        return await provider.catalog(refresh)

    @app.get("/api/utic/{identity}/stream")
    async def stream(identity: str, owner=Depends(user)):
        limiter.check("utic-stream:" + owner.id, 12, 60)
        return await provider.stream(identity)

    @app.post("/api/utic/{identity}/probe")
    async def probe(identity: str, owner=Depends(user)):
        limiter.check("utic-probe:" + owner.id, 4, 60)
        return await provider.probe(identity)

    return provider
