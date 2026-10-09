import {useEffect,useState} from 'react'
import {api,json} from './api'
type Location={estimate:{available:boolean;reason?:string;latitude?:number;longitude?:number;uncertainty_m?:number;warning?:string};simulation_id:string|null;message:string}
export default function IncidentPanel({eventId}:{eventId:string}){
  const [loc,setLoc]=useState<Location|null>(null),[outcome,setOutcome]=useState('uncertain'),[reason,setReason]=useState(''),[msg,setMsg]=useState(''),[busy,setBusy]=useState(false)
  useEffect(()=>{let off=false;api<Location>(`/events/${eventId}/location`).then(r=>{if(!off)setLoc(r)}).catch(()=>{if(!off)setMsg('위치 조회 실패')});return()=>{off=true}},[eventId])
  async function save(){setBusy(true);try{await api(`/events/${eventId}/review`,json('PUT',{outcome,reason}));setMsg('검토 저장 완료. 모델·정답 라벨은 자동 변경하지 않습니다.')}catch(e){setMsg((e as Error).message)}finally{setBusy(false)}}
  return <div className="incident-panel"><h3>자동 위치 추정 · 확인 필요</h3>{loc?.estimate.available?<div className="notice warning">추정 {loc.estimate.latitude?.toFixed(6)}, {loc.estimate.longitude?.toFixed(6)} · 가정 오차 {loc.estimate.uncertainty_m}m<p>{loc.estimate.warning}</p><p>{loc.message}</p>{loc.simulation_id&&<p>확산 작업 {loc.simulation_id.slice(0,12)}</p>}</div>:<p>{loc?.estimate.reason||'위치 조회 중'}</p>}
    <h3>오탐 검토 기록</h3><label>사람의 판정<select value={outcome} onChange={e=>setOutcome(e.target.value)}><option value="uncertain">판단 보류</option><option value="false_alarm">오탐 확인</option><option value="true_fire">실제 불꽃 확인</option></select></label>
    <label>판정 근거<input value={reason} maxLength={300} onChange={e=>setReason(e.target.value)}/></label><button className="button" disabled={busy} onClick={()=>void save()}>검토 저장</button>{msg&&<p role="status">{msg}</p>}</div>
}
