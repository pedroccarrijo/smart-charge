import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({ html: false, linkify: false, breaks: true })
markdown.renderer.rules.image = () => ''
markdown.renderer.rules.link_open = () => '<span>'
markdown.renderer.rules.link_close = () => '</span>'
export const renderAnswer = (text: string): string => markdown.render(text)

export interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
  status?: 'loading' | 'streaming' | 'completed' | 'cancelled' | 'failed'
  contextAt?: string
  error?: string
  truncated?: boolean
}
export interface Conversation {
  id: string
  messages: ChatMessage[]
}
export const newConversation = (): Conversation => ({ id: crypto.randomUUID(), messages: [] })

export async function readEvents(
  body: ReadableStream<Uint8Array>,
  receive: (event: Record<string, unknown>) => void
): Promise<void> {
  const reader = body.getReader(),
    decoder = new TextDecoder()
  let pending = ''
  function line(value: string): void {
    if (!value.trim()) return
    const data = JSON.parse(value)
    if (!data || typeof data !== 'object' || typeof data.type !== 'string')
      throw new Error('Resposta inválida do assistente')
    receive(data)
  }
  try {
    while (true) {
      const { done, value } = await reader.read()
      pending += decoder.decode(value, { stream: !done })
      if (pending.length > 64000) throw new Error('Resposta do assistente excedeu o limite')
      const lines = pending.split('\n')
      pending = lines.pop() ?? ''
      for (const item of lines) line(item)
      if (done) {
        line(pending)
        return
      }
    }
  } finally {
    reader.releaseLock()
  }
}
