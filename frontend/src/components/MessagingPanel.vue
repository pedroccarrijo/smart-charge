<script setup lang="ts">
  import { computed, onBeforeUnmount, ref } from 'vue'
  import type { MessagingState } from '../messaging'
  const props = defineProps<{
    data: MessagingState
    connected: boolean
    canInspect: boolean
    api: (path: string, options?: RequestInit) => Promise<Response>
  }>()
  const now = ref(Date.now())
  const timer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
  onBeforeUnmount(() => window.clearInterval(timer))
  const current = computed(
    () =>
      props.connected &&
      props.data.available &&
      !!props.data.sampled_at &&
      now.value - Date.parse(props.data.sampled_at) < 15000
  )
  const preview = ref<
    { routing_key: string; payload: unknown; payload_bytes: number; redelivered: boolean }[]
  >([])
  const inspected = ref(false),
    inspecting = ref(false),
    error = ref('')
  const dlq = computed(() => props.data.queues.find((q) => q.name === 'deadletters'))
  const total = computed(() => props.data.queues.reduce((sum, q) => sum + q.messages, 0))
  const number = (n: number | undefined) =>
    n?.toLocaleString('pt-BR', { maximumFractionDigits: 1 }) ?? '—'
  async function inspect(): Promise<void> {
    inspecting.value = true
    error.value = ''
    try {
      preview.value = (
        await (await props.api('/api/messaging/dlq/peek', { method: 'POST', body: '{}' })).json()
      ).messages
      inspected.value = true
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Falha ao inspecionar a fila'
    } finally {
      inspecting.value = false
    }
  }
</script>

<template>
  <section class="painel-dados">
    <h2>Mensageria RabbitMQ</h2>
    <p>
      O backend consulta a API de gerenciamento; o navegador recebe somente os dados autorizados
      pelo WebSocket.
    </p>
    <p :class="current ? 'state-normal' : 'state-warning'" role="status">
      {{
        current
          ? 'Monitoramento conectado'
          : (data.error ?? 'Aguardando atualização do monitoramento')
      }}
    </p>
    <p v-if="data.sampled_at">
      Última consulta: {{ new Date(data.sampled_at).toLocaleTimeString('pt-BR') }} · As taxas usam a
      janela de estatísticas do broker.
    </p>
    <div class="bus-indicators">
      <div>
        <span>Mensagens nas filas</span><strong>{{ number(total) }}</strong>
      </div>
      <div>
        <span>Publicações no barramento / s</span
        ><strong>{{ number(data.rates.publish_in) }}</strong>
      </div>
      <div>
        <span>Consumidores</span><strong>{{ data.consumers.length }}</strong>
      </div>
      <div>
        <span>DLQ</span><strong>{{ number(dlq?.messages) }}</strong>
      </div>
    </div>
    <div class="tabela-scroll">
      <table>
        <thead>
          <tr>
            <th>Fila</th>
            <th>Prontas</th>
            <th>Sem confirmação</th>
            <th>Consumidores</th>
            <th>Entrada / s</th>
            <th>Entrega / s</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="queue in data.queues"
            :key="queue.name"
            :data-queue="queue.name"
            :class="{
              'queue-paused':
                queue.name !== 'deadletters' && queue.consumers === 0 && queue.messages > 0,
            }"
          >
            <td>{{ queue.name }}</td>
            <td>{{ number(queue.ready) }}</td>
            <td>{{ number(queue.unacknowledged) }}</td>
            <td>{{ queue.consumers }}</td>
            <td>{{ number(queue.publish_rate) }}</td>
            <td>{{ number(queue.delivery_rate) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p>
      Uma publicação pode gerar cópias em várias filas. A taxa de entrada de uma fila conta essas
      cópias; a taxa do barramento conta as publicações no exchange.
    </p>
  </section>
  <section class="painel-dados">
    <details>
      <summary>Serviços conectados e configurações de consumo</summary>
      <h3>Consumidores conectados</h3>
      <div class="tabela-scroll">
        <table>
          <thead>
            <tr>
              <th>Fila</th>
              <th>Conta do serviço</th>
              <th>Confirmação explícita</th>
              <th>Prefetch</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="consumer in data.consumers" :key="consumer.tag">
              <td>{{ consumer.queue }}</td>
              <td>{{ consumer.user }}</td>
              <td>{{ consumer.ack_required ? 'Sim' : 'Não' }}</td>
              <td>{{ consumer.prefetch }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>
  </section>
  <section class="painel-dados">
    <details>
      <summary>Ver mensagens recentes (detalhes técnicos)</summary>
      <h3>Mensagens recentes observadas pela API</h3>
      <p>
        Amostra em memória dos últimos 40 eventos recebidos ou publicados pela API; não é o
        histórico completo do broker.
      </p>
      <details
        v-for="message in data.recent"
        :key="`${message.id}:${message.observed_at}`"
        class="bus-message"
      >
        <summary>
          {{ new Date(message.observed_at).toLocaleTimeString('pt-BR') }} · {{ message.type }} ·
          {{ message.device_id ?? 'laboratório' }} · {{ message.routing_key }}
        </summary>
        <pre>{{ JSON.stringify(message.payload, null, 2) }}</pre>
      </details>
    </details>
  </section>
  <section class="painel-dados">
    <h3 id="messaging-dlq">Fila de mensagens mortas (DLQ)</h3>
    <p>
      Mensagens com falha permanecem na fila para diagnóstico. A prévia de até cinco mensagens as
      devolve à fila e pode alterar sua ordem.
    </p>
    <button v-if="canInspect" :disabled="inspecting || !current" @click="inspect">
      {{ inspecting ? 'Consultando…' : 'Inspecionar sem remover' }}
    </button>
    <p v-else>Operador e administrador podem inspecionar o conteúdo da DLQ.</p>
    <p v-if="error" role="alert" class="aviso-erro">{{ error }}</p>
    <p v-if="inspected && !preview.length">A DLQ está vazia.</p>
    <details v-for="(message, index) in preview" :key="index" class="bus-message">
      <summary>
        {{ message.routing_key }} · {{ message.payload_bytes }} bytes ·
        {{ message.redelivered ? 'Reentregue' : 'Primeira entrega' }}
      </summary>
      <pre>{{ JSON.stringify(message.payload, null, 2) }}</pre>
    </details>
  </section>
</template>

<style scoped>
  p {
    margin: 12px 0;
    line-height: 1.6;
    font-size: 13px;
  }
</style>
