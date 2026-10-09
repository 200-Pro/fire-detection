// @vitest-environment jsdom
import React from 'react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import CctvPage from './CctvPage'
import {api} from './api'
vi.mock('./api',()=>({api:vi.fn(),json:(method:string)=>({method}),dateTime:()=> 'test time'}))
vi.mock('./NaverMap',()=>({default:()=> <div>map mock</div>}))
vi.mock('hls.js',()=>({default:class {static isSupported(){return false}}}))
const item={id:'catalog-id',name:'대구 테스트 지점',latitude:35.8,longitude:128.6,road:'ex',video_type:4}
beforeEach(()=>{
  vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{})
  vi.spyOn(HTMLMediaElement.prototype,'load').mockImplementation(()=>{})
  vi.mocked(api).mockImplementation(async(path)=>path==='/monitoring'?{items:[],server_approved:false,capacity:4}:path.includes('/catalog')?{items:[item],fetched_at:1,region:'대구'}:{url:'https://video.example.org/a.m3u8',video_type:4,name:item.name})
})
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.resetAllMocks()})
it('does not auto-query or start inference and requires the consent gate',async()=>{
  render(<CctvPage/>)
  expect(vi.mocked(api).mock.calls.some(([path])=>path.includes('/catalog')||path.includes('/stream'))).toBe(false)
  fireEvent.click(screen.getByRole('button',{name:'대구 주변 목록 조회'}))
  fireEvent.click(await screen.findByRole('button',{name:/대구 테스트 지점/}))
  const start=await screen.findByRole('button',{name:'프레임 AI 분석 · 최대 2분'})
  expect((start as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('checkbox',{name:/신청 목적에 영상 AI 분석/}))
  await waitFor(()=>expect((start as HTMLButtonElement).disabled).toBe(false))
  expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith('/register')||path.endsWith('/frames'))).toBe(false)
})
it('clears the old catalog on a changed format without requesting every format',async()=>{
  render(<CctvPage/>)
  fireEvent.click(screen.getByRole('button',{name:'대구 주변 목록 조회'}))
  await screen.findByRole('button',{name:/대구 테스트 지점/})
  fireEvent.change(screen.getByLabelText('영상 형식'),{target:{value:'5'}})
  expect(screen.queryByRole('button',{name:/대구 테스트 지점/})).toBeNull()
  expect(vi.mocked(api).mock.calls.filter(([path])=>path.includes('/catalog'))).toHaveLength(1)
})
