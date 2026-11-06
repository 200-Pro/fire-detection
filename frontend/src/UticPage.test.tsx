// @vitest-environment jsdom
import React from 'react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import UticPage from './UticPage'
import {api} from './api'
vi.mock('./api',()=>({api:vi.fn(),json:(method:string)=>({method}),dateTime:()=> 'test time'}))
vi.mock('./NaverMap',()=>({default:()=> <div>map mock</div>}))
vi.mock('hls.js',()=>({default:class {static isSupported(){return false}}}))
const item={id:'E100002',name:'가창삼거리',center:'대구교통정보센터',latitude:35.801472,longitude:128.622411,provider:'utic'}
beforeEach(()=>{
  vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{})
  vi.spyOn(HTMLMediaElement.prototype,'load').mockImplementation(()=>{})
  vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue(undefined)
  vi.mocked(api).mockImplementation(async(path)=>path.includes('/catalog')?
    {items:[item],source_total:14606,source_invalid_coordinates:2,missing_from_live_list:0,local_daegu_count:177,fetched_at:1}:
    path.endsWith('/probe')?{decoded:true,width:1080,height:720,jpeg_bytes:100,frame_base64:'AA==',http_requests:3,checked_at:1,ai_analysis:false,evidence_saved:false}:
    {url:'https://carcctv.daegu.go.kr/live3/_definst_/ch206.stream/playlist.m3u8',video_type:4,max_preview_seconds:60})
})
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.resetAllMocks();vi.useRealTimers()})
async function select(){fireEvent.click(screen.getByRole('button',{name:'UTIC 대구 목록 조회'}));fireEvent.click(await screen.findByRole('button',{name:/가창삼거리/}))}
it('does not auto-connect or request media when selecting a catalog item',async()=>{
  render(<UticPage/>);expect(api).not.toHaveBeenCalled();await select()
  expect(vi.mocked(api).mock.calls.map(([p])=>p)).toEqual(['/utic/catalog?refresh=false'])
  expect(screen.getByText(/지금은 목록·선택 재생/)).toBeTruthy()
})
it('requests exactly one server probe only on explicit click and labels the image honestly',async()=>{
  render(<UticPage/>);await select()
  fireEvent.click(screen.getByRole('button',{name:'서버 프레임 1장 확인'}))
  const image=await screen.findByAltText('UTIC 서버에서 한 번 수신한 정지 프레임')
  expect(image.getAttribute('src')).toBe('data:image/jpeg;base64,AA==')
  expect(screen.getByRole('status').textContent).toContain('AI 분석·알람·파일 저장 없음')
  expect(vi.mocked(api).mock.calls.filter(([p])=>p.endsWith('/probe'))).toHaveLength(1)
  expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/register')||p.includes('/monitoring'))).toBe(false)
})
it('stops selected playback on the bounded deadline',async()=>{
  render(<UticPage/>);await select()
  vi.mocked(api).mockResolvedValueOnce({url:'https://carcctv.daegu.go.kr/live3/_definst_/ch206.stream/playlist.m3u8',video_type:4,max_preview_seconds:1})
  fireEvent.click(screen.getByRole('button',{name:'UTIC 영상 재생 · 최대 60초'}))
  await screen.findByLabelText('UTIC 선택 영상')
  await waitFor(()=>expect(screen.queryByLabelText('UTIC 선택 영상')).toBeNull(),{timeout:2000})
  expect(vi.mocked(api).mock.calls.filter(([p])=>p.endsWith('/stream'))).toHaveLength(1)
})
