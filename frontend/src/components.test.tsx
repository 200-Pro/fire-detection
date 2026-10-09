// @vitest-environment jsdom
import React from 'react'
import {afterEach,describe,it,expect,vi} from 'vitest'
import {render,screen,fireEvent,cleanup} from '@testing-library/react'
import {CameraCard,EventRow,Modal} from './components'
import type {Camera,Alert} from './types'
afterEach(cleanup)
const camera:Camera={id:'1',name:'Phone',location:'Field',kind:'browser',enabled:true,online:false,signal:'offline',last_seen:null,frames:0,latency_ms:null,preview_url:null}
const event:Alert={id:'e',camera_id:'1',camera_name:'Phone',kind:'demo',state:'new',created_at:'2026-10-05T00:00:00Z',confidence:.8,model_sha256:'a',policy_sha256:'b',detections:[],snapshot_url:null,note:''}
describe('monitoring UI',()=>{
  it('does not show an offline camera as live',()=>{render(<CameraCard camera={camera} tick={0} onSelect={()=>{}} onPair={()=>{}}/>);expect(screen.getByText('OFFLINE')).toBeDefined();expect(screen.queryByText('LIVE')).toBeNull()})
  it('opens the camera pairing control',()=>{const action=vi.fn();render(<CameraCard camera={camera} tick={0} onSelect={()=>{}} onPair={action}/>);fireEvent.click(screen.getByRole('button',{name:'Phone 연결'}));expect(action).toHaveBeenCalledOnce()})
  it('marks demo alerts and opens evidence',()=>{const action=vi.fn();render(<EventRow event={event} onClick={action}/>);expect(screen.getByText(/예제 데이터/)).toBeDefined();fireEvent.click(screen.getByRole('button'));expect(action).toHaveBeenCalledOnce()})
  it('closes the dialog on Escape',()=>{const close=vi.fn();render(<Modal title="Test" onClose={close}><button>Continue</button></Modal>);fireEvent.keyDown(document,{key:'Escape'});expect(close).toHaveBeenCalledOnce()})
})
