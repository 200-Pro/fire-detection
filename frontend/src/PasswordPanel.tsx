import {useState, type FormEvent} from 'react'
import {KeyRound, LoaderCircle, ShieldCheck} from 'lucide-react'
import {api, json} from './api'
import './PasswordPanel.css'

export default function PasswordPanel(){
  const [current,setCurrent]=useState(''),[password,setPassword]=useState(''),[repeat,setRepeat]=useState('')
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState(false)
  async function submit(event:FormEvent){
    event.preventDefault();setError('');setSaved(false)
    if(password!==repeat){setError('새 비밀번호 두 개가 일치하지 않습니다.');return}
    setBusy(true)
    try{
      await api('/auth/password',json('POST',{current_password:current,new_password:password}))
      setCurrent('');setPassword('');setRepeat('');setSaved(true)
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  return <section className="panel account-panel"><div className="section-heading"><h2><KeyRound size={20}/>계정 보안</h2></div>
    <p className="small-muted">휴대폰 연결 전에 기본 비밀번호를 변경하세요. 다른 로그인 세션은 종료되며 현재 창은 유지됩니다.</p>
    <form onSubmit={submit} className="password-form">
      <div><label htmlFor="current-password">현재 비밀번호</label><input id="current-password" type="password" value={current} onChange={e=>setCurrent(e.target.value)} autoComplete="current-password" required/></div>
      <div><label htmlFor="new-password">새 비밀번호 (16자 이상)</label><input id="new-password" type="password" minLength={16} maxLength={256} value={password} onChange={e=>setPassword(e.target.value)} autoComplete="new-password" required/></div>
      <div><label htmlFor="repeat-password">새 비밀번호 확인</label><input id="repeat-password" type="password" value={repeat} onChange={e=>setRepeat(e.target.value)} autoComplete="new-password" required/></div>
      {error&&<div className="notice error" role="alert">{error}</div>}{saved&&<div className="notice info" role="status"><ShieldCheck size={16}/>비밀번호가 변경되었습니다.</div>}
      <button className="button primary" disabled={busy}>{busy?<LoaderCircle className="spin" size={16}/>:<KeyRound size={16}/>}비밀번호 변경</button>
    </form>
  </section>
}
