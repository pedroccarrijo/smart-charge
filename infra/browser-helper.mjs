import { readFileSync } from 'node:fs'

export const credentials = Object.fromEntries(readFileSync(new URL('../secrets/usuarios-demo.txt', import.meta.url), 'utf8').trim().split(/\r?\n/).map(line => {
  const split=line.indexOf(':'); return [line.slice(0,split),line.slice(split+1).trim()]
}))
export const pause = ms => new Promise(resolve => setTimeout(resolve,ms))
export async function browserSession() {
  let target
  for(let i=0;i<40;i++) { try {target=await(await fetch('http://127.0.0.1:9223/json/new?about:blank',{method:'PUT'})).json();break}catch{await pause(250)} }
  if(!target) throw new Error('Chrome debugging endpoint unavailable')
  const ws=new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject})
  let counter=0
  const pending=new Map(),exceptions=[]
  ws.onmessage=event=>{const data=JSON.parse(event.data);if(data.id&&pending.has(data.id)){pending.get(data.id)(data);pending.delete(data.id)}if(data.method==='Runtime.exceptionThrown')exceptions.push(data.params.exceptionDetails.exception?.description??data.params.exceptionDetails.text)}
  function send(method,params={}) {const id=++counter;return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{pending.delete(id);reject(new Error(`CDP timeout: ${method}`))},20000);pending.set(id,data=>{clearTimeout(timer);data.error?reject(new Error(data.error.message)):resolve(data.result)});ws.send(JSON.stringify({id,method,params}))})}
  async function evaluate(expression){const data=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(data.exceptionDetails)throw new Error(data.exceptionDetails.exception?.description??data.exceptionDetails.text);return data.result.value}
  async function until(expression,timeout=30000){const end=Date.now()+timeout;while(Date.now()<end){if(await evaluate(expression))return;await pause(300)}throw new Error(`Browser condition timed out: ${expression}`)}
  async function login(role){await until("!!document.querySelector('#usuario')");await evaluate(`(()=>{const u=document.querySelector('#usuario'),p=document.querySelector('#senha');u.value=${JSON.stringify(role)};u.dispatchEvent(new Event('input',{bubbles:true}));p.value=${JSON.stringify(credentials[role])};p.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('.login-card').requestSubmit()})()`);await until("!!document.querySelector('.conta-atual')")}
  async function tab(label){await evaluate(`[...document.querySelectorAll('.abas button')].find(b=>b.textContent.trim()===${JSON.stringify(label)}).click()`)}
  async function close(){try{await evaluate("document.querySelector('.conta-atual button')?.click()")}catch{}ws.send(JSON.stringify({id:++counter,method:'Browser.close'}))}
  await send('Page.enable');await send('Runtime.enable');await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});await send('Page.navigate',{url:'http://127.0.0.1:8080'})
  return {send,evaluate,until,login,tab,close,exceptions}
}
