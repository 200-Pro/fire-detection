// @vitest-environment jsdom
import React from 'react'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {AddressSearch} from './NaverMap'
import {api} from './api'
vi.mock('./api',()=>({api:vi.fn()}))
beforeEach(()=>vi.resetAllMocks())
afterEach(()=>cleanup())
it('searches addresses only on user request and returns coordinates',async()=>{
  const onPoint=vi.fn()
  vi.mocked(api).mockResolvedValue({items:[{address:'대구 남구 테스트',latitude:35.8,longitude:128.6}]})
  render(<AddressSearch point={{latitude:35.8,longitude:128.6}} onPoint={onPoint}/>)
  expect(api).not.toHaveBeenCalled()
  fireEvent.change(screen.getByPlaceholderText('도로명 또는 지번 주소'),{target:{value:'대구 남구'}})
  fireEvent.click(screen.getByRole('button',{name:'주소 검색'}))
  fireEvent.click(await screen.findByRole('button',{name:'대구 남구 테스트'}))
  expect(onPoint).toHaveBeenCalledWith({address:'대구 남구 테스트',latitude:35.8,longitude:128.6})
  expect(api).toHaveBeenCalledWith('/maps/geocode?query='+encodeURIComponent('대구 남구'))
})
it('does not automatically reverse geocode clicks and explains empty address',async()=>{
  vi.mocked(api).mockResolvedValue({address:null})
  render(<AddressSearch point={{latitude:35.8,longitude:128.6}} onPoint={vi.fn()}/>)
  expect(api).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button',{name:'선택 좌표 주소 확인'}))
  await waitFor(()=>expect(screen.getByRole('status').textContent).toContain('상세 주소가 없는'))
})
