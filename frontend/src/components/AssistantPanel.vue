<script setup lang="ts">
  import { onBeforeUnmount, onMounted, ref } from 'vue'
  import {
    newConversation,
    readEvents,
    renderAnswer,
    type Conversation,
    type ChatMessage,
  } from '../assistant'

  const props = defineProps<{
    conversation: Conversation
    api: (path: string, options?: RequestInit) => Promise<Response>
  }>()
  const emit = defineEmits<{ reset: [conversation: Conversation] }>()
  const question = ref(''),
    busy = ref(false),
    notice = ref(''),
    service = ref('Consultando modelo local…')
  let controller: AbortController | null = null
  const suggestions = [
    'Resuma o estado atual das três estações.',
    'Explique os alertas ativos e a vida útil prevista.',
    'Como os modelos se comparam ao baseline?',
    'Explique o caminho dos dados no projeto.',
  ]

  async function checkStatus(): Promise<void> {
    try {
      const state = await (await props.api('/api/assistant/status')).json()
      service.value = !state.available
        ? 'Ollama indisponível'
        : !state.downloaded
          ? 'Modelo local ainda não foi baixado'
          : `${state.model} · ${state.loaded ? 'carregado' : 'carregará na primeira pergunta'}`
    } catch {
      service.value = 'Não foi possível consultar o Ollama'
    }
  }
  function stop(): void {
    controller?.abort()
  }
  function clear(): void {
    if (!busy.value) {
      emit('reset', newConversation())
      notice.value = ''
    }
  }
  async function ask(text = question.value): Promise<void> {
    text = text.trim()
    if (!text || busy.value) return
    question.value = ''
    notice.value = ''
    busy.value = true
    props.conversation.messages.push(
      { role: 'user', text },
      { role: 'assistant', text: '', status: 'loading' }
    )
    const answer = props.conversation.messages[props.conversation.messages.length - 1]!
    controller = new AbortController()
    try {
      const response = await props.api('/api/assistant/chat', {
        method: 'POST',
        signal: controller.signal,
        body: JSON.stringify({ question: text, conversation_id: props.conversation.id }),
      })
      if (!response.body) throw new Error('O navegador não recebeu a resposta em fluxo')
      let terminal = false
      await readEvents(response.body, (event) => {
        if (event.type === 'context' && typeof event.snapshot_at === 'string')
          answer.contextAt = event.snapshot_at
        if (event.type === 'token' && typeof event.text === 'string') {
          answer.status = 'streaming'
          answer.text = (answer.text + event.text).slice(0, 12000)
        }
        if (event.type === 'error') {
          terminal = true
          answer.status = 'failed'
          answer.error =
            typeof event.message === 'string' ? event.message : 'Falha no assistente local'
        }
        if (event.type === 'done') {
          terminal = true
          answer.status = 'completed'
          answer.truncated = event.truncated === true
        }
      })
      if (!terminal) throw new Error('A conexão terminou antes de concluir a resposta')
    } catch (e) {
      answer.status = controller.signal.aborted ? 'cancelled' : 'failed'
      if (answer.status === 'failed')
        answer.error = e instanceof Error ? e.message : 'Falha ao consultar o assistente'
    } finally {
      busy.value = false
      controller = null
    }
  }
  const time = (value: string): string => new Date(value).toLocaleString('pt-BR')
  const stateLabel = (message: ChatMessage): string =>
    message.status === 'loading'
      ? 'Preparando dados e carregando o modelo local…'
      : message.status === 'streaming'
        ? 'Respondendo…'
        : message.status === 'cancelled'
          ? 'Resposta interrompida por você.'
          : message.truncated
            ? 'Resposta atingiu o limite de tamanho. Faça uma pergunta mais específica para continuar.'
            : ''
  onMounted(checkStatus)
  onBeforeUnmount(stop)
</script>

<template>
  <section class="painel-dados assistant-panel">
    <h2>Assistente local</h2>
    <p>
      Consulte as leituras, previsões, alertas e resultados do treinamento. O assistente usa Ollama
      no seu computador e não executa comandos nos equipamentos.
    </p>
    <p class="muted">{{ service }} · Consultas auditadas · Até cinco perguntas por minuto</p>
    <p class="muted">
      Respostas de IA podem conter erros. Confira valores no Dashboard e em Insights de IA. As
      previsões são baseadas em dados sintéticos.
    </p>
    <div class="suggestions">
      <button
        v-for="suggestion in suggestions"
        :key="suggestion"
        :disabled="busy"
        @click="ask(suggestion)"
      >
        {{ suggestion }}
      </button>
    </div>
    <div class="conversation" aria-label="Conversa com o assistente" aria-live="off">
      <p v-if="!conversation.messages.length" class="muted">
        Faça uma pergunta ou selecione uma sugestão. A primeira resposta pode demorar enquanto o
        modelo é carregado.
      </p>
      <article
        v-for="(message, index) in conversation.messages"
        :key="index"
        :class="['chat-message', message.role]"
      >
        <strong>{{ message.role === 'user' ? 'Você' : 'Smart Charge' }}</strong>
        <p v-if="message.role === 'user'" class="user-question">{{ message.text }}</p>
        <div v-else class="answer" v-html="renderAnswer(message.text)"></div>
        <p v-if="message.contextAt" class="muted">
          Dados consultados em {{ time(message.contextAt) }}.
        </p>
        <p v-if="stateLabel(message)" role="status">{{ stateLabel(message) }}</p>
        <p v-if="message.error" role="alert" class="error">{{ message.error }}</p>
      </article>
    </div>
    <form @submit.prevent="ask()">
      <label for="assistant-question">Sua pergunta</label>
      <textarea
        id="assistant-question"
        v-model="question"
        maxlength="1200"
        rows="3"
        :disabled="busy"
        placeholder="Qual estação precisa de atenção?"
        required
      ></textarea>
      <div class="chat-actions">
        <button type="submit" :disabled="busy || !question.trim()">Perguntar</button>
        <button v-if="busy" type="button" @click="stop">Interromper resposta</button>
        <button type="button" :disabled="busy || !conversation.messages.length" @click="clear">
          Nova conversa
        </button>
        <span class="muted">{{ question.length }}/1200</span>
      </div>
    </form>
    <p v-if="notice" role="status">{{ notice }}</p>
  </section>
</template>

<style scoped>
  .assistant-panel {
    padding: 22px;
  }
  p {
    margin: 12px 0;
    line-height: 1.55;
  }
  .muted {
    color: #a4aa9a;
    font-size: 0.85rem;
  }
  .suggestions,
  .chat-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
    margin: 18px 0;
  }
  .conversation {
    margin: 20px 0;
    max-height: 580px;
    overflow-y: auto;
  }
  .chat-message {
    padding: 16px 20px;
    border: 1px solid #34382e;
    border-radius: 12px;
    margin: 14px 0;
    overflow-wrap: anywhere;
  }
  .chat-message.user {
    background: #2a321d;
  }
  .chat-message.assistant {
    background: #171a13;
  }
  .user-question {
    white-space: pre-wrap;
  }
  textarea {
    display: block;
    width: 100%;
    box-sizing: border-box;
    margin-top: 10px;
    padding: 12px;
    resize: vertical;
    background: #151713;
    color: #f5f6ef;
    border: 1px solid #515c41;
    border-radius: 8px;
    font: inherit;
  }
  .answer {
    line-height: 1.65;
  }
  .answer :deep(pre) {
    overflow: auto;
  }
  .error {
    color: #ff8f83;
  }
</style>
