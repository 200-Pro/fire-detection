// @vitest-environment jsdom
import React from 'react'
import {afterEach,it,expect,vi} from 'vitest'
import {render,screen,fireEvent,cleanup,waitFor} from '@testing-library/react'
import CameraViewer,{ArchiveCameraDialog,ArchivedCameras} from './CameraViewer'
import {CameraCard,EventRow} from './components'
import {api} from './api'
import type {Camera,Alert} from './types'
vi.mock('./api',()=>({api:vi.fn(),dateTime:(s:string)=>s,since:()=>''}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
const camera:Camera={id:'c',name:'대구 CCTV',location:'35.8,128.6 · 설치점',kind:'its',enabled:true,online:false,signal:'offline',last_seen:'2026-10-10',frames:5,latency_ms:10,preview_url:'/preview',preview_stale:true,monitor_message:'제공기관 영상 응답 오류 (403)입니다.'}
it('retains a stale preview without claiming live',()=>{render(<CameraCard camera={camera} tick={1} onSelect={()=>{}} onPair={()=>{}}/>);expect(screen.getByRole('img').getAttribute('src')).toBe('/preview?v=1');expect(screen.getByText('과거 프레임')).toBeDefined();expect(screen.queryByText('수신 중')).toBeNull()})
it('opening a viewer does not connect to a stream until requested',()=>{render(<CameraViewer camera={camera} tick={1} onClose={()=>{}}/>);expect(api).not.toHaveBeenCalled();expect(screen.getByText(/과거 프레임이며/)).toBeDefined();expect(screen.getByText(/403/)).toBeDefined();expect(screen.getByRole('button',{name:'실시간 영상 재생'})).toBeDefined()})
it('archive is explicit and preserves history messaging',async()=>{vi.mocked(api).mockResolvedValue({ok:true});const done=vi.fn();render(<ArchiveCameraDialog camera={camera} onClose={()=>{}} onArchived={done}/>);expect(api).not.toHaveBeenCalled();expect(screen.getByText(/기존 알람·증거는 유지/)).toBeDefined();fireEvent.click(screen.getByRole('button',{name:'목록에서 제거'}));await waitFor(()=>expect(done).toHaveBeenCalledOnce());expect(api).toHaveBeenCalledWith('/cameras/c/archive',{method:'POST'})})
it('canceling archive does not mutate the camera',()=>{const close=vi.fn();render(<ArchiveCameraDialog camera={camera} onClose={close} onArchived={()=>{}}/>);fireEvent.click(screen.getByRole('button',{name:'취소'}));expect(close).toHaveBeenCalledOnce();expect(api).not.toHaveBeenCalled()})
it('loads archived cameras on demand and restores explicitly',async()=>{vi.mocked(api).mockResolvedValueOnce([camera]).mockResolvedValueOnce({ok:true}).mockResolvedValueOnce([]);const done=vi.fn();render(<ArchivedCameras onRestored={done}/>);expect(api).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'제거된 카메라 보기'}));await screen.findByRole('button',{name:'복원'});fireEvent.click(screen.getByRole('button',{name:'복원'}));await waitFor(()=>expect(done).toHaveBeenCalledOnce());expect(api).toHaveBeenCalledWith('/cameras/c/restore',{method:'POST'})})
it('shows smoke and installation location on an alarm',()=>{const event:Alert={id:'e',camera_id:'c',camera_name:'대구 CCTV',camera_location:'대구 도동대교',candidate_label:'smoke',kind:'live',state:'new',created_at:'today',confidence:.8,model_sha256:'a',policy_sha256:'b',detections:[],snapshot_url:null,note:''};render(<EventRow event={event} onClick={()=>{}}/>);expect(screen.getByText(/연기 감지 후보/)).toBeDefined();expect(screen.getByText('대구 도동대교')).toBeDefined()})
