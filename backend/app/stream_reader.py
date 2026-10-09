"""Bounded HLS sampling. FFmpeg receives bytes only, never a network URL.
All nested URLs require explicit host allowlisting and a pinned public IP.
No redirects, cookies, HTTP auth, encryption/DRM or access-control bypass.
"""
import http.client
import ipaddress
import os
import socket
import ssl
import subprocess
import time
from urllib.parse import urlsplit, urljoin
from .providers import Providers

class StreamError(Exception):
    pass

def safe_target(url, allowed_hosts):
    if not Providers.public_stream(url) or len(url)>4096:
        raise StreamError("허용되지 않은 영상 주소입니다.")
    p=urlsplit(url)
    if p.hostname.lower() not in allowed_hosts:
        raise StreamError("영상 호스트가 서버 허용 목록에 없습니다.")
    try:
        records=socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=="https" else 80),
                                   type=socket.SOCK_STREAM)
        ips=list(dict.fromkeys(r[4][0] for r in records))
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise StreamError("공개 IP가 아닌 영상 주소는 연결하지 않습니다.")
        return p,ips[0]
    except OSError:
        raise StreamError("영상 호스트 DNS 확인 실패입니다.") from None

def fetch_bytes(url, allowed_hosts, limit, redirects=2, stats=None, metadata=None):
    p,ip=safe_target(url,allowed_hosts)
    if stats is not None:
        stats["video_http_attempts"]+=1
    port=p.port or (443 if p.scheme=="https" else 80)
    connection=http.client.HTTPConnection(p.hostname,port,timeout=5)
    deadline=time.monotonic()+10
    try:
        # Pin the checked IP while retaining original Host and TLS SNI verification.
        sock=socket.create_connection((ip,port),timeout=5)
        if p.scheme=="https":
            try:
                sock=ssl.create_default_context().wrap_socket(sock,server_hostname=p.hostname)
            except Exception:
                sock.close()
                raise
        connection.sock=sock
        connection.request("GET",p.path+("?" + p.query if p.query else ""),
                           headers={"User-Agent":"Ember-Research/1.0","Accept-Encoding":"identity",
                                    "Connection":"close"})
        response=connection.getresponse()
        if response.status in (301,302,303,307,308):
            target=urljoin(url,response.getheader("Location") or "")
            next_url=urlsplit(target)
            if (redirects<=0 or not response.getheader("Location") or
                next_url.hostname!=p.hostname or next_url.scheme not in (p.scheme,"https") or
                not Providers.public_stream(target)):
                raise StreamError("영상 주소 이동이 동일 호스트·HTTPS 안전 조건을 벗어났습니다.")
            connection.close()
            return fetch_bytes(target,allowed_hosts,limit,redirects-1,stats,metadata)
        if response.status!=200:
            raise StreamError(f"제공기관 영상 응답 오류 ({response.status})입니다. 반복 접속하지 않고 대기합니다.")
        length=response.getheader("Content-Length")
        if length and (not length.isdecimal() or int(length)>limit):
            raise StreamError("영상 응답 크기 한도를 초과했습니다.")
        data=bytearray()
        while True:
            if time.monotonic()>deadline:
                raise StreamError("영상 읽기 시간 초과입니다.")
            chunk=response.read(min(65536,limit+1-len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data)>limit:
                raise StreamError("영상 응답 크기 한도를 초과했습니다.")
        if stats is not None:
            stats["video_success_bytes"]+=len(data)
        if metadata is not None:
            metadata["url"]=url
        return bytes(data)
    except StreamError:
        raise
    except Exception:
        raise StreamError("영상 연결 실패입니다. 제공기관 권한·연결 상태를 확인하세요.") from None
    finally:
        connection.close()

def media_segment(text, base):
    if not text.startswith("#EXTM3U"):
        raise StreamError("HLS 목록 형식이 아닙니다.")
    lines=[l.strip() for l in text.splitlines() if l.strip()]
    if any(l.startswith(("#EXT-X-KEY:","#EXT-X-MAP:","#EXT-X-BYTERANGE:","#EXT-X-ENDLIST")) for l in lines):
        raise StreamError("암호화·fMP4·부분 범위·종료 영상은 상시 수집 대상에서 제외합니다.")
    entries=[l for l in lines if not l.startswith("#")]
    if not entries:
        raise StreamError("영상 목록에 조각이 없습니다.")
    if any(l.startswith("#EXT-X-STREAM-INF:") for l in lines):
        return "master",urljoin(base,entries[0])
    if not any(l.startswith("#EXTINF:") for l in lines):
        raise StreamError("HLS 재생 목록에 시간 정보가 없습니다.")
    return "segment",urljoin(base,entries[-1])

class HlsReader:
    def __init__(self):
        self.last={}
        self.stats={}
        self.playlists={}

    def measured_fetch(self, identity, url, hosts, limit):
        stats=self.stats.setdefault(identity,{"video_http_attempts":0,"video_success_bytes":0})
        metadata={}
        data=fetch_bytes(url,hosts,limit,stats=stats,metadata=metadata)
        return data,metadata["url"]

    @property
    def allowed_hosts(self):
        return {v.strip().lower() for v in os.getenv("EMBER_STREAM_ALLOWED_HOSTS","").split(",") if v.strip()}

    def read(self, identity, url):
        hosts=self.allowed_hosts
        original_url=url
        cached=self.playlists.get(identity)
        if cached and cached[0]==original_url:
            url=cached[1]
        for _ in range(3):
            data,resolved_url=self.measured_fetch(identity,url,hosts,512000)
            kind,target=media_segment(data.decode("utf-8-sig"),resolved_url)
            if kind=="segment":
                # Keep the authorized media playlist, as an HLS player does.
                # Repeatedly reopening the ticket/redirect entry can be rejected.
                self.playlists[identity]=(original_url,resolved_url)
                break
            url=target
        else:
            raise StreamError("중첩 영상 목록 한도를 초과했습니다.")
        if self.last.get(identity)==target:
            return None
        segment,_=self.measured_fetch(identity,target,hosts,12_000_000)
        frame=decode_segment(segment)
        self.last[identity]=target
        return frame

def decode_segment(segment):
    import imageio_ffmpeg
    binary=imageio_ffmpeg.get_ffmpeg_exe()
    # Forced MPEG-TS demux, pipe-only protocol. Nested media cannot fetch network/file.
    args=[binary,"-hide_banner","-loglevel","error","-threads","1",
          "-protocol_whitelist","pipe","-f","mpegts","-i","pipe:0",
          "-map","0:v:0","-frames:v","1","-an",
          "-vf","scale=1280:720:force_original_aspect_ratio=decrease",
          "-threads","1","-f","image2pipe","-vcodec","mjpeg","pipe:1"]
    try:
        result=subprocess.run(args,input=segment,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                              timeout=12,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        if result.returncode or not result.stdout or len(result.stdout)>2_000_000:
            raise StreamError("영상 프레임 해석 실패입니다.")
        return result.stdout
    except (OSError,subprocess.TimeoutExpired):
        raise StreamError("영상 디코더 실행 실패 또는 시간 초과입니다.") from None
