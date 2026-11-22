import { writeFileSync } from 'node:fs'
import { browserSession, pause } from './browser-helper.mjs'

const browser = await browserSession()
const { evaluate, until, send } = browser
try {
  await browser.login('visualizador')
  await browser.tab('Assistente local')
  await until("document.querySelector('.assistant-panel')?.textContent.includes('qwen2.5')")
  await evaluate(`(()=>{const input=document.querySelector('#assistant-question');input.value='Em duas frases, explique o caminho dos dados da simulação até a interface.';input.dispatchEvent(new Event('input',{bubbles:true}));input.form.requestSubmit()})()`)
  await until("!![...document.querySelectorAll('button')].find(b=>b.textContent==='Interromper resposta')")
  await until("!!document.querySelector('.answer')?.textContent.trim()", 160000)
  console.log('PASS: resposta do Ollama começou a aparecer no Chrome')
  await until("![...document.querySelectorAll('button')].find(b=>b.textContent==='Interromper resposta')", 160000)
  const result = await evaluate(`({text:document.querySelector('.answer').textContent, errors:[...document.querySelectorAll('.chat-message .error')].map(e=>e.textContent), remoteNodes:document.querySelectorAll('.answer img,.answer a,.answer script,.answer iframe').length, context:document.querySelector('.assistant-panel').textContent.includes('Dados consultados em')})`)
  if (result.errors.length || result.text.length < 40 || result.remoteNodes || !result.context) throw new Error(JSON.stringify(result))
  const screenshot = await send('Page.captureScreenshot', {format:'png'})
  writeFileSync(new URL('../secrets/assistant-preview.png', import.meta.url), Buffer.from(screenshot.data, 'base64'))
  await browser.tab('Dashboard'); await browser.tab('Assistente local')
  if (!await evaluate("document.querySelector('.answer')?.textContent.length>40")) throw new Error('Conversa se perdeu ao trocar de aba')
  await evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='Nova conversa').click()")
  await until("!document.querySelector('.chat-message')")
  await evaluate(`(()=>{const input=document.querySelector('#assistant-question');input.value='Explique todas as etapas da arquitetura e do treinamento detalhadamente.';input.dispatchEvent(new Event('input',{bubbles:true}));input.form.requestSubmit()})()`)
  await until("!![...document.querySelectorAll('button')].find(b=>b.textContent==='Interromper resposta')")
  await pause(1000)
  await evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent==='Interromper resposta').click()")
  await until("document.querySelector('.conversation').textContent.includes('Resposta interrompida por você')")
  await send('Page.navigate', { url: 'http://127.0.0.1:8080' })
  await until("!!document.querySelector('#usuario')")
  // Refresh intentionally loses JWT and conversation; sign in with another role.
  await browser.login('operador')
  await browser.tab('Assistente local')
  if (await evaluate("!!document.querySelector('.chat-message')")) throw new Error('Conversa vazou entre sessões')
  if (browser.exceptions.length) throw new Error(browser.exceptions.join('\n'))
  console.log('PASS: contexto datado, conversa entre abas, cancelamento e isolamento entre sessões')
} finally { await browser.close() }
