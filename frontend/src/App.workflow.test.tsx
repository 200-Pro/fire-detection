// @vitest-environment jsdom
import React from 'react'
import {it,expect,vi,afterEach,beforeEach} from 'vitest'
import {render,screen,fireEvent,cleanup,waitFor,act} from '@testing-library/react'
import App from './App'
const mocks=vi.hoisted(()=>({api:vi.fn(),sockets:[] as {onmessage?: (e:{data:string})=>void}[]}))
vi.mock('./api',()=>({api:mocks.api,json:(method:string,body?:unknown)=>({method,body:JSON.stringify(body)}),dateTime:()=>'',since:()=>''}))
const camera={id:'cam',name:'시험 CCTV',location:'대구 설치 위치',kind:'its',enabled:true,online:true,signal:'clear',last_seen:null,frames:10,latency_ms:1,preview_url:'/preview'}
const event={id:'event',camera_id:'cam',camera_name:camera.name,camera_location:camera.location,candidate_label:'smoke',kind:'live',state:'new',created_at:'today',confidence:.8,model_sha256:'a',policy_sha256:'b',detections:[],snapshot_url:null,note:''}
beforeEach(()=>{localStorage.clear();mocks.sockets.length=0;vi.stubGlobal('WebSocket',class {onmessage?: (e:{data:string})=>void;constructor(){mocks.sockets.push(this)}close(){}});mocks.api.mockImplementation(async(path:string)=>{
  if(path==='/auth/me')return {username:'admin'}
  if(path==='/cameras')return [camera]
  if(path.startsWith('/events'))return {items:[]}
  if(path==='/stats')return {online:1,cameras:1,unresolved:0,events_24h:0,latency_ms:1}
  if(path==='/system')return {demo_enabled:false,model:{ready:true},max_cameras:8}
  throw Error('Unexpected path '+path)
})})
afterEach(()=>{cleanup();vi.clearAllMocks();vi.unstubAllGlobals();vi.useRealTimers()})
it('manual alarm button opens camera management without starting another analyzer',async()=>{render(<App/>);await screen.findByRole('button',{name:'시험 CCTV 보기'});await act(async()=>mocks.sockets[0].onmessage?.({data:JSON.stringify({type:'alert.created',event})}));await screen.findByText('연기 감지 후보가 도착했어요.');fireEvent.click(screen.getByRole('button',{name:'카메라 화면 보기'}));await screen.findByRole('dialog',{name:'시험 CCTV'});expect(screen.getByText('대구 설치 위치')).toBeDefined();expect(mocks.api.mock.calls.some(([path])=>path.includes('/monitor')||path.includes('/stream'))).toBe(false)})
it('opt-in auto opening only opens the candidate camera on a new live event',async()=>{render(<App/>);await screen.findByRole('button',{name:'시험 CCTV 보기'});fireEvent.click(screen.getByRole('button',{name:'카메라 관리'}));fireEvent.click(screen.getByRole('checkbox',{name:/새 감지 알람/}));await waitFor(()=>expect(localStorage.getItem('ember.autoOpenCamera')).toBe('true'));await act(async()=>mocks.sockets[0].onmessage?.({data:JSON.stringify({type:'alert.created',event})}));await screen.findByRole('dialog',{name:'시험 CCTV'});expect(mocks.api.mock.calls.some(([path])=>path.includes('/stream'))).toBe(false)})
it('reconnects an existing session after server downtime instead of showing login',async()=>{vi.useFakeTimers();mocks.api.mockRejectedValueOnce(Object.assign(new Error('Unavailable'),{status:503}));render(<App/>);await act(async()=>{});expect(screen.getByText(/서버에 재연결 중/)).toBeDefined();expect(screen.queryByLabelText('비밀번호')).toBeNull();await act(async()=>{await vi.advanceTimersByTimeAsync(3000)});expect(screen.getByRole('button',{name:'시험 CCTV 보기'})).toBeDefined()})
