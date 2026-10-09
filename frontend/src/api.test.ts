// @vitest-environment jsdom
import {afterEach,describe,expect,it,vi} from 'vitest'
import {api,json,since,ApiError} from './api'
afterEach(()=>vi.unstubAllGlobals())
describe('API contract',()=>{
  it('adds same-origin credentials and CSRF header',async()=>{const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({ok:true})});vi.stubGlobal('fetch',fetch);expect(await api('/x',json('POST',{a:1}))).toEqual({ok:true});const [,options]=fetch.mock.calls[0];expect(options.credentials).toBe('same-origin');expect(options.headers.get('X-Ember-Client')).toBe('web');expect(options.headers.get('Content-Type')).toBe('application/json')})
  it('keeps binary frame headers',async()=>{const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({})});vi.stubGlobal('fetch',fetch);await api('/x',{body:new Blob(),method:'POST',headers:{'Content-Type':'image/jpeg'}});expect(fetch.mock.calls[0][1].headers.get('Content-Type')).toBe('image/jpeg')})
  it('reports authentication errors',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:401,json:async()=>({detail:'login required'})}));try{await api('/x');expect.unreachable()}catch(e){expect(e).toBeInstanceOf(ApiError);expect((e as ApiError).status).toBe(401)}})
  it('does not serialize absent POST bodies',()=>expect(json('POST')).toEqual({method:'POST'}))
  it('has readable missing-frame state',()=>expect(since(null)).toBe('아직 수신 전'))
})
