"""KMA observations with explicit freshness, no secret-bearing error messages."""
from datetime import datetime, timedelta, timezone
from math import sin, cos, tan, atan, log, floor, pi
import asyncio
import os
import time
from urllib.parse import unquote
import httpx
import logging

# httpx's INFO request log contains query credentials. Never enable it here.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

KST = timezone(timedelta(hours=9))
ENDPOINT = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"


def kma_grid(lat: float, lon: float):
    """Official DFS Lambert grid, 5 km, WGS84 latitude/longitude."""
    rad = pi / 180
    a, b = 30 * rad, 60 * rad
    sn = log(cos(a) / cos(b)) / log(tan(pi / 4 + b / 2) / tan(pi / 4 + a / 2))
    sf = tan(pi / 4 + a / 2) ** sn * cos(a) / sn
    ro = (6371.00877 / 5) * sf / tan(pi / 4 + 38 * rad / 2) ** sn
    ra = (6371.00877 / 5) * sf / tan(pi / 4 + lat * rad / 2) ** sn
    theta = (lon - 126) * rad
    theta = (theta + pi) % (2 * pi) - pi
    theta *= sn
    return floor(ra * sin(theta) + 43 + .5), floor(ro - ra * cos(theta) + 136 + .5)


def parse_observation(body, nx, ny, fetched_at=None):
    fetched_at = fetched_at or datetime.now(timezone.utc)
    try:
        response = body["response"]
        if str(response["header"]["resultCode"]) != "00":
            code = str(response["header"]["resultCode"])
            code = code if code.isdigit() and len(code) <= 3 else "unknown"
            return {"available": False, "source": "kma", "error_code": code,
                    "message": "기상청 응답 오류입니다. 인증·승인 상태 또는 발표 시각을 확인하세요."}
        items = response["body"]["items"]["item"]
        if isinstance(items, dict):
            items = [items]
        categories = {x["category"]: float(x["obsrValue"]) for x in items}
        required = {"T1H", "REH", "WSD", "VEC", "RN1"}
        if not required <= categories.keys():
            raise ValueError("Missing categories")
        if not (-60 <= categories["T1H"] <= 60 and 0 <= categories["REH"] <= 100
                and 0 <= categories["WSD"] <= 100 and 0 <= categories["VEC"] <= 360
                and 0 <= categories["RN1"] <= 1000):
            raise ValueError("Invalid observation")
        first = items[0]
        observed = datetime.strptime(str(first["baseDate"]) + str(first["baseTime"]).zfill(4),
                                     "%Y%m%d%H%M").replace(tzinfo=KST).astimezone(timezone.utc)
        if any(str(x["baseDate"]) != str(first["baseDate"]) or str(x["baseTime"]) != str(first["baseTime"])
               for x in items):
            raise ValueError("Mixed observation times")
        age = (fetched_at - observed).total_seconds() / 60
        fresh = -5 <= age <= 120
        return {"available": True, "source": "kma", "fresh": fresh,
                "quality": "grid_representative" if fresh else "stale",
                "observed_at": observed.isoformat(), "fetched_at": fetched_at.isoformat(),
                "age_minutes": round(age, 1), "grid": {"nx": nx, "ny": ny},
                "temperature_c": categories["T1H"], "humidity_pct": categories["REH"],
                "wind_speed_ms": categories["WSD"], "wind_from_deg": categories["VEC"] % 360,
                "wind_to_deg": (categories["VEC"] + 180) % 360, "rain_mm": categories["RN1"],
                "message": "5km 격자 대표 관측값입니다. 산림 내부의 실제 바람·연료 수분과 다를 수 있습니다."}
    except (KeyError, ValueError, TypeError, IndexError):
        return {"available": False, "source": "kma", "message": "기상청 자료가 없거나 값·형식이 유효하지 않습니다."}


class WeatherClient:
    def __init__(self):
        self.cache = {}
        self.lock = asyncio.Lock()

    async def observation(self, lat, lon):
        key = os.getenv("KMA_SERVICE_KEY", "").strip()
        if not key:
            return {"available": False, "source": "kma", "message": "서버 .env의 KMA_SERVICE_KEY가 필요합니다."}
        nx, ny = kma_grid(lat, lon)
        async with self.lock:
            cached = self.cache.get((nx, ny))
            if cached and time.monotonic() - cached[0] < 300:
                data = dict(cached[1])
                data["cached"] = True
                if data.get("available"):
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(data["observed_at"])).total_seconds() / 60
                    data["age_minutes"] = round(age, 1)
                    data["fresh"] = -5 <= age <= 120
                    data["quality"] = "grid_representative" if data["fresh"] else "stale"
                return data
            result = {"available": False, "source": "kma", "message": "기상청에 연결하지 못했습니다. 수동 시나리오만 사용할 수 있습니다."}
            # Hourly observations may not yet be published. Fetch <= 3 recent hours.
            base = (datetime.now(KST) - timedelta(minutes=45)).replace(minute=0, second=0, microsecond=0)
            async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
                for offset in range(3):
                    dt = base - timedelta(hours=offset)
                    try:
                        response = await client.get(ENDPOINT, params={"ServiceKey": unquote(key),
                            "pageNo": 1, "numOfRows": 1000, "dataType": "JSON",
                            "base_date": dt.strftime("%Y%m%d"), "base_time": dt.strftime("%H00"), "nx": nx, "ny": ny})
                        if response.status_code != 200:
                            result["error_code"] = str(response.status_code)
                            break
                        result = parse_observation(response.json(), nx, ny)
                        if result.get("available") or result.get("error_code") not in (None, "03"):
                            break
                    except (httpx.HTTPError, ValueError):
                        break  # Never expose the exception: URLs include the key.
            self.cache[(nx, ny)] = (time.monotonic(), result)
            return result
