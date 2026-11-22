// Run against an isolated Chrome with --remote-debugging-port=9223.
// Credentials stay in memory; screenshots/results go only to ignored secrets/.
import { readFileSync, writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import * as THREE from '../frontend/node_modules/three/build/three.module.js'

const root = fileURLToPath(new URL('../', import.meta.url))
const credentials = Object.fromEntries(readFileSync(new URL('../secrets/usuarios-demo.txt', import.meta.url), 'utf8').trim().split(/\r?\n/).map(line => {
  const split = line.indexOf(':'); return [line.slice(0, split), line.slice(split+1).trim()]
}))
const pause = ms => new Promise(resolve => setTimeout(resolve, ms))
let target
for (let i=0; i<40; i++) {
  try { target = await (await fetch('http://127.0.0.1:9223/json/new?about:blank', { method: 'PUT' })).json(); break } catch { await pause(250) }
}
if (!target) throw new Error('Chrome debugging endpoint unavailable')
const ws = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((resolve, reject) => { ws.onopen=resolve; ws.onerror=reject })
let counter=0
const pending = new Map(), exceptions=[], graphicsErrors=[]
ws.onmessage = event => {
  const data = JSON.parse(event.data)
  if (data.id && pending.has(data.id)) { pending.get(data.id)(data); pending.delete(data.id) }
  if (data.method === 'Runtime.exceptionThrown') exceptions.push(data.params.exceptionDetails.exception?.description ?? data.params.exceptionDetails.text)
  if (data.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(data.params.type)) graphicsErrors.push(data.params.args.map(a => a.value ?? a.description ?? '').join(' '))
}
function send(method, params={}) {
  const id=++counter
  return new Promise((resolve,reject) => {
    const timer=setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)) }, 20000)
    pending.set(id, data => { clearTimeout(timer); data.error ? reject(new Error(data.error.message)) : resolve(data.result) })
    ws.send(JSON.stringify({id,method,params}))
  })
}
async function evaluate(expression) {
  const result = await send('Runtime.evaluate', {expression,awaitPromise:true,returnByValue:true})
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description ?? result.exceptionDetails.text)
  return result.result.value
}
async function until(expression, timeout=30000) {
  const end=Date.now()+timeout
  while (Date.now()<end) { if (await evaluate(expression)) return; await pause(300) }
  throw new Error(`Browser condition timed out: ${expression}`)
}
async function login(role) {
  await until("!!document.querySelector('#usuario')")
  await evaluate(`(() => { const user=document.querySelector('#usuario'), pass=document.querySelector('#senha'); user.value=${JSON.stringify(role)}; user.dispatchEvent(new Event('input',{bubbles:true})); pass.value=${JSON.stringify(credentials[role])}; pass.dispatchEvent(new Event('input',{bubbles:true})); document.querySelector('.login-card').requestSubmit(); })()`)
  await until("!!document.querySelector('.conta-atual')")
  await evaluate("[...document.querySelectorAll('.abas button')].find(b=>b.textContent.includes('3D')).click()")
  await until("document.querySelectorAll('.twin-canvas canvas').length===1 && document.querySelectorAll('[data-component-id]').length===18")
  await until("document.querySelector('.twin-status')?.dataset.live==='true'")
  await evaluate("document.querySelector('.twin-viewport').scrollIntoView({block:'center'})")
}
async function canvasShot() {
  const rect=await evaluate("(() => {const r=document.querySelector('.twin-canvas').getBoundingClientRect(); return {x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height,scale:1}})()")
  return (await send('Page.captureScreenshot',{format:'png',clip:rect,captureBeyondViewport:true})).data
}
let simulatorStopped=false
try {
  await send('Page.enable'); await send('Runtime.enable')
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:Number(process.env.TWIN_DPR ?? 1),mobile:false})
  await send('Page.navigate',{url:'http://127.0.0.1:8080'})
  await login('visualizador')
  if (await evaluate("document.querySelectorAll('.twin-command button').length") !== 0) throw new Error('Viewer has command controls')
  if (!await evaluate("!!document.querySelector('.twin-canvas canvas').getContext('webgl2') && !document.querySelector('.twin-canvas canvas').getContext('webgl2').isContextLost()")) throw new Error('WebGL2 context unavailable')
  const pixelCount = () => evaluate("new Promise(resolve => requestAnimationFrame(() => {const source=document.querySelector('.twin-canvas canvas'), c=document.createElement('canvas');c.width=source.width;c.height=source.height;const ctx=c.getContext('2d');ctx.drawImage(source,0,0);const pixels=ctx.getImageData(0,0,c.width,c.height).data, colors=new Set();for(let i=0;i<pixels.length;i+=256)colors.add((pixels[i]<<16)|(pixels[i+1]<<8)|pixels[i+2]);resolve(colors.size)}))")
  if (await pixelCount() < 20) throw new Error('Canvas exists but the 3D is blank')
  await evaluate("[...document.querySelectorAll('.twin-toolbar button')].find(b=>b.textContent.includes('Recentrar')).click()")
  if (await pixelCount() < 20) throw new Error('Camera reset left the scene blank')
  await evaluate("[...document.querySelectorAll('.twin-toolbar button')].find(b=>b.textContent.includes('Modo compatível')).click()")
  await until("document.querySelectorAll('.twin-canvas canvas').length===1 && document.querySelector('.twin-canvas canvas').dataset.rendered==='true'")
  if (await pixelCount() < 20) throw new Error('Compatibility mode left the scene blank')
  await evaluate("[...document.querySelectorAll('.twin-toolbar button')].find(b=>b.textContent.includes('Reiniciar')).click()")
  await until("document.querySelectorAll('.twin-canvas canvas').length===1 && document.querySelector('.twin-canvas canvas').dataset.rendered==='true'")
  if (await pixelCount() < 20) throw new Error('Scene restart left the scene blank')
  const renderingError = await evaluate("document.querySelector('.twin-overlay[role=alert]')?.textContent ?? ''")
  if (renderingError) throw new Error(renderingError)
  await pause(500)
  const livePixels = () => evaluate("new Promise(resolve => requestAnimationFrame(() => resolve(document.querySelector('.twin-canvas canvas').toDataURL('image/png'))))")
  const movingBefore = await livePixels(); await pause(700)
  if (movingBefore === await livePixels()) throw new Error('Cena tem pixels, mas não anima com telemetria de recarga')
  console.log('PASS: pixels reais, animação com telemetria, câmera e reinicialização sem erro de renderização')
  await evaluate("document.querySelector('[data-component-id=\"ponto01.temperature\"]').click()")
  await until("document.querySelector('.twin-detail code')?.textContent==='ponto01.temperature' && !!document.querySelector('.twin-chart')")
  console.log('PASS: WebGL2, 18 componentes, painel/minigráfico e visualizador sem comandos')
  const rect=await evaluate("(() => {const r=document.querySelector('.twin-canvas canvas').getBoundingClientRect(); return {x:r.left,y:r.top,w:r.width,h:r.height}})()")
  const camera=new THREE.PerspectiveCamera(42,rect.w/rect.h,.1,100)
  camera.position.set(14,13,19); camera.lookAt(0,1,0); camera.updateMatrixWorld()
  const projected=new THREE.Vector3(0,1.3,-2.25).project(camera)
  const x=rect.x+(projected.x+1)/2*rect.w, y=rect.y+(-projected.y+1)/2*rect.h
  await send('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'left',clickCount:1})
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',x,y,button:'left',clickCount:1})
  await until("document.querySelector('.twin-detail code')?.textContent==='ponto02.module'")
  console.log('PASS: seleção real por raycast no canvas')
  writeFileSync(new URL('../secrets/twin-preview.png',import.meta.url),Buffer.from(await canvasShot(),'base64'))
  if (process.env.TWIN_DIAGNOSTIC === '1') {
    console.log(await evaluate("(() => {const c=document.querySelector('.twin-canvas canvas'), g=c.getContext('webgl2'), ext=g.getExtension('WEBGL_debug_renderer_info'); return {width:c.width,height:c.height,clientWidth:c.clientWidth,clientHeight:c.clientHeight,lost:g.isContextLost(),error:g.getError(),renderer:ext?g.getParameter(ext.UNMASKED_RENDERER_WEBGL):'unavailable'}})()"))
    console.log('Graphics warnings:', graphicsErrors)
    console.log('Runtime exceptions:', exceptions)
  } else {
  execFileSync('docker',['compose','stop','simulator'],{cwd:root,stdio:'pipe'}); simulatorStopped=true
  await until("document.querySelector('.twin-status')?.dataset.live==='false'",20000)
  if (await evaluate("[...document.querySelectorAll('[data-component-id]')].filter(b=>b.textContent.includes('Sem dados')).length") !== 18) throw new Error('Stale components still show live state')
  await evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve(true))))")
  await pause(700)
  const renderedPixels = () => evaluate("new Promise(resolve => requestAnimationFrame(() => resolve(document.querySelector('.twin-canvas canvas').toDataURL('image/png'))))")
  const frozen=await renderedPixels(); await pause(1200)
  const after=await renderedPixels()
  if (frozen !== after) {
    writeFileSync(new URL('../secrets/twin-frozen-before.png',import.meta.url),Buffer.from(frozen.split(',')[1],'base64'))
    writeFileSync(new URL('../secrets/twin-frozen-after.png',import.meta.url),Buffer.from(after.split(',')[1],'base64'))
    throw new Error('Scene continued to animate without telemetry')
  }
  console.log('PASS: simulador parado sinaliza sem dados e congela os pixels da cena')
  execFileSync('docker',['compose','start','simulator'],{cwd:root,stdio:'pipe'}); simulatorStopped=false
  await until("document.querySelector('.twin-status')?.dataset.live==='true'",30000)
  await evaluate("document.querySelector('.conta-atual button').click()")
  await login('operador')
  await evaluate("document.querySelector('[data-component-id=\"ponto03.contactor\"]').click()")
  await until("!!document.querySelector('.twin-command button:not(:disabled)')")
  const original=await evaluate("document.querySelector('.twin-reading').textContent.trim()")
  await evaluate("document.querySelector('.twin-command button').click()")
  await until(`document.querySelector('.twin-reading')?.textContent.trim()!==${JSON.stringify(original)} && !!document.querySelector('.twin-command button:not(:disabled)')`)
  await evaluate("document.querySelector('.twin-command button').click()")
  await until(`document.querySelector('.twin-reading')?.textContent.trim()===${JSON.stringify(original)} && !!document.querySelector('.twin-command button:not(:disabled)')`)
  console.log('PASS: operador comanda o contator pelo painel 3D e estado original restaurado')
  if (await evaluate("!!document.querySelector('.twin-overlay[role=alert]')")) throw new Error('Erro tratado no loop 3D não pode passar despercebido')
  if (exceptions.length) throw new Error(exceptions.join('\n'))
  console.log('PASS: nenhuma exceção JavaScript durante os testes')
  }
} finally {
  if (simulatorStopped) execFileSync('docker',['compose','start','simulator'],{cwd:root,stdio:'pipe'})
  try { await evaluate("document.querySelector('.conta-atual button')?.click()") } catch {}
  ws.send(JSON.stringify({id:++counter,method:'Browser.close'}))
}
