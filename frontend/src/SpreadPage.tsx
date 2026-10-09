import {useCallback,useEffect,useRef,useState} from 'react'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import type {FeatureCollection} from 'geojson'
import {ArrowRight,CloudSun,Download,Flame,Layers,LoaderCircle,MapPin,Play,RefreshCw,ShieldCheck,Wind} from 'lucide-react'
import {api,json,dateTime} from './api'
import {Badge} from './components'
import 'maplibre-gl/dist/maplibre-gl.css'
import './SpreadPage.css'
import NaverMap,{AddressSearch} from './NaverMap'

type Point={latitude:number;longitude:number}
type Weather={available?:boolean;fresh?:boolean;source:string;message?:string;observed_at?:string|null;age_minutes?:number;temperature_c:number;humidity_pct:number;wind_speed_ms:number;wind_from_deg:number;rain_mm:number}
type Manifest={grid_m:number;default_ignition:Point;bounds_wgs84:number[];forest_features:number;soil_features:number;known_forest_cells:number;data_sha256:string;years:string[];warnings:string[]}
type Status={ready:boolean;manifest?:Manifest;message?:string;nifos?:{available:boolean;message:string}}
type DangerRecord={valid_at:string;minimum:number;mean:number;maximum:number;future_time:boolean}
type Danger={available:boolean;fresh?:boolean;region?:string;current?:DangerRecord|null;forecasts?:DangerRecord[];age_minutes?:number|null;message:string}
type Summary={horizons:{minute:number;mean_area_ha:number;any_run_area_ha:number}[];runtime_ms:number;runs:number;seed:number;grid_m:number;engine_version:string;boundary_contact:boolean;warnings:string[]}
type Job={id:string;state:'queued'|'running'|'completed'|'failed';created_at:string;message?:string;summary?:Summary;context?:unknown;request:{latitude:number;longitude:number;model:string;horizon_min:number;weather:Weather;event_id?:string}}
const empty:FeatureCollection={type:'FeatureCollection',features:[]}
const modelLabels:Record<string,string>={circle:'원형 기준선',ellipse:'풍향 타원 기준선',ca:'바람·경사·숲 CA'}
maplibregl.setWorkerUrl(mapWorkerUrl) // Bundled same-origin worker; no blob/CSP bypass.
function downloadBlob(blob:Blob,name:string){
  const url=URL.createObjectURL(blob),link=document.createElement('a')
  link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}

