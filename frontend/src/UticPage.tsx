import {useEffect,useRef,useState} from 'react'
import type Hls from 'hls.js'
import {api,json,dateTime} from './api'
import {Badge} from './components'
import NaverMap,{type MapCamera} from './NaverMap'
import './ProviderPages.css'

type Item=MapCamera&{center:string;provider:'utic'}
type Catalog={items:Item[];fetched_at:number;source_total:number;source_invalid_coordinates:number;missing_from_live_list:number;local_daegu_count:number}
type Stream={url:string;video_type:number;max_preview_seconds:number}
type Probe={decoded:boolean;width:number;height:number;jpeg_bytes:number;frame_base64:string;http_requests:number;checked_at:number;ai_analysis:false;evidence_saved:false}

function UticPlayer({stream,onStop}:{stream:Stream;onStop:()=>void}){
  const videoRef=useRef<HTMLVideoElement>(null),onStopRef=useRef(onStop)
  onStopRef.current=onStop
  const [message,setMessage]=useState('영상 연결 중…'),[remaining,setRemaining]=useState(stream.max_preview_seconds)
  useEffect(()=>{
    const video=videoRef.current!;let disposed=false,hls:Hls|undefined
    const deadline=Date.now()+Math.min(60,stream.max_preview_seconds)*1000
    const stop=()=>{video.pause();hls?.stopLoad();onStopRef.current()}
    const interval=setInterval(()=>{const seconds=Math.max(0,Math.ceil((deadline-Date.now())/1000));setRemaining(seconds);if(!seconds)stop()},1000)
    const visibility=()=>{if(document.hidden)stop()}
    document.addEventListener('visibilitychange',visibility)
    void (async()=>{
      if(video.canPlayType('application/vnd.apple.mpegurl'))video.src=stream.url
      else{
        const {default:Hls}=await import('hls.js');if(disposed)return
        if(!Hls.isSupported()){setMessage('이 브라우저에서 HLS를 지원하지 않습니다. 서버 프레임 시험을 사용하세요.');return}
        hls=new Hls({maxBufferLength:10,maxMaxBufferLength:15,manifestLoadingMaxRetry:0,levelLoadingMaxRetry:0,fragLoadingMaxRetry:0,
          manifestLoadingTimeOut:10000,levelLoadingTimeOut:10000,fragLoadingTimeOut:10000})
        hls.on(Hls.Events.ERROR,(_,data)=>{if(data.fatal){hls?.stopLoad();setMessage('브라우저 영상 연결 실패. CORS·기관 상태·사용자 IP 제한일 수 있습니다. 서버 프레임 시험으로 구분하세요.')}})
        hls.attachMedia(video);hls.loadSource(stream.url)
      }
      if(!disposed)void video.play().catch(()=>{if(!disposed)setMessage('재생 버튼을 눌러 영상을 시작하세요.')})
    })().catch(()=>{if(!disposed)setMessage('영상 플레이어를 불러오지 못했습니다.')})
    return()=>{disposed=true;clearInterval(interval);document.removeEventListener('visibilitychange',visibility);hls?.destroy();video.pause();video.removeAttribute('src');video.load()}
  },[stream])
  return <><video ref={videoRef} className="cctv-player" controls playsInline muted aria-label="UTIC 선택 영상"
    onPlaying={()=>setMessage('실시간 재생 중 · AI 분석·증거 저장은 하지 않습니다.')}
    onError={()=>setMessage('영상 재생 실패. 서버 프레임 시험과 브라우저 재생은 별도입니다.')}/>
    <p role="status" className="small-muted">{message} · 남은 시험 시간 {remaining}초</p></>
}

