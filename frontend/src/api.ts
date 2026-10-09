export class ApiError extends Error {constructor(message:string,public status:number){super(message)}}
export async function api<T>(path:string, options:RequestInit={}):Promise<T>{
  const headers=new Headers(options.headers);headers.set('X-Ember-Client','web')
  if(typeof options.body==='string')headers.set('Content-Type','application/json')
  const response=await fetch('/api'+path,{...options,headers,credentials:'same-origin'})
  if(!response.ok){let detail='요청을 처리하지 못했습니다.';try{const body=await response.json();detail=typeof body.detail==='string'?body.detail:detail}catch{};throw new ApiError(detail,response.status)}
  return response.json()
}
export const json=(method:string,body?:unknown)=>({method,...(body!==undefined?{body:JSON.stringify(body)}:{})})
export const dateTime=(value:string)=>new Date(value).toLocaleString('ko-KR',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})
export const since=(value:string|null)=>{if(!value)return '아직 수신 전';const seconds=Math.max(0,Math.round((Date.now()-new Date(value).getTime())/1000));return seconds<60?`${seconds}초 전`:`${Math.floor(seconds/60)}분 전`}
