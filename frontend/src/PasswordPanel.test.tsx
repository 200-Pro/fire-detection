// @vitest-environment jsdom
import React from 'react'
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import PasswordPanel from './PasswordPanel'
import {api} from './api'
vi.mock('./api',()=>({api:vi.fn(),json:(method:string,body:unknown)=>({method,body})}))
afterEach(cleanup)
beforeEach(()=>vi.mocked(api).mockReset())
function fill(repeat='test-only-long-password'){
  fireEvent.change(screen.getByLabelText('현재 비밀번호'),{target:{value:'test-current'}})
  fireEvent.change(screen.getByLabelText('새 비밀번호 (16자 이상)'),{target:{value:'test-only-long-password'}})
  fireEvent.change(screen.getByLabelText('새 비밀번호 확인'),{target:{value:repeat}})
  fireEvent.submit(screen.getByRole('button',{name:'비밀번호 변경'}).closest('form')!)
}
describe('password form',()=>{
  it('does not submit mismatched passwords',()=>{
    render(<PasswordPanel/>);fill('different-password')
    expect(screen.getByRole('alert').textContent).toContain('일치하지 않습니다')
    expect(api).not.toHaveBeenCalled()
  })
  it('clears sensitive fields after the user submits a successful change',async()=>{
    vi.mocked(api).mockResolvedValue({ok:true})
    render(<PasswordPanel/>);fill()
    await waitFor(()=>expect(screen.getByRole('status').textContent).toContain('변경되었습니다'))
    expect((screen.getByLabelText('현재 비밀번호') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('새 비밀번호 (16자 이상)') as HTMLInputElement).value).toBe('')
    expect(api).toHaveBeenCalledOnce()
  })
})
