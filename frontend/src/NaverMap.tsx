import {useEffect,useRef,useState} from 'react'
import type {FeatureCollection} from 'geojson'
import {api} from './api'
import './ProviderPages.css'

export type MapPoint={latitude:number;longitude:number}
export type MapCamera=MapPoint&{id:string;name:string}
// External SDK objects are dynamic; never expose the server API Secret here.
type SDK=any
declare global {interface Window {naver?:{maps:SDK};navermap_authFailure?:()=>void}}
let sdkPromise:Promise<SDK>|undefined
export function loadNaver(id:string):Promise<SDK>{
  if(window.naver?.maps)return Promise.resolve(window.naver.maps)
  if(!sdkPromise)sdkPromise=new Promise((resolve,reject)=>{
    const script=document.createElement('script')
    const timer=setTimeout(()=>{script.remove();sdkPromise=undefined;reject(new Error('네이버 지도 연결 시간이 초과되었습니다.'))},20000)
    const fail=()=>{clearTimeout(timer);script.remove();sdkPromise=undefined;reject(new Error('네이버 지도 인증 실패입니다. 등록 Web URL과 Dynamic Map 권한을 확인하세요.'))}
    window.navermap_authFailure=fail
    script.src=`https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=${encodeURIComponent(id)}`
    script.referrerPolicy='strict-origin-when-cross-origin'
    script.onload=()=>{clearTimeout(timer);if(window.naver?.maps)resolve(window.naver.maps);else fail()}
    script.onerror=fail
    document.head.appendChild(script)
  })
  return sdkPromise
}
const empty:FeatureCollection={type:'FeatureCollection',features:[]}

