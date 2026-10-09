import {useEffect,useRef,useState} from 'react'
import Hls from 'hls.js'
import {api,json,dateTime} from './api'
import {Badge} from './components'
import type {FrameResult} from './types'
import NaverMap,{type MapCamera} from './NaverMap'
import './SpreadPage.css'
import './ProviderPages.css'
import MonitoringPanel from './MonitoringPanel'

type Item=MapCamera&{road:string;video_type:number}
type Catalog={items:Item[];fetched_at:number;region:string}
type Stream={url:string;video_type:number;name:string}
export default function CctvPage(){
  const [catalog,setCatalog]=useState<Catalog|null>(null),[selected,setSelected]=useState<Item|null>(null),[stream,setStream]=useState<Stream|null>(null)
  const [road,setRoad]=useState('ex'),[videoType,setVideoType]=useState(4),[search,setSearch]=useState(''),[busy,setBusy]=useState(false)
  const [error,setError]=useState(''),[playerMessage,setPlayerMessage]=useState(''),[consent,setConsent]=useState(false),[running,setRunning]=useState(false)
  const [frames,setFrames]=useState(0),[result,setResult]=useState<FrameResult|null>(null),[cameraId,setCameraId]=useState('')
  const video=useRef<HTMLVideoElement>(null),generation=useRef(0),selection=useRef(0),timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined)
  const hlsPlayer=useRef<Hls|null>(null)
  function stop(){generation.current++;clearTimeout(timer.current);setRunning(false)}
  useEffect(()=>()=>{generation.current++;selection.current++;clearTimeout(timer.current)},[])
  useEffect(()=>{const onVisibility=()=>{if(document.hidden){stop();video.current?.pause();hlsPlayer.current?.stopLoad()}};document.addEventListener('visibilitychange',onVisibility);return()=>document.removeEventListener('visibilitychange',onVisibility)},[])
  async function load(refresh=false){stop();const v=++selection.current;setBusy(true);setError('');setSelected(null);setStream(null);setCatalog(null)
    try{const c=await api<Catalog>(`/cctv/catalog?road=${road}&video_type=${videoType}&refresh=${refresh}`);if(v===selection.current)setCatalog(c)}
    catch(e){if(v===selection.current)setError((e as Error).message)}finally{if(v===selection.current)setBusy(false)}}
  async function choose(item:MapCamera){stop();const v=++selection.current;setSelected(item as Item);setStream(null);setResult(null);setFrames(0);setCameraId('');setConsent(false);setError('');setPlayerMessage('영상 주소 확인 중…')
    try{const s=await api<Stream>(`/cctv/${item.id}/stream`);if(v===selection.current){setStream(s);setPlayerMessage('재생 버튼을 눌러 영상을 확인하세요.')}}
    catch(e){if(v===selection.current)setError((e as Error).message)}}
  useEffect(()=>{
    const v=video.current;if(!v||!stream)return
    if(location.protocol==='https:'&&stream.url.startsWith('http:')){setPlayerMessage('이 영상은 HTTP 전용입니다. HTTPS 화면에서는 차단됩니다. HTTPS HLS/MP4 조건으로 다시 조회하세요.');return}
    let hls:Hls|undefined
    if(stream.video_type===1||stream.video_type===4){
      if(v.canPlayType('application/vnd.apple.mpegurl'))v.src=stream.url
      else if(Hls.isSupported()){
        hls=new Hls({enableWorker:false,lowLatencyMode:false,maxBufferLength:10,maxMaxBufferLength:20,
          manifestLoadingTimeOut:10000,levelLoadingTimeOut:10000,fragLoadingTimeOut:10000,
          manifestLoadingMaxRetry:1,levelLoadingMaxRetry:1,fragLoadingMaxRetry:1})
        hlsPlayer.current=hls
        hls.loadSource(stream.url);hls.attachMedia(v)
        hls.on(Hls.Events.ERROR,(_,data)=>{if(data.fatal){hls?.stopLoad();stop();setPlayerMessage('영상 연결 실패: 제공기관 중단·만료 또는 CORS 제한일 수 있습니다. 반복 재접속하지 말고 다른 지점을 선택하세요.')}})
      }else setPlayerMessage('이 브라우저는 HLS 재생을 지원하지 않습니다. MP4 조건을 선택하세요.')
    }else v.src=stream.url
    return()=>{hls?.destroy();hlsPlayer.current=null;v.pause();v.removeAttribute('src');v.load()}
  },[stream])
  async function start(){
    if(!selected||!consent||!video.current)return
    stop();const g=generation.current;setError('');setFrames(0);setResult(null)
    const selectedId=selected.id
    const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d')
    if(!ctx){setError('이 브라우저에서 프레임 추출을 지원하지 않습니다.');return}
    const expires=Date.now()+120000;let camera='',lastTime=-1
    async function tick(){
      if(g!==generation.current)return
      const v=video.current
      if(!v||document.hidden||Date.now()>expires){stop();return}
      try{
        if(v.paused||v.ended||v.readyState<2||v.currentTime===lastTime){timer.current=setTimeout(()=>void tick(),1500);return}
        canvas.width=Math.min(v.videoWidth,1280);canvas.height=Math.round(v.videoHeight*canvas.width/v.videoWidth)
        ctx!.drawImage(v,0,0,canvas.width,canvas.height);lastTime=v.currentTime
        const blob=await new Promise<Blob>((resolve,reject)=>{try{canvas.toBlob(b=>b?resolve(b):reject(new Error('프레임 변환 실패')),'image/jpeg',.8)}catch{reject(new Error('제공기관 CORS 정책으로 프레임 추출이 차단됐습니다. 재생과 AI 분석 가능 여부는 다릅니다. 승인된 edge 연결이 필요합니다.'))}})
        if(g!==generation.current)return
        if(!camera){const c=await api<{id:string}>(`/cctv/${selectedId}/register`,json('POST'));camera=c.id;if(g!==generation.current)return;setCameraId(c.id)}
        const r=await api<FrameResult>(`/cctv/cameras/${camera}/frames`,{method:'POST',body:blob})
        if(g!==generation.current)return
        setResult(r);setFrames(n=>n+1);timer.current=setTimeout(()=>void tick(),1500)
      }catch(e){if(g===generation.current){stop();setError((e as Error).message)}}
    }
    if(video.current.paused){setError('먼저 영상 재생 버튼을 누르세요.');return}
    setRunning(true);void tick()
  }
  const items=catalog?.items.filter(c=>c.name.toLowerCase().includes(search.toLowerCase()))||[]
  return <div><div className="notice info">출처: 국토교통부 국가교통정보센터(ITS). 고속도로·국도 CCTV · 대구 주변 선택 조회. UTIC는 신청 완료 · 승인 대기 · 아직 미연결입니다. 설치 좌표는 실제 발화 위치가 아닙니다.</div>
    {error&&<div className="notice error" role="alert">{error}</div>}
    <div className="cctv-layout"><section className="panel"><div className="section-heading"><h2>공공 CCTV 찾기</h2><Badge>ITS</Badge></div><div className="cctv-filter">
      <label>도로 종류<select value={road} onChange={e=>{stop();selection.current++;setBusy(false);setRoad(e.target.value);setCatalog(null);setSelected(null);setStream(null)}}><option value="ex">고속도로</option><option value="its">국도</option></select></label>
      <label>영상 형식<select value={videoType} onChange={e=>{stop();selection.current++;setBusy(false);setVideoType(Number(e.target.value));setCatalog(null);setSelected(null);setStream(null)}}><option value={4}>HTTPS HLS · 권장</option><option value={5}>HTTPS MP4</option><option value={1}>HTTP HLS · 로컬 테스트</option><option value={2}>HTTP MP4 · 로컬 테스트</option></select></label>
      <button className="button primary" disabled={busy} onClick={()=>void load()}>{busy?'조회 중…':'대구 주변 목록 조회'}</button></div>
      {catalog&&<><p className="cctv-meta">{catalog.items.length}개 · {dateTime(new Date(catalog.fetched_at*1000).toISOString())} 조회</p><input aria-label="CCTV 이름 검색" placeholder="지점 이름 검색" value={search} onChange={e=>setSearch(e.target.value)}/><div className="cctv-list">{items.map(c=><button className={selected?.id===c.id?'active':''} key={c.id} onClick={()=>void choose(c)}>{c.name}<small>{c.latitude.toFixed(5)}, {c.longitude.toFixed(5)}</small></button>)}</div>{!items.length&&<p className="small-muted">목록이 없습니다. 도로·영상 형식을 변경해 조회하세요.</p>}<button className="text-button" disabled={busy} onClick={()=>void load(true)}>제공기관 목록 갱신</button></>}
      <p className="cctv-meta">같은 조건 목록은 24시간 캐시, 강제 갱신은 최소 60초 간격입니다. 브라우저는 선택한 한 곳을 재생하고, 서버는 아래 등록·활성화한 CCTV를 별도로 분석합니다. 전체 목록 자동 수집이나 원본 영상 녹화는 하지 않습니다.</p></section>
    <section className="panel"><div className="section-heading"><h2>CCTV 설치 위치</h2><Badge>{catalog?.items.length||0}개</Badge></div><NaverMap showIgnition={false} point={selected||{latitude:35.85,longitude:128.60}} cameras={catalog?.items||[]} selectedCamera={selected?.id} onCamera={c=>void choose(c)}/></section></div>
    <section className="panel cctv-player-panel"><div className="section-heading"><h2>{selected?.name||'목록이나 지도에서 CCTV를 선택하세요'}</h2><Badge tone={running?'warning':'neutral'}>{running?'AI 분석 중':'분석 중지'}</Badge></div>
      {stream&&<video className="cctv-player" ref={video} controls playsInline muted crossOrigin="anonymous" preload="none" onPlay={()=>hlsPlayer.current?.startLoad()} onPause={()=>hlsPlayer.current?.stopLoad()} onPlaying={()=>setPlayerMessage('영상 재생 중 · AI 분석은 별도로 시작하세요.')} onError={()=>{stop();setPlayerMessage('영상 재생 실패입니다. 제공기관 상태·URL 만료·브라우저 접근 제한을 확인하세요.')}}/>}
      <p className="small-muted" role="status">{playerMessage||'자동 연결·자동 분석하지 않습니다.'}</p>
      {selected&&<><label className="cctv-consent"><input type="checkbox" checked={consent} disabled={running} onChange={e=>setConsent(e.target.checked)}/><span>신청 목적에 영상 AI 분석·증거 저장이 포함되며 제공기관 이용 조건을 확인했습니다. 후보 알람 발생 시 증거 이미지가 저장되는 연구용 테스트에 동의합니다. 사람·차량 개인정보와 보존 기간을 별도로 관리합니다.</span></label>
        <div className="button-row"><button className="button primary" disabled={!consent||!stream||running} onClick={()=>void start()}>프레임 AI 분석 · 최대 2분</button><button className="button" disabled={!running} onClick={stop}>분석 중지</button></div></>}
      <div className="cctv-result"><Badge tone={result?.fire_candidate?'warning':'neutral'}>{result?result.fire_candidate?'불꽃 후보':result.smoke_candidate?'연기 후보':'후보 없음':'아직 분석하지 않음'}</Badge><span>{frames}프레임 · {result?.latency_ms??'—'}ms</span></div>
      {result&&cameraId&&<img className="cctv-snapshot" src={`/api/cameras/${cameraId}/preview?v=${frames}`} alt="최근 CCTV 프레임 AI 분석 결과"/>}
      <p className="cctv-meta">이 버튼은 브라우저 2분 테스트입니다. 숨겨진 탭·페이지 이동 시 중지됩니다. 화면과 독립적인 분석은 아래 서버 상시 감시 설정을 사용하세요. 실제 산불 검증·자동 신고는 아닙니다.</p></section><MonitoringPanel selected={selected}/></div>
}
