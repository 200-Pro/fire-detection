// @vitest-environment jsdom
import React from 'react'
import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,render,waitFor} from '@testing-library/react'
import NaverMap from './NaverMap'
vi.mock('./api',()=>({api:vi.fn(async()=>({enabled:true,client_id:'public-test-id'}))}))
afterEach(()=>{cleanup();delete window.naver;vi.unstubAllGlobals()})
it('detaches camera overlays before destroying the SDK map on page switching',async()=>{
  const operations:string[]=[];let destroyed=false
  const removeListener=vi.fn()
  class TestMap {setMapTypeId(){} panTo(){} getCenter(){return {}} destroy(){destroyed=true;operations.push('destroy')}}
  class Marker {setMap(value:null){if(destroyed)throw new Error('detaching from destroyed map');operations.push('detach')}}
  class Coordinate {constructor(..._args:unknown[]) {}}
  window.naver={maps:{Map:TestMap,Marker,LatLng:Coordinate,Point:Coordinate,
    MapTypeId:{HYBRID:'hybrid',NORMAL:'normal'},Event:{addListener:vi.fn(()=>({})),removeListener,trigger:vi.fn()}}}
  vi.stubGlobal('ResizeObserver',class {observe(){} disconnect(){}})
  const view=render(<NaverMap showIgnition={false} point={{latitude:35.8,longitude:128.6}}
    cameras={[{id:'E100002',name:'가창삼거리',latitude:35.8,longitude:128.6}]}/> )
  await waitFor(()=>expect(removeListener).not.toHaveBeenCalled())
  await waitFor(()=>expect(view.container.querySelector('.small-muted')).toBeNull())
  view.unmount()
  expect(operations).toEqual(['detach','destroy'])
})