export default function NaverMap({point,onPoint,forest=empty,terrain=empty,result=empty,minute=30,bounds,cameras=[],onCamera,selectedCamera,showIgnition=true}:{
  point:MapPoint;onPoint?:(p:MapPoint)=>void;forest?:FeatureCollection;terrain?:FeatureCollection;result?:FeatureCollection;
  minute?:number;bounds?:number[];cameras?:MapCamera[];onCamera?:(c:MapCamera)=>void;selectedCamera?:string;showIgnition?:boolean
}){
  const host=useRef<HTMLDivElement>(null),map=useRef<SDK>(null),sdk=useRef<SDK>(null)
  const pointCallback=useRef(onPoint),cameraCallback=useRef(onCamera)
  pointCallback.current=onPoint;cameraCallback.current=onCamera
  const [ready,setReady]=useState(false),[error,setError]=useState(''),[base,setBase]=useState('hybrid')
  const [showForest,setShowForest]=useState(false),[showTerrain,setShowTerrain]=useState(false)
  useEffect(()=>{
    let stopped=false,observer:ResizeObserver|undefined,handle:SDK
    api<{enabled:boolean;client_id:string}>('/maps/config').then(async config=>{
      if(!config.enabled)throw new Error('네이버 지도 ID가 설정되지 않았습니다. 로컬 GIS 지도로 전환할 수 있습니다.')
      const n=await loadNaver(config.client_id)
      if(stopped||!host.current)return
      sdk.current=n
      const m=new n.Map(host.current,{center:new n.LatLng(point.latitude,point.longitude),zoom:14,
        mapTypeId:n.MapTypeId.HYBRID,zoomControl:true,scaleControl:true,mapDataControl:true,
        logoControl:true,mapTypeControl:false,minZoom:7,maxZoom:19})
      map.current=m
      handle=n.Event.addListener(m,'click',(e:SDK)=>pointCallback.current?.({latitude:e.coord.lat(),longitude:e.coord.lng()}))
      observer=new ResizeObserver(()=>{const center=m.getCenter();n.Event.trigger(m,'resize');m.setCenter(center)})
      observer.observe(host.current);setReady(true)
    }).catch(e=>{if(!stopped)setError((e as Error).message)})
    return()=>{stopped=true;observer?.disconnect();if(handle)sdk.current?.Event.removeListener(handle);map.current?.destroy();map.current=null}
    // One SDK map; changing inputs only updates overlays.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[])
  useEffect(()=>{if(ready)map.current.setMapTypeId(base==='hybrid'?sdk.current.MapTypeId.HYBRID:sdk.current.MapTypeId.NORMAL)},[base,ready])
  useEffect(()=>{if(ready)map.current.panTo(new sdk.current.LatLng(point.latitude,point.longitude))},[ready,point.latitude,point.longitude])
  useEffect(()=>{
    if(!ready)return
    const n=sdk.current,m=map.current,overlays:SDK[]=[],handles:SDK[]=[]
    const coords=(ring:number[][])=>ring.map(c=>new n.LatLng(c[1],c[0]))
    function polygons(data:FeatureCollection,kind:'forest'|'terrain'|'spread'){
      for(const f of data.features){
        if(kind==='spread'&&Number(f.properties?.minute)!==minute)continue
        const g=f.geometry;if(g.type!=='Polygon'&&g.type!=='MultiPolygon')continue
        const shapes=g.type==='Polygon'?[g.coordinates]:g.coordinates
        const frequency=Number(f.properties?.frequency_threshold||0)
        const color=kind==='spread'?(frequency>=.9?'#e34124':frequency>=.5?'#ff7b32':'#ffc05c'):kind==='forest'?'#2d9866':'#c4d7c0'
        for(const shape of shapes)overlays.push(new n.Polygon({map:m,paths:shape.map(coords),fillColor:color,
          fillOpacity:kind==='spread'?.38:kind==='forest'?.18:.1,strokeColor:color,strokeWeight:kind==='spread'?2:1,
          strokeOpacity:.75,clickable:false,zIndex:kind==='spread'?20:5}))
      }
    }
    if(showTerrain)polygons(terrain,'terrain')
    if(showForest)polygons(forest,'forest')
    polygons(result,'spread')
    if(bounds?.length===4){const [w,s,e,north]=bounds;overlays.push(new n.Polygon({map:m,
      paths:coords([[w,s],[e,s],[e,north],[w,north],[w,s]]),fillOpacity:0,strokeColor:'#e0be74',strokeWeight:2,strokeStyle:'dash',clickable:false}))}
    if(showIgnition)overlays.push(new n.Marker({map:m,position:new n.LatLng(point.latitude,point.longitude),title:'직접 지정한 가상 발화점',
      icon:{content:'<span class="ignition-pin" aria-label="가상 발화점">🔥</span>',anchor:new n.Point(15,30)},zIndex:100}))
    for(const c of cameras){const marker=new n.Marker({map:m,position:new n.LatLng(c.latitude,c.longitude),title:c.name,
      icon:{content:`<span class="cctv-pin ${c.id===selectedCamera?'selected':''}">▣</span>`,anchor:new n.Point(15,15)},zIndex:50})
      overlays.push(marker);handles.push(n.Event.addListener(marker,'click',()=>cameraCallback.current?.(c)))}
    return()=>{handles.forEach(h=>n.Event.removeListener(h));overlays.forEach(o=>o.setMap(null))}
  },[ready,forest,terrain,result,minute,point,showForest,showTerrain,bounds,cameras,selectedCamera,showIgnition])
  return <div className="naver-map-wrap"><div className="map-toolbar"><div className="tabs"><button className={base==='hybrid'?'active':''} onClick={()=>setBase('hybrid')}>위성·도로</button><button className={base==='normal'?'active':''} onClick={()=>setBase('normal')}>일반지도</button></div>
    {!!forest.features.length&&<label><input type="checkbox" checked={showForest} onChange={e=>setShowForest(e.target.checked)}/>임상도</label>}
    {!!terrain.features.length&&<label><input type="checkbox" checked={showTerrain} onChange={e=>setShowTerrain(e.target.checked)}/>지형 격자</label>}</div>
    {error&&<div className="notice warning" role="alert">{error}</div>}<div ref={host} className="spread-map naver-map" aria-label="네이버 위성·일반지도"/>
    {!ready&&!error&&<p className="small-muted">네이버 지도 연결 중…</p>}
    <p className="map-footnote">위성사진은 실시간 영상이 아닙니다. {bounds?.length===4?'노란 점선은 지형 데이터 범위이며, 내부에도 산림 자료 공백이 있습니다. 지도 밖·자료 밖은 안전 지역이 아닙니다.':'표시된 CCTV 좌표는 카메라 설치 위치이며 실제 발화 위치가 아닙니다.'}</p>
    <p className="map-footnote">네이버 지도는 화면에서 열람합니다. 지도 캡처·타일 재배포 대신 연구 결과 GeoJSON 또는 로컬 GIS PNG를 이용하세요.</p></div>
}

export function AddressSearch({point,onPoint}:{point:MapPoint;onPoint:(p:MapPoint)=>void}){
  const [query,setQuery]=useState(''),[items,setItems]=useState<(MapPoint&{address:string})[]>([]),[message,setMessage]=useState(''),[busy,setBusy]=useState(false)
  const version=useRef(0)
  useEffect(()=>{version.current++;setMessage('');setItems([])},[point.latitude,point.longitude])
  useEffect(()=>()=>{version.current++},[])
  async function search(){const v=++version.current;setBusy(true);setMessage('');setItems([])
    try{const r=await api<{items:(MapPoint&{address:string})[]}>(`/maps/geocode?query=${encodeURIComponent(query.trim())}`);if(v===version.current){setItems(r.items);if(!r.items.length)setMessage('주소 결과가 없습니다. 도로명·지번 주소로 입력하세요.')}}
    catch(e){if(v===version.current)setMessage((e as Error).message)}finally{setBusy(false)}}
  async function reverse(){const v=++version.current;setBusy(true);setMessage('');try{const r=await api<{address:string|null}>(`/maps/reverse?latitude=${point.latitude}&longitude=${point.longitude}`);if(v===version.current)setMessage(r.address||'상세 주소가 없는 위치입니다.')}
    catch(e){if(v===version.current)setMessage((e as Error).message)}finally{setBusy(false)}}
  return <div className="address-search"><label>주소로 발화 지점 찾기<input value={query} onChange={e=>setQuery(e.target.value)} maxLength={200} placeholder="도로명 또는 지번 주소" onKeyDown={e=>{if(e.key==='Enter'&&query.trim().length>=2&&!busy)void search()}}/></label>
    <div className="button-row"><button className="button" disabled={busy||query.trim().length<2} onClick={()=>void search()}>주소 검색</button><button className="text-button" disabled={busy} onClick={()=>void reverse()}>선택 좌표 주소 확인</button></div>
    {items.map((r,i)=><button className="address-result" key={i} onClick={()=>onPoint(r)}>{r.address}</button>)}{message&&<p className="small-muted" role="status">{message}</p>}
    <p className="small-muted">주소 위치는 발화점 확정이 아닙니다. 지도에서 확인하세요. 확산 계산은 준비된 숲 격자 안에서만 가능합니다.</p></div>
}
