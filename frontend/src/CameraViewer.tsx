import {useEffect,useRef,useState} from 'react'
import type Hls from 'hls.js'
import {api} from './api'
import {dateTime} from './api'
import {Badge,Modal} from './components'
import type {Camera} from './types'

function Player({url,type}:{url:string;type:number}){
  const ref=useRef<HTMLVideoElement>(null),[error,setError]=useState('')
  useEffect(()=>{
    const video=ref.current!;let hls:Hls|undefined,disposed=false
    const fail=()=>setError('브라우저 영상 재생 실패. 기관 응답·CORS·영상 형식을 확인하세요. 서버 분석 상태와는 별도입니다.')
    // Keep the HLS runtime out of the login/overview bundle. Load only one selected feed.
    void (async()=>{
      if([1,4].includes(type)){
        const {default:Hls}=await import('hls.js')
        if(disposed)return
        if(Hls.isSupported()){
          hls=new Hls({maxBufferLength:10,maxMaxBufferLength:20,manifestLoadingMaxRetry:1,levelLoadingMaxRetry:1,fragLoadingMaxRetry:1})
          hls.on(Hls.Events.ERROR,(_,data)=>{if(data.fatal){fail();hls?.stopLoad()}})
          hls.attachMedia(video);hls.loadSource(url)
        }else video.src=url
      }else video.src=url
      if(!disposed)void video.play().catch(()=>{/* User can press controls if autoplay is blocked. */})
    })().catch(()=>{if(!disposed)fail()})
    const visibility=()=>{if(document.hidden){video.pause();hls?.stopLoad()}else if(!video.paused)hls?.startLoad()}
    const playing=()=>{if(document.hidden){video.pause();return}hls?.startLoad()}
    const pause=()=>hls?.stopLoad()
    video.addEventListener('error',fail);video.addEventListener('play',playing);video.addEventListener('pause',pause);document.addEventListener('visibilitychange',visibility)
    return()=>{disposed=true;document.removeEventListener('visibilitychange',visibility);video.removeEventListener('error',fail);video.removeEventListener('play',playing);video.removeEventListener('pause',pause);hls?.destroy();video.pause();video.removeAttribute('src');video.load()}
  },[url,type])
  return <><video ref={ref} controls muted playsInline className="event-snapshot" aria-label="선택한 CCTV 실시간 영상"/>{error&&<div className="notice error" role="alert">{error}</div>}</>
}

export default function CameraViewer({camera,tick,onClose}:{camera:Camera;tick:number;onClose:()=>void}){
  const [stream,setStream]=useState<{url:string;video_type:number}|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const mounted=useRef(true)
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[])
  async function play(){setBusy(true);setError('');try{const result=await api<{url:string;video_type:number}>(`/cameras/${camera.id}/stream`);if(mounted.current)setStream(result)}catch(e){if(mounted.current)setError((e as Error).message)}finally{if(mounted.current)setBusy(false)}}
  return <Modal title={camera.name} subtitle={camera.location||'설치 위치 미지정'} onClose={onClose}>
    <Badge tone={camera.online?'success':'warning'}>{camera.online?'서버 프레임 수신 중':'현재 정상 수신 확인 안 됨'}</Badge>
    <p className="small-muted">{camera.monitor_message||'화면 표시와 서버 AI 분석은 별개입니다.'}</p>
    {stream?<Player url={stream.url} type={stream.video_type}/>:camera.preview_url?<img className="event-snapshot" src={`${camera.preview_url}?v=${tick}`} alt={`${camera.name} 최근 분석 프레임`}/>:<div className="simple-empty">최근 분석 프레임이 없습니다.</div>}
    {!stream&&<p className="small-muted">최근 분석: {camera.last_seen?dateTime(camera.last_seen):'없음'} · {camera.preview_stale?'과거 프레임이며 실시간 화면이 아닙니다.':'분석 프레임을 주기적으로 표시합니다.'}</p>}
    {camera.kind==='its'&&<div className="button-row">{stream?<button className="button" onClick={()=>setStream(null)}>영상 재생 중지</button>:<button className="button primary" disabled={busy} onClick={()=>void play()}>{busy?'영상 주소 확인 중…':'실시간 영상 재생'}</button>}</div>}
    {error&&<div className="notice error" role="alert">{error}</div>}
    <div className="notice info">이 창을 닫아도 활성화된 서버 감시는 계속됩니다. 설치 좌표는 실제 발화점이 아닙니다.{camera.kind==='its'&&' 영상 출처: 국토교통부 국가교통정보센터(ITS).'}</div>
  </Modal>
}

export function ArchiveCameraDialog({camera,onClose,onArchived}:{camera:Camera;onClose:()=>void;onArchived:()=>void}){
  const [busy,setBusy]=useState(false),[error,setError]=useState('')
  async function archive(){setBusy(true);try{await api(`/cameras/${camera.id}/archive`,{method:'POST'});onArchived()}catch(e){setError((e as Error).message);setBusy(false)}}
  return <Modal title="카메라를 목록에서 제거할까요?" subtitle={camera.name} onClose={onClose}><p>전송 키와 감시를 해제하고 목록에서 숨깁니다. 기존 알람·증거는 유지되며 나중에 복원할 수 있습니다. 복원 후 연결 코드는 새로 발급해야 합니다.</p>{error&&<div className="notice error" role="alert">{error}</div>}<div className="button-row"><button className="button" disabled={busy} onClick={onClose}>취소</button><button className="button primary" disabled={busy} onClick={()=>void archive()}>목록에서 제거</button></div></Modal>
}

export function ArchivedCameras({onRestored}:{onRestored:()=>void}){
  const [items,setItems]=useState<Camera[]|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false)
  async function load(){setError('');try{setItems(await api<Camera[]>('/cameras/archived'))}catch(e){setError((e as Error).message)}}
  async function restore(id:string){setBusy(true);try{await api(`/cameras/${id}/restore`,{method:'POST'});await load();onRestored()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  return <div style={{marginTop:20}}><button className="text-button" onClick={()=>{if(items)setItems(null);else void load()}}>{items?'제거된 카메라 접기':'제거된 카메라 보기'}</button>{items&&<div>{items.length===0?<p className="small-muted">제거된 카메라가 없습니다.</p>:items.map(c=><div className="camera-controls" key={c.id}><span>{c.name} · {c.location}</span><button className="button" disabled={busy} onClick={()=>void restore(c.id)}>복원</button></div>)}</div>}{error&&<div className="notice error" role="alert">{error}</div>}</div>
}
