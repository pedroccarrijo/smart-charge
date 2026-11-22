import test from 'node:test'
import assert from 'node:assert/strict'
import { readEvents, renderAnswer } from '../src/assistant.ts'

test('respostas aceitam Markdown sem HTML ativo, imagens ou links navegáveis', () => {
  const html = renderAnswer(
    '**Saúde** <script>alert(1)</script> <img src="http://remote/test"> ![x](https://remote/image) [link](javascript:alert(1)) [site](https://remote)'
  )
  assert.match(html, /<strong>Saúde<\/strong>/)
  assert.doesNotMatch(html, /<script|<img|<a[ >]/i)
  assert.match(html, /&lt;script&gt;/)
})

test('NDJSON preserva UTF-8 e eventos divididos entre pacotes', async () => {
  const bytes = new TextEncoder().encode('{"type":"token","text":"Tensão"}\n{"type":"done"}\n')
  const body = new ReadableStream({
    start(controller) {
      for (const byte of bytes) controller.enqueue(Uint8Array.of(byte))
      controller.close()
    },
  })
  const events: Record<string, unknown>[] = []
  await readEvents(body, (event) => events.push(event))
  assert.deepEqual(events, [{ type: 'token', text: 'Tensão' }, { type: 'done' }])
})

test('NDJSON inválido produz erro explícito', async () => {
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('oops\n'))
      controller.close()
    },
  })
  await assert.rejects(readEvents(body, () => {}))
})
