import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { writeFileSync } from 'node:fs'
import { browserSession,credentials } from './browser-helper.mjs'

const root=fileURLToPath(new URL('../',import.meta.url))
async function api(path,method='GET',body,token) {
  const response=await fetch('http://127.0.0.1:8080'+path,{method,headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:body===undefined?undefined:JSON.stringify(body)})
  if(!response.ok)throw new Error(`HTTP ${response.status}: ${path}`)
  return response.json()
}
const auth=await api('/api/auth/login','POST',{username:'administrador',password:credentials.administrador})
const original=await api('/api/catalog','GET',undefined,auth.access_token)
const device=original.devices.find(row=>row.id==='ponto03'),sensor=original.components.find(row=>row.id==='ponto01.temperature')
const browser=await browserSession()
const {send,evaluate,until,login,tab}=browser
let stopped=false
try {
  await login('administrador');await tab('Mensageria')
  await until("document.querySelectorAll('[data-queue]').length===7 && document.body.textContent.includes('Monitoramento conectado')")
  await evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Inspecionar sem remover')).click()")
  await until("document.querySelector('#messaging-dlq').parentElement.querySelector('details') || document.querySelector('#messaging-dlq').parentElement.textContent.includes('DLQ está vazia')")
  console.log('PASS: painel mostra filas/consumidores e inspeciona a DLQ')
  execFileSync('docker',['compose','stop','writer'],{cwd:root,stdio:'pipe'});stopped=true
  await until("(()=>{const cells=document.querySelector('[data-queue=\"writer.telemetry\"]')?.querySelectorAll('td');return cells&&cells[3].textContent==='0'&&parseInt(cells[1].textContent)>0})()",30000)
  console.log('PASS: fila cresce e indica consumidor parado na tela')
  writeFileSync(new URL('../secrets/messaging-preview.png',import.meta.url),Buffer.from((await send('Page.captureScreenshot',{format:'png'})).data,'base64'))
  execFileSync('docker',['compose','start','writer'],{cwd:root,stdio:'pipe'});stopped=false
  await until("(()=>{const cells=document.querySelector('[data-queue=\"writer.telemetry\"]')?.querySelectorAll('td');return cells&&cells[3].textContent==='1'&&parseInt(cells[1].textContent)===0})()",30000)
  console.log('PASS: consumidor retorna e a fila drena na tela')
  await tab('Dispositivos')
  await until("!!document.querySelector('[data-edit-device=\"ponto03\"]')")
  await evaluate("document.querySelector('[data-edit-device=\"ponto03\"]').click()")
  await evaluate("(()=>{const input=document.querySelector('.catalog-form input');input.value='Estação validada no navegador';input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('.catalog-form').requestSubmit()})()")
  await until("!document.querySelector('.catalog-form') && document.body.textContent.includes('Estação validada no navegador')")
  await tab('Dashboard')
  await until("[...document.querySelectorAll('.card-estacao h3')].some(h=>h.textContent==='Estação validada no navegador')")
  await tab('Dispositivos')
  await evaluate("document.querySelector('[data-edit-component=\"ponto01.temperature\"]').click()")
  await evaluate("(()=>{const label=[...document.querySelectorAll('.catalog-form label')].find(l=>l.textContent.includes('Normal máximo')),input=label.querySelector('input');input.value='10';input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('.catalog-form').requestSubmit()})()")
  await until("!document.querySelector('.catalog-form')")
  await tab('Gêmeo digital 3D')
  await until("document.querySelector('[data-component-id=\"ponto01.temperature\"]')?.classList.contains('state-warning')")
  console.log('PASS: nome chega ao dashboard e faixa do sensor muda a cor no 3D via WebSocket')
  await evaluate("document.querySelector('.conta-atual button').click()")
  await login('visualizador');await tab('Dispositivos')
  await until("document.body.textContent.includes('Seu papel permite consultar o cadastro')")
  if(await evaluate("document.querySelectorAll('[data-edit-device],[data-edit-component]').length"))throw new Error('Viewer has edit controls')
  await tab('Mensageria')
  if(await evaluate("[...document.querySelectorAll('button')].some(b=>b.textContent.includes('Inspecionar sem remover'))"))throw new Error('Viewer has DLQ inspector')
  if(browser.exceptions.length)throw new Error(browser.exceptions.join('\n'))
  console.log('PASS: visualizador sem controles de edição/DLQ; nenhuma exceção JavaScript')
} finally {
  if(stopped)execFileSync('docker',['compose','start','writer'],{cwd:root,stdio:'pipe'})
  const current=await api('/api/catalog','GET',undefined,auth.access_token)
  const latestDevice=current.devices.find(row=>row.id===device.id),latestSensor=current.components.find(row=>row.id===sensor.id)
  await api('/api/catalog/devices/'+device.id,'PUT',{name:device.name,location:device.location,description:device.description,commands_enabled:device.commands_enabled,revision:latestDevice.revision},auth.access_token)
  await api('/api/catalog/components/'+sensor.id,'PUT',{name:sensor.name,normal_min:sensor.normal_min,normal_max:sensor.normal_max,critical_min:sensor.critical_min,critical_max:sensor.critical_max,revision:latestSensor.revision},auth.access_token)
  await api('/api/auth/logout','POST',{},auth.access_token)
  await browser.close()
  console.log('Cadastros originais restaurados')
}
