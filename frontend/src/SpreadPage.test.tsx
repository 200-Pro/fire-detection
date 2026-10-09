// @vitest-environment jsdom
import React from 'react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import SpreadPage from './SpreadPage'
import {api} from './api'

const mapState=vi.hoisted(()=>({sources:{} as Record<string,{setData:ReturnType<typeof vi.fn>}>}))
vi.mock('./api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)}),dateTime:()=> 'test time'}))
vi.mock('maplibre-gl',()=>({
  setWorkerUrl:vi.fn(),
  Map:class {
    handlers:Record<string,(()=>void)[]>={}
    constructor(){queueMicrotask(()=>this.handlers.load?.forEach(fn=>fn()))}
    addControl(){} addLayer(){} setFilter(){} resize(){} remove(){} easeTo(){}
    on(name:string,fn:()=>void){(this.handlers[name]??=[]).push(fn)}
    once(name:string,fn:()=>void){this.on(name,fn)} off(){}
    addSource(id:string){mapState.sources[id]={setData:vi.fn()}}
    getSource(id:string){return mapState.sources[id]}
    getLayer(){return true}
    isStyleLoaded(){return false} // Source workers can be loading after map load.
  },NavigationControl:class{},ScaleControl:class{},AttributionControl:class{}
}))
const empty={type:'FeatureCollection',features:[]}
const geometry={type:'FeatureCollection',features:[{type:'Feature',properties:{minute:30},geometry:{type:'Polygon',coordinates:[[[128.5,35.8],[128.6,35.8],[128.6,35.9],[128.5,35.8]]]}}]}
const status={ready:true,manifest:{grid_m:90,default_ignition:{latitude:35.8,longitude:128.5},bounds_wgs84:[],forest_features:3,soil_features:2,known_forest_cells:10,data_sha256:'hash',years:['2025'],warnings:[]}}
const queued={id:'a'.repeat(32),state:'queued',created_at:'2026',request:{latitude:35.8,longitude:128.5,model:'ca',horizon_min:30,weather:{source:'manual'}}}
const completed={...queued,state:'completed',summary:{horizons:[{minute:30,mean_area_ha:2,any_run_area_ha:4}],runtime_ms:200,runs:30,seed:42,grid_m:90,engine_version:'test',boundary_contact:false,warnings:[]}}
beforeEach(()=>{
  vi.stubGlobal('ResizeObserver',class {observe(){} disconnect(){}})
  mapState.sources={}
  vi.mocked(api).mockImplementation(async(path,options)=>{
    if(path==='/spread/status')return status
    if(path==='/spread/forest'||path==='/spread/terrain')return empty
    if(path==='/fire-danger')return {available:false,message:'자료 없음'}
    if(path==='/simulations')return options?.method==='POST'?queued:{items:[]}
    if(path.endsWith('/perimeters')){await new Promise(resolve=>setTimeout(resolve,20));return geometry}
    if(path.startsWith('/simulations/'))return completed
    throw new Error('Unexpected endpoint')
  })
})
afterEach(()=>{cleanup();vi.resetAllMocks();vi.unstubAllGlobals()})

it('blocks execution until the manually chosen research ignition is confirmed',async()=>{
  render(<SpreadPage/>)
  const button=await screen.findByRole('button',{name:'확산 시뮬레이션 실행'})
  expect((button as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('checkbox'))
  expect((button as HTMLButtonElement).disabled).toBe(false)
})

it('keeps completion geometry despite delayed fetch and ongoing style data loading',async()=>{
  render(<SpreadPage/>)
  await screen.findByRole('button',{name:'확산 시뮬레이션 실행'})
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button',{name:'확산 시뮬레이션 실행'}))
  await screen.findByRole('button',{name:'입력·자료 해시·결과 GeoJSON 저장'},{timeout:4000})
  await waitFor(()=>expect(mapState.sources.spread.setData).toHaveBeenCalledWith(geometry))
  const call=vi.mocked(api).mock.calls.find(([path,options])=>path==='/simulations'&&options?.method==='POST')
  expect(JSON.parse(call![1]!.body as string)).toMatchObject({location_confirmed:true,weather_mode:'manual'})
})

it('explains missing GIS instead of rendering a fabricated spread result',async()=>{
  vi.mocked(api).mockImplementation(async path=>path==='/spread/status'?{ready:false,message:'지도 전처리가 필요합니다.'}:{items:[]})
  render(<SpreadPage/>)
  expect(await screen.findByText(/지도 전처리가 필요합니다/)).toBeDefined()
  expect(screen.queryByRole('button',{name:'확산 시뮬레이션 실행'})).toBeNull()
})

it('saves the selected alarm link with the submitted research scenario',async()=>{
  const eventId='c'.repeat(32)
  render(<SpreadPage eventId={eventId}/>)
  await screen.findByRole('button',{name:'확산 시뮬레이션 실행'})
  fireEvent.click(screen.getByRole('checkbox'))
  fireEvent.click(screen.getByRole('button',{name:'확산 시뮬레이션 실행'}))
  await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p,o])=>p==='/simulations'&&o?.method==='POST')).toBe(true))
  const call=vi.mocked(api).mock.calls.find(([p,o])=>p==='/simulations'&&o?.method==='POST')!
  expect(JSON.parse(call[1]!.body as string).event_id).toBe(eventId)
})