function LocalMap({forest,terrain,result,minute,point,exportLabel,onPoint,onError}:{forest:FeatureCollection;terrain:FeatureCollection;result:FeatureCollection;minute:number;point:Point;exportLabel:string;onPoint:(p:Point)=>void;onError:(m:string)=>void}){
  const container=useRef<HTMLDivElement>(null), map=useRef<maplibregl.Map|null>(null)
  const pointRef=useRef(onPoint),errorRef=useRef(onError)
  pointRef.current=onPoint;errorRef.current=onError
  useEffect(()=>{
    if(!container.current)return
    const m=new maplibregl.Map({container:container.current,center:[point.longitude,point.latitude],zoom:13.5,
      style:{version:8,sources:{},layers:[{id:'background',type:'background',paint:{'background-color':'#f1f4f0'}}]},
      attributionControl:false,canvasContextAttributes:{preserveDrawingBuffer:true},maxZoom:17,minZoom:10})
    map.current=m
    m.addControl(new maplibregl.NavigationControl({showCompass:true}),'top-right')
    m.addControl(new maplibregl.ScaleControl({unit:'metric'}),'bottom-left')
    m.addControl(new maplibregl.AttributionControl({customAttribution:'지형: 국토지리정보원 · 임상/토양: 산림청 · 연구용 로컬 지도',compact:false}))
    m.on('load',()=>{
      for(const id of ['terrain','forest','spread','ignition'])m.addSource(id,{type:'geojson',data:empty})
      m.addLayer({id:'terrain-shade',type:'fill',source:'terrain',paint:{'fill-color':['interpolate',['linear'],['get','elevation_band_m'],0,'#f4f5f1',400,'#e4e9de',900,'#c4ceba'],'fill-opacity':.8}})
      m.addLayer({id:'terrain-lines',type:'line',source:'terrain',paint:{'line-color':'#ccd5c4','line-width':.6,'line-opacity':.55}})
      m.addLayer({id:'forest-fill',type:'fill',source:'forest',paint:{'fill-color':['match',['get','forest_type'],'침엽수림','#557b61','활엽수림','#91a876','혼효림','#749788','#a5b8a5'],'fill-opacity':.58}})
      m.addLayer({id:'forest-lines',type:'line',source:'forest',paint:{'line-color':'#385c48','line-width':.7,'line-opacity':.42}})
      m.addLayer({id:'spread-fill',type:'fill',source:'spread',paint:{'fill-color':['step',['get','frequency_threshold'],'#efb46d',.5,'#e9834f',.9,'#c64f36'],'fill-opacity':.45}})
      m.addLayer({id:'spread-line',type:'line',source:'spread',paint:{'line-color':'#ad4f35','line-width':1.6}})
      m.addLayer({id:'ignition-circle',type:'circle',source:'ignition',paint:{'circle-color':'#b74732','circle-radius':8,'circle-stroke-width':3,'circle-stroke-color':'#ffffff'}})
      ;(m.getSource('terrain') as maplibregl.GeoJSONSource).setData(terrain)
      ;(m.getSource('forest') as maplibregl.GeoJSONSource).setData(forest)
      ;(m.getSource('spread') as maplibregl.GeoJSONSource).setData(result)
      ;(m.getSource('ignition') as maplibregl.GeoJSONSource).setData({type:'FeatureCollection',features:[{type:'Feature',geometry:{type:'Point',coordinates:[point.longitude,point.latitude]},properties:{}}]})
      m.setFilter('spread-fill',['==',['get','minute'],minute]);m.setFilter('spread-line',['==',['get','minute'],minute])
    })
    m.on('click',e=>pointRef.current({latitude:e.lngLat.lat,longitude:e.lngLat.lng}))
    m.on('error',()=>errorRef.current('지도 표시 오류가 있습니다. WebGL 지원을 확인하세요. 좌표 입력으로도 계산할 수 있습니다.'))
    const observer=new ResizeObserver(()=>m.resize());observer.observe(container.current)
    return()=>{observer.disconnect();m.remove();map.current=null}
    // One map instance. Data updates are handled below; no external map requests.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[])
  useEffect(()=>{
    const m=map.current
    if(!m)return
    const update=()=>{
      for(const [id,data] of [['terrain',terrain],['forest',forest],['spread',result]] as const)(m.getSource(id) as maplibregl.GeoJSONSource)?.setData(data)
      ;(m.getSource('ignition') as maplibregl.GeoJSONSource)?.setData({type:'FeatureCollection',features:[{type:'Feature',geometry:{type:'Point',coordinates:[point.longitude,point.latitude]},properties:{}}]})
      if(m.getLayer('spread-fill')){m.setFilter('spread-fill',['==',['get','minute'],minute]);m.setFilter('spread-line',['==',['get','minute'],minute])}
    }
    // Source data can be loading after the initial style load. The one-time
    // 'load' event will not fire again; check source existence instead.
    if(m.getSource('spread'))update();else m.once('load',update)
    return()=>{m.off('load',update)}
  },[forest,terrain,result,minute,point])
  useEffect(()=>{map.current?.easeTo({center:[point.longitude,point.latitude],duration:350})},[point.latitude,point.longitude])
  function exportMap(){
    const m=map.current
    if(!m)return
    const source=m.getCanvas(),canvas=document.createElement('canvas')
    canvas.width=Math.max(900,source.width)
    const mapHeight=Math.round(source.height*canvas.width/source.width)
    canvas.height=mapHeight+150
    const ctx=canvas.getContext('2d')
    if(!ctx)return
    ctx.drawImage(source,0,0,canvas.width,mapHeight);ctx.fillStyle='#f3f5ef';ctx.fillRect(0,mapHeight,canvas.width,150)
    ctx.fillStyle='#244937';ctx.font='bold 20px sans-serif';ctx.fillText('Ember | Research-only spread scenario',20,mapHeight+32)
    ctx.font='14px sans-serif';ctx.fillText(exportLabel,20,mapHeight+60)
    ctx.fillText(`${minute} model minutes | Uncalibrated, NOT an arrival time or evacuation guide`,20,mapHeight+87)
    ctx.fillText('Terrain: NGII | Forest/soil: Korea Forest Service | Local GIS, 90 m',20,mapHeight+114)
    canvas.toBlob(blob=>{if(blob)downloadBlob(blob,`ember-spread-${minute}modelmin.png`)},'image/png')
  }
  return <div><div className="spread-map" ref={container} aria-label="발화점을 선택하는 대구 숲·지형 지도"/><button className="text-button spread-map-export" onClick={exportMap}><Download size={14}/>현재 지도 PNG 저장</button></div>
}

export default function SpreadPage({eventId}:{eventId?:string}){
  const [mapMode,setMapMode]=useState<'local'|'naver'>('local')
  useEffect(()=>{api<{enabled:boolean}>('/maps/config').then(c=>{if(c.enabled)setMapMode('naver')}).catch(()=>{})},[])
  const [status,setStatus]=useState<Status|null>(null),[point,setPoint]=useState<Point>({latitude:35.81,longitude:128.58})
  const [forest,setForest]=useState<FeatureCollection>(empty),[terrain,setTerrain]=useState<FeatureCollection>(empty),[result,setResult]=useState<FeatureCollection>(empty)
  const [model,setModel]=useState('ca'),[mode,setMode]=useState('manual'),[horizon,setHorizon]=useState(30),[runs,setRuns]=useState(30),[seed,setSeed]=useState(42)
  const [manual,setManual]=useState<Weather>({source:'manual',temperature_c:20,humidity_pct:40,wind_speed_ms:3,wind_from_deg:270,rain_mm:0})
  const [weather,setWeather]=useState<Weather|null>(null),[job,setJob]=useState<Job|null>(null),[history,setHistory]=useState<Job[]>([])
  const [danger,setDanger]=useState<Danger|null>(null),[dangerBusy,setDangerBusy]=useState(false)
  const [error,setError]=useState(''),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[fetching,setFetching]=useState(false),[confirmed,setConfirmed]=useState(false),[minute,setMinute]=useState(30)
  const selectionVersion=useRef(0),weatherVersion=useRef(0)
  useEffect(()=>()=>{selectionVersion.current++;weatherVersion.current++},[])
  const active=job?.state==='queued'||job?.state==='running'
  const fetchHistory=useCallback(()=>api<{items:Job[]}>('/simulations').then(r=>setHistory(r.items)).catch(()=>{}),[])
  const getDanger=useCallback(async()=>{
    setDangerBusy(true)
    try{setDanger(await api<Danger>('/fire-danger'))}catch{setDanger({available:false,message:'위험지수 조회 실패입니다. 확산 계산에는 영향을 주지 않습니다.'})}finally{setDangerBusy(false)}
  },[])
  useEffect(()=>{
    let mounted=true
    api<Status>('/spread/status').then(async s=>{
      if(!mounted)return
      setStatus(s)
      if(s.ready&&s.manifest){
        setPoint(s.manifest.default_ignition)
        const [f,t]=await Promise.all([api<FeatureCollection>('/spread/forest'),api<FeatureCollection>('/spread/terrain')])
        if(mounted){setForest(f);setTerrain(t)}
      }
    }).catch(e=>{if(mounted)setError(e.message)}).finally(()=>{if(mounted)setLoading(false)})
    void fetchHistory();void getDanger();return()=>{mounted=false}
  },[fetchHistory,getDanger])
  useEffect(()=>{
    if(!job||!active)return
    let cancelled=false
    let timer:ReturnType<typeof setTimeout>
    const poll=async()=>{
      let terminal=false
      await api<Job>(`/simulations/${job.id}`).then(async j=>{
        if(cancelled)return
        if(j.state==='completed'){
          const r=await api<FeatureCollection>(`/simulations/${j.id}/perimeters`)
          // Commit completion and its geometry together. Updating active state
          // before awaiting geometry cancels this effect and drops the result.
          if(!cancelled){terminal=true;setResult(r);setMinute(j.request.horizon_min);setJob(j);void fetchHistory()}
        }else if(j.state==='failed'){terminal=true;setJob(j);setError(j.message||'계산 실패');void fetchHistory()}
        else setJob(j)
      }).catch(e=>{if(!cancelled)setError(e.message)})
      if(!cancelled&&!terminal)timer=setTimeout(()=>void poll(),1000)
    }
    timer=setTimeout(()=>void poll(),1000)
    return()=>{cancelled=true;clearTimeout(timer)}
  },[job?.id,active,fetchHistory])
  const selectPoint=useCallback((p:Point)=>{weatherVersion.current++;setFetching(false);setPoint(p);setConfirmed(false);setWeather(null)},[])
  const clearSelection=()=>{selectionVersion.current++;setJob(null);setResult(empty)}
  useEffect(()=>{
    if(!eventId||loading)return
    let off=false
    api<{estimate:{available:boolean;latitude:number;longitude:number};simulation_id:string|null}>(`/events/${eventId}/location`).then(async loc=>{
      if(off||!loc.estimate.available)return
      setPoint({latitude:loc.estimate.latitude,longitude:loc.estimate.longitude});setConfirmed(false)
      if(loc.simulation_id){
        const j=await api<Job>(`/simulations/${loc.simulation_id}`)
        if(off)return
        setJob(j);setMinute(j.request.horizon_min)
        if(j.state==='completed'){
          const r=await api<FeatureCollection>(`/simulations/${j.id}/perimeters`)
          if(!off)setResult(r)
        }
      }
    }).catch(()=>{})
    return()=>{off=true}
  },[eventId,loading])
  async function getWeather(){
    const version=++weatherVersion.current
    setFetching(true);setError('')
    try{const w=await api<Weather>(`/weather?latitude=${point.latitude}&longitude=${point.longitude}`);if(version===weatherVersion.current)setWeather(w)}
    catch(e){if(version===weatherVersion.current)setError((e as Error).message)}
    finally{if(version===weatherVersion.current)setFetching(false)}
  }
  async function submit(){
    const version=++selectionVersion.current
    setBusy(true);setError('')
    try{
      const j=await api<Job>('/simulations',json('POST',{...point,event_id:eventId||null,location_confirmed:confirmed,
        model,horizon_min:horizon,runs,seed,weather_mode:mode,manual_weather:mode==='manual'?manual:null}))
      if(version===selectionVersion.current){setJob(j);setResult(empty);setMinute(horizon)}
      void fetchHistory()
    }catch(e){if(version===selectionVersion.current)setError((e as Error).message)}finally{setBusy(false)}
  }
  async function openJob(j:Job){const version=++selectionVersion.current;setJob(j);setError('');setResult(empty);setMinute(j.request.horizon_min);if(j.state==='completed'){
    try{const r=await api<FeatureCollection>(`/simulations/${j.id}/perimeters`);if(version===selectionVersion.current)setResult(r)}catch(e){if(version===selectionVersion.current)setError((e as Error).message)}
  }}
  if(loading)return <div className="panel spread-loading"><LoaderCircle className="spin"/>지도 자료 불러오는 중</div>
  if(!status?.ready||!status.manifest)return <div className="notice warning">{error||status?.message||'확산 데이터 준비가 필요합니다.'} 서버에서 scripts/prepare-spread-data.py를 실행한 뒤 새로고침하세요.</div>
  const manifest=status.manifest,selectedSummary=job?.summary?.horizons.find(h=>h.minute===minute),viewPoint=job?.state==='completed'?{latitude:job.request.latitude,longitude:job.request.longitude}:point
  return <div className="spread-page">
    <div className="spread-intro"><ShieldCheck size={20}/><div><strong>연구용 산불 확산 시나리오</strong><p>발화점은 직접 지정합니다. 표시 시간·반복 비율은 검증된 도달시각·실제 화재 확률이 아닙니다. 공식 경보·대피 지시를 대체하지 않습니다.</p></div><Badge tone="warning">UNCALIBRATED</Badge></div>
    {eventId&&<div className="notice info"><Flame size={18}/>새 계산은 알람 {eventId.slice(0,8)}…에 연결됩니다. 실제 발화 좌표를 영상에서 추정한 것은 아닙니다.</div>}
    {error&&<div className="notice error" role="alert">{error}</div>}
    <div className="spread-layout"><section className="spread-controls panel">
      <div className="section-heading"><h2><MapPin size={18}/>시나리오 설정</h2><Badge>대구 일부</Badge></div>
      <p className="small-muted">지도에서 숲 내부를 클릭하거나 좌표를 입력하세요. 셀 중심이 임상도 숲에 포함돼야 합니다.</p>
      <div className="spread-field-pair"><label>위도<input aria-label="발화점 위도" type="number" step="0.00001" value={point.latitude.toFixed(5)} onChange={e=>selectPoint({...point,latitude:Number(e.target.value)})}/></label><label>경도<input aria-label="발화점 경도" type="number" step="0.00001" value={point.longitude.toFixed(5)} onChange={e=>selectPoint({...point,longitude:Number(e.target.value)})}/></label></div>
      <button className="text-button" onClick={()=>{selectPoint(manifest.default_ignition);clearSelection()}}><MapPin size={14}/>검증된 숲 격자 지점으로 초기화</button>
      <AddressSearch point={point} onPoint={p=>{selectPoint(p);clearSelection()}}/>
      <div className="spread-divider"/>
      <label>기상 입력<select aria-label="기상 입력 방식" value={mode} onChange={e=>setMode(e.target.value)}><option value="manual">수동 가상 기상 · 실황 아님</option><option value="kma">기상청 최신 실황</option></select></label>
      {mode==='manual'?<><div className="spread-field-pair"><label>풍속 (m/s)<input type="number" min="0" max="40" step=".5" value={manual.wind_speed_ms} onChange={e=>setManual({...manual,wind_speed_ms:Number(e.target.value)})}/></label><label>풍향 · 불어오는 방향 (°)<input type="number" min="0" max="359" value={manual.wind_from_deg} onChange={e=>setManual({...manual,wind_from_deg:Number(e.target.value)})}/></label></div><div className="spread-field-pair"><label>습도 (%)<input type="number" min="0" max="100" value={manual.humidity_pct} onChange={e=>setManual({...manual,humidity_pct:Number(e.target.value)})}/></label><label>강수 (mm)<input type="number" min="0" max="100" value={manual.rain_mm} onChange={e=>setManual({...manual,rain_mm:Number(e.target.value)})}/></label></div><p className="small-muted">270° 서풍 → 동쪽으로 부는 바람. 가상 풍속·습도·강수만 계산에 적용합니다. 실제 연료 수분 측정값이 아닙니다.</p></>:<><button className="button full" disabled={fetching} onClick={()=>void getWeather()}>{fetching?<LoaderCircle className="spin" size={16}/>:<CloudSun size={16}/>}선택 지점 실황 조회</button>{weather&&<div className={`spread-weather ${weather.available&&weather.fresh?'':'unavailable'}`}><strong>{weather.available?(weather.fresh?'기상청 관측값':'오래된 관측값'):'조회 불가'}</strong>{weather.available&&<><span><Wind size={15}/>{weather.wind_speed_ms}m/s · {weather.wind_from_deg}°에서</span><span>{weather.temperature_c}°C · 습도 {weather.humidity_pct}% · 강수 {weather.rain_mm}mm</span><small>{weather.observed_at&&dateTime(weather.observed_at)} · {weather.age_minutes}분 전</small></>}<p>{weather.message}</p></div>}<p className="small-muted">실행 시 최신 기상을 다시 확인·저장합니다. 자료가 없으면 가상 값으로 자동 대체하지 않습니다.</p></>}
      <div className="spread-divider"/>
      <label>확산 계산 모델<select aria-label="확산 계산 모델" value={model} onChange={e=>setModel(e.target.value)}>{Object.entries(modelLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
      <div className="spread-field-pair"><label>모델 시간<select aria-label="계산 시간 범위" value={horizon} onChange={e=>setHorizon(Number(e.target.value))}><option value="10">10분</option><option value="30">30분</option><option value="60">60분</option></select></label><label>반복 횟수<input aria-label="반복 횟수" type="number" min="10" max="100" value={runs} disabled={model!=='ca'} onChange={e=>setRuns(Number(e.target.value))}/></label></div>
      <label>재현용 seed<input aria-label="재현용 seed" type="number" min="0" max="2147483647" value={seed} onChange={e=>setSeed(Number(e.target.value))}/></label>
      <label className="spread-confirm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/><span>이 위치는 직접 선택한 가상 발화점이며, 결과는 연구용 시나리오임을 확인했습니다.</span></label>
      <button className="button primary full" disabled={!confirmed||busy||active} onClick={()=>void submit()}>{busy||active?<LoaderCircle className="spin" size={17}/>:<Play size={17}/>} {active?'별도 프로세스에서 계산 중':'확산 시뮬레이션 실행'}</button>
      <p className="small-muted">탐지·알람은 계속 실행됩니다. 기본 전파율 6m/모델분, 연소 지속 8모델분은 검증되지 않은 가정입니다.</p>
    </section><section className="spread-map-panel panel"><div className="section-heading"><div><span className="eyebrow">LOCAL GIS / SPREAD LAB</span><h2>숲과 지형 위에서, 확산을 살펴보세요.</h2></div><Badge tone="success">원본 DEM {manifest.grid_m}m</Badge></div>
      <div className="map-mode-row"><button className={`button ${mapMode==='naver'?'primary':''}`} onClick={()=>setMapMode('naver')}>네이버 실제 지도</button><button className={`button ${mapMode==='local'?'primary':''}`} onClick={()=>setMapMode('local')}>로컬 GIS · PNG 내보내기</button></div>
      {mapMode==='naver'?<NaverMap forest={forest} terrain={terrain} result={result} minute={minute} point={viewPoint} bounds={manifest.bounds_wgs84} onPoint={p=>{selectPoint(p);clearSelection()}}/>:<LocalMap forest={forest} terrain={terrain} result={result} minute={minute} point={viewPoint} exportLabel={job?.state==='completed'?`Run ${job.id.slice(0,8)} | ${job.request.model} | ${job.request.weather.source} | seed ${job.summary?.seed}`:'No saved result | manually selected ignition'} onPoint={p=>{selectPoint(p);clearSelection()}} onError={setError}/>}
      <div className="spread-map-legend"><span><i className="conifer"/>침엽수림</span><span><i className="broadleaf"/>활엽수림</span><span><i className="mixed"/>혼효림</span><span><i className="fire"/>시뮬레이션 영역</span><span className="small-muted">회색/숲 자료 밖 = 미확인 · 안전 지역 아님</span></div>
      <div className="spread-timeline"><span><Layers size={17}/>모델 시간</span><div className="tabs">{(job?.summary?.horizons.map(h=>h.minute)||[10,30,60]).map(m=><button key={m} className={minute===m?'active':''} disabled={!job?.summary} onClick={()=>setMinute(m)}>{m}분</button>)}</div><small>실제 도달시각 아님</small></div>
      {job&&<div className="spread-result"><div><span className="eyebrow">{job.state==='completed'?'SAVED RESULT':'CALCULATION'}</span><h3>{job.state==='queued'?'계산 대기 중':job.state==='running'?'확산 계산 중':job.state==='failed'?'계산 실패':modelLabels[job.request.model]}</h3><p>{job.request.weather.source==='manual'?'수동 가상 기상':'기상청 실황'} · {dateTime(job.created_at)} · ID {job.id.slice(0,8)}</p></div>{job.summary&&<><div><span>평균 모의 연소면적</span><strong>{selectedSummary?.mean_area_ha??'—'} <small>ha</small></strong></div><div><span>계산 시간 / 반복</span><strong>{(job.summary.runtime_ms/1000).toFixed(1)} <small>s / {job.summary.runs}회</small></strong></div></>}</div>}
      {job?.summary&&<div className="spread-result-note">{job.request.model==='ca'?'영역 색은 10·50·90% 이상 반복 실행에서 연소한 셀의 중첩입니다. 실제 화재 확률이나 신뢰구간이 아닙니다.':'이 결과는 원형/타원 기하 기준선입니다. CA 결과와 같은 조건에서 비교하세요.'} 입력을 변경해도 저장된 결과는 바뀌지 않습니다. 새 계산을 실행하세요.</div>}
      {job&&<p className="small-muted" data-testid="saved-event-link">저장된 연결 알람: {job.request.event_id||'없음 · 독립 시나리오'}</p>}
      {job?.state==='completed'&&result.features.length>0&&<button className="text-button spread-map-export" onClick={()=>downloadBlob(new Blob([JSON.stringify({...result,experiment:{id:job.id,created_at:job.created_at,request:job.request,summary:job.summary,context:job.context,research_only:true}},null,2)],{type:'application/geo+json'}),`ember-spread-${job.id}.geojson`)}><Download size={14}/>입력·자료 해시·결과 GeoJSON 저장</button>}
    </section></div>
    <div className="spread-bottom"><section className="panel"><div className="section-heading"><h2><RefreshCw size={18}/>최근 시뮬레이션</h2><button className="text-button" onClick={()=>void fetchHistory()}>새로고침</button></div>{history.length?<div className="spread-history">{history.map(j=><button key={j.id} onClick={()=>void openJob(j)}><span><strong>{modelLabels[j.request.model]}</strong><small>{dateTime(j.created_at)} · {j.request.horizon_min}모델분 · {j.request.weather.source==='manual'?'가상 기상':'기상청'}</small></span><Badge tone={j.state==='completed'?'success':j.state==='failed'?'danger':'warning'}>{j.state==='completed'?'완료':j.state==='failed'?'실패':'계산 중'}</Badge><ArrowRight size={15}/></button>)}</div>:<p className="small-muted">아직 실행 기록이 없습니다. 첫 시나리오를 실행해보세요.</p>}</section>
    <section className="panel spread-quality"><div className="section-heading"><h2><ShieldCheck size={18}/>자료와 검증 범위</h2></div>
      <div className="spread-risk"><div className="section-heading"><strong>대구광역시 산불위험지수</strong><button className="text-button" disabled={dangerBusy} onClick={()=>void getDanger()} aria-label="대구 산불위험지수 새로고침">{dangerBusy?'조회 중':'새로고침'}</button></div>
      {danger?.available&&danger.current?<><p>기준시각 {dateTime(danger.current.valid_at)} {danger.fresh?'':'· 오래된 자료'}</p><div className="spread-risk-values"><span>평균 <b>{danger.current.mean}</b></span><span>최소 {danger.current.minimum}</span><span>최대 {danger.current.maximum}</span></div>
      {!!danger.forecasts?.length&&<p>이후 자료: {danger.forecasts.slice(0,3).map(r=>`${dateTime(r.valid_at)} 평균 ${r.mean}`).join(' / ')}</p>}</>:<p>{dangerBusy?'공식 API 조회 중…':danger?.message||'위험지수 아직 조회하지 않음'}</p>}
      <p>{danger?.available?danger.message:status.nifos?.message}</p></div>
      <p>임상도 {manifest.forest_features}영역 · 토양도 {manifest.soil_features}영역 · 사용 가능한 숲 격자 {manifest.known_forest_cells}개</p><p>자료 갱신년도 {manifest.years.filter(y=>y!=='unknown').join(' · ')}. 토양도는 아직 확산 계수에 사용하지 않습니다.</p><code>DATA {manifest.data_sha256.slice(0,20)}…</code>{[...manifest.warnings,...(job?.summary?.warnings||[]).filter(w=>!manifest.warnings.includes(w))].map(w=><p key={w} className="small-muted">• {w}</p>)}</section></div>
  </div>
}
