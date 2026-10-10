import {useEffect,useState} from 'react'
import {api,json,dateTime} from './api'
import {Badge} from './components'
import NaverMap from './NaverMap'
type Monitor={road:string;video_type:number;interval_seconds:number;approval_reference:string;rules:Record<string,unknown>;retry_at?:string;camera_id:string;catalog_id:string;name:string;enabled:boolean;state:string;message:string;frames?:number;last_frame?:string;failures?:number;auto_spread:boolean;calibration?:{sha256?:string;uncertainty_m?:number}}
type Listing={items:Monitor[];server_approved:boolean;capacity:number}
type Trial={id:string;camera_id:string;name:string;state:string;deadline:string;evidence_hours:number;report:Record<string,number|string|boolean|null>}
type Point={x:string;y:string;latitude:string;longitude:string}
const emptyPoints=()=>Array.from({length:6},()=>({x:'',y:'',latitude:'',longitude:''}))
const states:Record<string,string>={running:'상시 분석',connecting:'프레임 대기',analyzing:'추론 중',stale:'영상 정체',backoff:'오류 대기',stopped:'중지',approval_required:'승인 필요',capacity_blocked:'한도 초과 · 미분석'}
export default function MonitoringPanel({selected}:{selected:{id:string;name:string}|null}){
  const [data,setData]=useState<Listing|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false)
  const [approval,setApproval]=useState(''),[rights,setRights]=useState(false),[auto,setAuto]=useState(false),[ack,setAck]=useState(false)
  const [score,setScore]=useState(.25),[interval,setInterval]=useState(3),[ignore,setIgnore]=useState('[]'),[camera,setCamera]=useState('')
  const [points,setPoints]=useState<Point[]>(emptyPoints),[active,setActive]=useState(0),[preview,setPreview]=useState(false)
  const [note,setNote]=useState(''),[fixed,setFixed]=useState(false),[uncertainty,setUncertainty]=useState(90)
  const [reference,setReference]=useState('')
  const [minutes,setMinutes]=useState(10),[hours,setHours]=useState(24),[trials,setTrials]=useState<Trial[]>([])
  const reload=async()=>setData(await api<Listing>('/monitoring'))
  useEffect(()=>{let off=false;let timer:ReturnType<typeof setTimeout>;async function poll(){try{const r=await api<Listing>('/monitoring');if(!off)setData(r)}catch(e){if(!off)setError((e as Error).message)}if(!off)timer=setTimeout(()=>void poll(),5000)}void poll();return()=>{off=true;clearTimeout(timer)}},[])
  useEffect(()=>{setCamera('');setRights(false);setAuto(false);setAck(false);setPreview(false);setError('');setPoints(emptyPoints());setFixed(false);setNote('');setScore(.25);setInterval(3);setIgnore('[]');setApproval('');setUncertainty(90)},[selected?.id])
  async function configure(enabled:boolean){
    if(!selected)return
    setBusy(true);setError('')
    try{const r=await api<Monitor>(`/cctv/${selected.id}/monitor`,json('PUT',{enabled,rights_confirmed:rights,approval_reference:approval,interval_seconds:interval,
      rules:{minimum_score:score,ignore_polygons:JSON.parse(ignore)},auto_spread:auto,research_acknowledged:ack,
      trial_minutes:minutes,evidence_hours:hours}));setCamera(r.camera_id);await reload()}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function retryTrial(m:Monitor){setBusy(true);setError('');try{await api(`/cctv/catalog?road=${m.road}&video_type=${m.video_type}`);await api(`/cctv/${m.catalog_id}/monitor`,json('PUT',{enabled:true,rights_confirmed:true,approval_reference:m.approval_reference,interval_seconds:10,rules:m.rules,auto_spread:false,trial_minutes:2,evidence_hours:1}));await reload()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function stop(id:string){setBusy(true);try{await api(`/monitoring/${id}/stop`,json('POST'));await reload()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function loadTrials(download=false){try{const r=await api<{items:Trial[];warning:string}>('/monitoring/trials');setTrials(r.items);if(download){const url=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='cctv-connection-trials.json';a.click();URL.revokeObjectURL(url)}}catch(e){setError((e as Error).message)}}
  function update(i:number,key:keyof Point,value:string){setPoints(rows=>rows.map((r,j)=>j===i?{...r,[key]:value}:r))}
  const current=data?.items.find(m=>m.catalog_id===selected?.id),target=camera||current?.camera_id
  async function calibrate(){
    setBusy(true);setError('')
    try{
      if(points.some(r=>Object.values(r).some(v=>!v.trim()||!Number.isFinite(Number(v)))))throw new Error('기준점 4개와 독립 검사점 2개를 모두 입력하세요.')
      const pts=points.map(r=>Object.fromEntries(Object.entries(r).map(([k,v])=>[k,Number(v)])))
      await api(`/monitoring/${target}/calibration`,json('PUT',{reference_sha256:reference,points:pts.slice(0,4),checks:pts.slice(4),uncertainty_m:uncertainty,fixed_planar_view_confirmed:fixed,reference_note:note}))
      await reload();setPreview(false)
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  return <section className="panel monitor-panel"><div className="section-heading"><h2>서버 상시 CCTV 감시</h2><Badge tone={data?.server_approved?'success':'warning'}>{data?.server_approved?'승인 설정됨':'실제 수집 잠금'}</Badge></div>
    <p className="small-muted">등록된 활성 CCTV는 화면 재생·페이지 이동과 무관하게 서버에서 분석합니다. PC 절전·서버 종료 시 중단됩니다. 동시 한도 {data?.capacity??'—'}대 (성능 보장 아님).</p>
    {!data?.server_approved&&<div className="notice warning">기관의 무인 AI 분석·증거 저장 허용 확인 전입니다. 설정 준비는 가능하지만 실제 상시 수집은 서버에서 차단됩니다.</div>}
    {error&&<div className="notice error" role="alert">{error}</div>}
    <div className="monitor-records">{data?.items.map(m=><article key={m.camera_id}><div><strong>{m.name}</strong> <Badge tone={m.state==='running'?'success':'warning'}>{states[m.state]||m.state}</Badge>
      <p>{m.message}</p>{m.state==='backoff'&&m.retry_at&&<p>다음 재시도: {dateTime(m.retry_at)} · 권한 오류는 즉시 반복 접속하지 않습니다.</p>}<small>{m.frames??0}프레임 · 오류 {m.failures??0}회 · {m.last_frame?dateTime(m.last_frame):'수신 전'}</small>
      {m.calibration?.sha256&&<p>위치 보정 등록 · 가정 오차 {m.calibration.uncertainty_m}m · 자동 확산 {m.auto_spread?'ON':'OFF'}</p>}</div>
      <div className="button-row"><button className="button" disabled={busy||!m.enabled} onClick={()=>void stop(m.camera_id)}>상시 감시 중지</button><button className="button" disabled={busy||m.enabled||!data?.server_approved||m.approval_reference.length<5} onClick={()=>void retryTrial(m)}>2분 재시험 · 기존 허용 설정</button></div></article>)}</div>
    <p className="small-muted">2분 재시험은 기존 허용 근거·제외 구역을 유지하며 10초 간격으로 분석하고 자동 종료합니다. 자동 확산은 끕니다. 새 시험 증거는 1시간 뒤 삭제됩니다.</p><details><summary>장시간 연결 시험 기록</summary><p>연결·수신·지연을 측정합니다. 화재 탐지 정확도 검증이나 24시간 정상 작동 보장은 아닙니다.</p><div className="button-row"><button className="button" onClick={()=>void loadTrials()}>시험 기록 새로고침</button><button className="button" onClick={()=>void loadTrials(true)}>시험 보고서 JSON 다운로드</button></div>
      {trials.map(t=><article key={t.id}><strong>{t.name}</strong><p>{t.state==='running'?'시험 진행 중':t.state==='completed'?'시험 시간 종료':t.state} · 자동 종료 {dateTime(t.deadline)}</p><small>분석 {t.report.frames??0}장 · 오류 {t.report.failures??0}회 · 영상 요청 시도 {t.report.video_http_attempts??0}회 · 성공 수신 {((Number(t.report.video_success_bytes)||0)/1024/1024).toFixed(1)}MB · 평균 프레임 간격 {t.report.frame_interval_ms_mean==null?'—':(Number(t.report.frame_interval_ms_mean)/1000).toFixed(1)+'초'}</small></article>)}
    </details>
    {selected&&<details open><summary>{selected.name} · 감시 설정</summary>
      <div className="cctv-filter"><label>최소 샘플 간격 (초)<input type="number" min={2} max={10} value={interval} onChange={e=>setInterval(Number(e.target.value))}/></label>
      <label>불꽃 점수 하한<input type="number" min={.25} max={.95} step={.05} value={score} onChange={e=>setScore(Number(e.target.value))}/></label></div>
      <div className="cctv-filter"><label>시험 시간 · 자동 종료<select value={minutes} onChange={e=>setMinutes(Number(e.target.value))}><option value={2}>2분 기능 시험</option><option value={10}>10분</option><option value={60}>1시간</option><option value={240}>4시간</option><option value={1440}>24시간</option></select></label><label>새 시험 증거 사진 보관 시간<input type="number" min={1} max={24} value={hours} onChange={e=>setHours(Number(e.target.value))}/></label></div><p className="small-muted">이번 시험에서 생성된 증거 사진만 기간 뒤 삭제됩니다. 기존 사진은 유지되며 알람 메타데이터는 남습니다. 기관 조건보다 길게 설정하지 마세요.</p>
      <label>기관 허용 근거 (키·비밀번호 입력 금지)<input value={approval} maxLength={300} onChange={e=>setApproval(e.target.value)} placeholder="허용 문서 날짜·제목"/></label>
      <label className="cctv-consent"><input type="checkbox" checked={rights} onChange={e=>setRights(e.target.checked)}/>무인 AI 분석·후보 증거 저장이 허용됨을 확인했습니다.</label>
      <details><summary>오탐 제외 구역 (고급)</summary><p>정규화 화면 다각형 JSON. 실제 불도 제외될 수 있어 검증이 필요합니다. 예: [[[0,0],[0.2,0],[0.2,0.2],[0,0.2]]]</p><textarea aria-label="제외 구역 JSON" rows={3} value={ignore} onChange={e=>setIgnore(e.target.value)}/></details>
      <label className="cctv-consent"><input type="checkbox" checked={auto} onChange={e=>setAuto(e.target.checked)}/>보정 위치의 연구용 확산 자동 실행</label>
      {auto&&<label className="cctv-consent"><input type="checkbox" checked={ack} onChange={e=>setAck(e.target.checked)}/>최초 발화점이 아닌 근사이며, 오차·자료·기상 조건 미충족 시 보류됨을 이해했습니다.</label>}
      <div className="button-row"><button className="button" disabled={busy} onClick={()=>void configure(false)}>설정만 저장 · 수집 OFF</button><button className="button primary" disabled={busy||!data?.server_approved||!rights} onClick={()=>void configure(true)}>상시 감시 시작</button></div>
      <p className="small-muted">불꽃 또는 점수 0.5 이상 연기의 같은 위치 후보 3/5회·최소 6초 확인. 연기 기준은 현장 검증 전입니다. 새로운 프레임이 30초 이상 없으면 정상 감시 아님. 샘플링은 모든 영상 프레임을 검사하는 것이 아니므로 짧은 불꽃은 놓칠 수 있습니다.</p>
    </details>}
    {target&&<details><summary>화면–지도 자동 위치 보정</summary><div className="notice warning">고정 시야·평면 근사용입니다. 산악 지형·PTZ에 적용하지 마세요. 카메라 설치 좌표를 발화점으로 사용하지 않습니다.</div>
      <p>설정만 저장 → 허용된 2분 분석으로 최근 프레임 준비 → 상시 감시 중지 → 기준점 4개·독립 검사점 2개 입력. 행을 선택하고 이미지와 지도에서 동일한 지점을 클릭하세요.</p>
      <button className="button" onClick={()=>{setError('');void api<{sha256:string}>(`/monitoring/${target}/reference`,json('POST')).then(r=>{setReference(r.sha256);setPreview(true)}).catch(e=>setError(e.message))}}>기준 프레임 고정 · 15분 유효</button>
      {preview&&<img className="calibration-image" src={`/api/monitoring/${target}/reference?v=${reference}`} alt="위치 보정 기준 프레임" onClick={e=>{const r=e.currentTarget.getBoundingClientRect();update(active,'x',((e.clientX-r.left)/r.width).toFixed(5));update(active,'y',((e.clientY-r.top)/r.height).toFixed(5))}}/>}
      <div className="table-wrap"><table><thead><tr><th>선택</th><th>종류</th><th>X</th><th>Y</th><th>위도</th><th>경도</th></tr></thead><tbody>{points.map((r,i)=><tr key={i}><td><input aria-label={`기준 행 ${i+1}`} type="radio" checked={active===i} onChange={()=>setActive(i)}/></td><td>{i<4?'보정':'독립 검사'} {i+1}</td>{(Object.keys(r) as (keyof Point)[]).map(k=><td key={k}><input aria-label={`${i+1} ${k}`} type="number" step="any" value={r[k]} onChange={e=>update(i,k,e.target.value)}/></td>)}</tr>)}</tbody></table></div>
      <NaverMap point={{latitude:Number(points[active].latitude)||35.81,longitude:Number(points[active].longitude)||128.60}} onPoint={p=>{update(active,'latitude',p.latitude.toFixed(7));update(active,'longitude',p.longitude.toFixed(7))}}/>
      <label>위치 가정 오차 (m, 최소 90)<input type="number" min={90} max={1000} value={uncertainty} onChange={e=>setUncertainty(Number(e.target.value))}/></label>
      <label>기준점 근거<input value={note} maxLength={300} onChange={e=>setNote(e.target.value)} placeholder="실측/기관 자료 등"/></label>
      <label className="cctv-consent"><input type="checkbox" checked={fixed} onChange={e=>setFixed(e.target.checked)}/>고정 시야·평면 근사·렌즈 왜곡 보정 조건을 확인했습니다.</label>
      <button className="button primary" disabled={busy||!fixed||!reference} onClick={()=>void calibrate()}>보정 검사·저장</button>
    </details>}
  </section>
}