export default function UticPage(){
  const [catalog,setCatalog]=useState<Catalog|null>(null),[selected,setSelected]=useState<Item|null>(null),[search,setSearch]=useState('')
  const [stream,setStream]=useState<Stream|null>(null),[probe,setProbe]=useState<Probe|null>(null)
  const [busy,setBusy]=useState<'catalog'|'stream'|'probe'|null>(null),[error,setError]=useState('')
  const generation=useRef(0),mounted=useRef(true)
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;generation.current++}},[])
  async function load(refresh=false){const g=++generation.current;setStream(null);setProbe(null);setSelected(null);setCatalog(null);setBusy('catalog');setError('')
    try{const result=await api<Catalog>(`/utic/catalog?refresh=${refresh}`);if(mounted.current&&g===generation.current)setCatalog(result)}
    catch(e){if(mounted.current&&g===generation.current)setError((e as Error).message)}finally{if(mounted.current&&g===generation.current)setBusy(null)}}
  function choose(item:MapCamera){generation.current++;setSelected(item as Item);setStream(null);setProbe(null);setError('');setBusy(null)}
  async function act(kind:'stream'|'probe'){
    if(!selected||busy)return
    const g=++generation.current,id=selected.id;setBusy(kind);setError('');setStream(null)
    try{if(kind==='stream'){const result=await api<Stream>(`/utic/${id}/stream`);if(mounted.current&&g===generation.current)setStream(result)}
      else{setProbe(null);const result=await api<Probe>(`/utic/${id}/probe`,json('POST'));if(mounted.current&&g===generation.current)setProbe(result)}}
    catch(e){if(mounted.current&&g===generation.current)setError((e as Error).message)}finally{if(mounted.current&&g===generation.current)setBusy(null)}}
  const items=catalog?.items.filter(c=>c.name.toLowerCase().includes(search.toLowerCase()))||[]
  return <div>
    <div className="notice info">출처: 경찰청 도시교통정보센터(UTIC)·대구교통정보센터. 등록된 공인 IP의 서버에서 공식 개방데이터를 조회합니다. 지금은 목록·선택 재생·서버 프레임 1장 연결 시험이며 상시 AI 분석·알람·증거 저장은 하지 않습니다.</div>
    {error&&<div className="notice error" role="alert">{error}</div>}
    <div className="cctv-layout"><section className="panel"><div className="section-heading"><h2>UTIC 대구 CCTV 찾기</h2><Badge>UTIC</Badge></div>
      <button className="button primary" disabled={!!busy} onClick={()=>void load()}>{busy==='catalog'?'조회 중…':'UTIC 대구 목록 조회'}</button>
      {catalog&&<><p className="cctv-meta">{catalog.items.length}개 · {dateTime(new Date(catalog.fetched_at*1000).toISOString())} 확인<br/>좌표 원본 {catalog.source_total.toLocaleString()}개 · 잘못된 좌표 {catalog.source_invalid_coordinates}건 제외 · 현재 목록 미확인 {catalog.missing_from_live_list}개</p>
        <input aria-label="UTIC CCTV 이름 검색" placeholder="가창·두류·앞산 등 지점 검색" value={search} onChange={e=>setSearch(e.target.value)}/>
        <div className="cctv-list">{items.map(c=><button key={c.id} className={selected?.id===c.id?'active':''} onClick={()=>choose(c)}>{c.name}<small>{c.id} · {c.latitude.toFixed(5)}, {c.longitude.toFixed(5)}</small></button>)}</div>
        {!items.length&&<p className="small-muted">검색 결과가 없습니다.</p>}
        <button className="text-button" disabled={!!busy} onClick={()=>void load(true)}>UTIC 목록 갱신</button></>}
      <p className="cctv-meta">전체 영상 순회 없이 공식 목록 1회와 로컬 좌표 파일을 대조합니다. 목록은 24시간 캐시하고 실패·강제 갱신은 최소 60초 간격입니다. 이 목록은 재생 성공이나 실제 화재 탐지 보장이 아닙니다.</p>
    </section><section className="panel"><div className="section-heading"><h2>CCTV 설치 위치</h2><Badge>{catalog?.items.length||0}개</Badge></div>
      {catalog?<NaverMap showIgnition={false} point={selected||{latitude:35.85,longitude:128.60}} cameras={catalog.items} selectedCamera={selected?.id} onCamera={choose}/>:<div className="simple-empty">UTIC 목록을 조회하면 설치 위치를 지도에 표시합니다.</div>}
    </section></div>
    <section className="panel cctv-player-panel"><div className="section-heading"><h2>{selected?.name||'목록이나 지도에서 UTIC CCTV를 선택하세요'}</h2><Badge>연결 시험</Badge></div>
      {selected&&<><p className="small-muted">{selected.id} · {selected.center} · 설치 좌표 {selected.latitude.toFixed(6)}, {selected.longitude.toFixed(6)} — 발화점이 아닙니다.</p>
        <div className="button-row"><button className="button primary" disabled={!!busy||!!stream} onClick={()=>void act('stream')}>{busy==='stream'?'영상 확인 중…':'UTIC 영상 재생 · 최대 60초'}</button>
          {stream&&<button className="button" onClick={()=>setStream(null)}>영상 정지</button>}
          <button className="button" disabled={!!busy} onClick={()=>void act('probe')}>{busy==='probe'?'서버 수신 확인 중…':'서버 프레임 1장 확인'}</button></div></>}
      {stream&&<UticPlayer stream={stream} onStop={()=>setStream(null)}/>}
      {probe&&<><p className="notice info" role="status">서버 영상 수신 성공 · {probe.width}×{probe.height} · 영상 요청 {probe.http_requests}회 · {dateTime(new Date(probe.checked_at*1000).toISOString())} 확인. AI 분석·알람·파일 저장 없음.</p>
        <img className="cctv-snapshot" src={`data:image/jpeg;base64,${probe.frame_base64}`} alt="UTIC 서버에서 한 번 수신한 정지 프레임"/></>}
      <p className="cctv-meta">재생은 최대 60초 후 자동 종료하고 숨긴 탭·페이지 이동에서도 중지합니다. 서버 프레임은 한 장의 정지 화면이며 실시간 연속 영상이 아닙니다. 재시험은 카메라별 최소 60초 간격입니다. UTIC AI 분석·저장 허용은 ITS와 별도로 확인해야 합니다.</p>
    </section>
  </div>
}