it('does not overwrite a newer history selection with a slow older geometry',async()=>{
  const base=vi.mocked(api).getMockImplementation()!
  const a={...completed,id:'a'.repeat(32)},b={...completed,id:'b'.repeat(32),request:{...completed.request,model:'ellipse',event_id:'c'.repeat(32)}}
  let resolveOld!:(value:typeof geometry)=>void
  const newer={...geometry,features:[{...geometry.features[0],properties:{minute:10}}]}
  vi.mocked(api).mockImplementation(async(p,o)=>{
    if(p==='/simulations'&&!o)return {items:[a,b]}
    if(p===`/simulations/${a.id}/perimeters`)return await new Promise(resolve=>{resolveOld=resolve})
    if(p===`/simulations/${b.id}/perimeters`)return newer
    return base(p,o)
  })
  render(<SpreadPage/>)
  fireEvent.click(await screen.findByRole('button',{name:/바람·경사·숲 CA/}))
  fireEvent.click(screen.getByRole('button',{name:/풍향 타원 기준선/}))
  await waitFor(()=>expect(mapState.sources.spread.setData).toHaveBeenLastCalledWith(newer))
  resolveOld(geometry)
  await new Promise(resolve=>setTimeout(resolve,30))
  expect(mapState.sources.spread.setData).toHaveBeenLastCalledWith(newer)
  expect(screen.getByTestId('saved-event-link').textContent).toContain('c'.repeat(32))
})

it('discards weather fetched for a point that has since changed',async()=>{
  const base=vi.mocked(api).getMockImplementation()!
  let resolveWeather!:(value:unknown)=>void
  vi.mocked(api).mockImplementation(async(p,o)=>p.startsWith('/weather?')?await new Promise(resolve=>{resolveWeather=resolve}):base(p,o))
  render(<SpreadPage/>)
  await screen.findByRole('button',{name:'확산 시뮬레이션 실행'})
  fireEvent.change(screen.getByLabelText('기상 입력 방식'),{target:{value:'kma'}})
  fireEvent.click(screen.getByRole('button',{name:'선택 지점 실황 조회'}))
  fireEvent.change(screen.getByLabelText('발화점 위도'),{target:{value:'35.9'}})
  resolveWeather({available:true,fresh:true,source:'kma',wind_speed_ms:99,wind_from_deg:270,humidity_pct:40,rain_mm:0,temperature_c:20})
  await new Promise(resolve=>setTimeout(resolve,30))
  expect(screen.queryByText('기상청 관측값')).toBeNull()
})
