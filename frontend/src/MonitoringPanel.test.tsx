// @vitest-environment jsdom
import React from 'react'
import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import MonitoringPanel from './MonitoringPanel'
import {api} from './api'
vi.mock('./api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body:JSON.stringify(body)}),dateTime:()=> 'time'}))
vi.mock('./NaverMap',()=>({default:()=> <div>map mock</div>}))
afterEach(()=>{cleanup();vi.resetAllMocks()})
it('locks public collection before server approval and permits OFF preparation',async()=>{
  vi.mocked(api).mockImplementation(async path=>path==='/monitoring'?{items:[],server_approved:false,capacity:4}:{camera_id:'x'})
  render(<MonitoringPanel selected={{id:'cat',name:'camera'}}/>)
  await screen.findByText('실제 수집 잠금')
  expect((screen.getByRole('button',{name:'상시 감시 시작'}) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button',{name:'설정만 저장 · 수집 OFF'}))
  await screen.findByText('화면–지도 자동 위치 보정')
  const call=vi.mocked(api).mock.calls.find(([path])=>path.endsWith('/monitor'))!
  expect(JSON.parse(call[1]!.body as string).enabled).toBe(false)
})
