<script setup lang="ts">
  import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
  import { Chart, ArcElement, DoughnutController, Legend, Tooltip } from 'chart.js'
  import LabPanel from './components/LabPanel.vue'
  import type { LabState } from './lab'
  import InsightsPanel from './components/InsightsPanel.vue'
  import type { InsightsState } from './insights'
  import type { ChargingPoint as Ponto, DeviceComponent, Catalog } from './twin'
  import type { MessagingState } from './messaging'
  import MessagingPanel from './components/MessagingPanel.vue'
  import DeviceManager from './components/DeviceManager.vue'
  import AssistantPanel from './components/AssistantPanel.vue'
  import { newConversation } from './assistant'
  import SensorHistory from './components/SensorHistory.vue'
  import ChargeIllustration from './components/ChargeIllustration.vue'
  const DigitalTwin = defineAsyncComponent(() => import('./components/DigitalTwin.vue'))

  Chart.register(ArcElement, DoughnutController, Legend, Tooltip)

  type StatusPonto = 'DISPONIVEL' | 'EM USO' | 'SEM DADOS'

  interface HistoricoItem {
    ponto: string
    status: StatusPonto
    horario: string | null
  }

  const pontos = ref<Ponto[]>([
    { ponto: '01', status: 'SEM DADOS', horario: null },
    { ponto: '02', status: 'SEM DADOS', horario: null },
    { ponto: '03', status: 'SEM DADOS', horario: null },
  ])
  const historico = ref<HistoricoItem[]>([])
  const erro = ref('')
  const graficoCanvas = ref<HTMLCanvasElement | null>(null)
  let grafico: Chart<'doughnut'> | null = null
  interface Usuario {
    username: string
    role: 'visualizador' | 'operador' | 'administrador'
  }
  interface Sessao {
    id: string
    device_id: string
    status: string
    battery_percent: number
    energy_kwh: number
    started_at: string
  }
  interface Comando {
    id: string
    device_id: string
    status: string
  }
  interface Auditoria {
    id: number
    created_at: string
    username: string | null
    action: string
    device_id: string | null
  }
  const usuario = ref<Usuario | null>(null)
  const token = ref('')
  const aba = ref<
    'dashboard' | 'laboratorio' | 'insights' | 'twin' | 'messaging' | 'devices' | 'assistant'
  >('dashboard')
  const conversation = ref(newConversation())
  const historyOpen = ref(false)
  const pageInfo = computed(
    () =>
      ({
        dashboard: [
          'Estações de carregamento',
          'Veja a disponibilidade, a bateria e o andamento das recargas.',
        ],
        insights: [
          'Manutenção preditiva',
          'Acompanhe a saúde dos módulos de potência e os alertas.',
        ],
        twin: ['Gêmeo digital', 'Explore as três estações e seus componentes em tempo real.'],
        assistant: ['Assistente local', 'Tire dúvidas sobre as leituras e previsões do sistema.'],
        laboratorio: [
          'Laboratório de dados',
          'Gere dados sintéticos e treine os modelos de previsão.',
        ],
        messaging: ['Mensageria', 'Acompanhe o caminho das mensagens entre os serviços.'],
        devices: ['Dispositivos', 'Consulte as estações e configure seus componentes.'],
      })[aba.value]
  )
  const cadastro = ref<Catalog>({ devices: [], components: [] })
  const mensageria = ref<MessagingState>({
    available: false,
    error: null,
    sampled_at: null,
    queues: [],
    consumers: [],
    rates: {},
    recent: [],
  })
  const componentes = ref<DeviceComponent[]>([])
  const socketConnected = ref(false)
  const socketFrameAt = ref(0)
  const insights = ref<InsightsState>({ devices: [], alerts: [], active_model_id: null })
  const laboratorio = ref<LabState>({ jobs: [], models: [] })
  const pontosOnline = computed(() =>
    socketConnected.value ? pontos.value.filter((p) => p.online && p.telemetry) : []
  )
  const potenciaAtual = computed(() =>
    pontosOnline.value.reduce((sum, p) => sum + (p.telemetry?.power_kw ?? 0), 0)
  )
  const alertasAtivos = computed(() => insights.value.alerts.filter((a) => a.active).length)
  const loginUsuario = ref('visualizador')
  const loginSenha = ref('')
  const entrando = ref(false)
  const sessoes = ref<Sessao[]>([])
  const comandos = ref<Comando[]>([])
  const auditoria = ref<Auditoria[]>([])
  const mostrarAuditoria = ref(false)
  const mensagem = ref('')
  const erroComando = ref('')
  const comandoAguardado = ref<string | null>(null)
  const enviando = ref<string | null>(null)
  const limites = ref<Record<string, number>>({ '01': 100, '02': 100, '03': 100 })
  const podeComandar = computed(
    () => usuario.value?.role === 'operador' || usuario.value?.role === 'administrador'
  )
  let socket: WebSocket | null = null
  let reconectar: number | undefined

  function limparSessao(): void {
    historyOpen.value = false
    conversation.value = newConversation()
    usuario.value = null
    token.value = ''
    socketConnected.value = false
    socketFrameAt.value = 0
    componentes.value = []
    cadastro.value = { devices: [], components: [] }
    mensageria.value = {
      available: false,
      error: null,
      sampled_at: null,
      queues: [],
      consumers: [],
      rates: {},
      recent: [],
    }
    aba.value = 'dashboard'
    laboratorio.value = { jobs: [], models: [] }
    insights.value = { devices: [], alerts: [], active_model_id: null }
    window.clearTimeout(reconectar)
    socket?.close()
    socket = null
    sessoes.value = []
    comandos.value = []
    auditoria.value = []
    mostrarAuditoria.value = false
    pontos.value = ['01', '02', '03'].map((ponto) => ({
      ponto,
      status: 'SEM DADOS',
      horario: null,
    }))
    historico.value = []
    erroComando.value = ''
    comandoAguardado.value = null
    grafico?.destroy()
    grafico = null
  }

  async function api(path: string, options: RequestInit = {}): Promise<Response> {
    const response = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token.value}`,
        ...options.headers,
      },
    })
    if (!response.ok) {
      if (response.status === 401) limparSessao()
      const body = await response.json().catch(() => ({}))
      throw new Error(
        typeof body.detail === 'string' ? body.detail : 'Não foi possível concluir a operação'
      )
    }
    return response
  }

  async function entrar(): Promise<void> {
    entrando.value = true
    erro.value = ''
    mensagem.value = ''
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: loginUsuario.value, password: loginSenha.value }),
      })
      const body = await response.json()
      if (!response.ok)
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Login inválido')
      token.value = body.access_token
      usuario.value = body.user
      loginSenha.value = ''
      cadastro.value = await (await api('/api/catalog')).json()
      componentes.value = cadastro.value.components
      await atualizarDashboard()
      await ligarRealtime()
    } catch (e) {
      erro.value = e instanceof Error ? e.message : 'Falha no login'
    } finally {
      entrando.value = false
    }
  }

  async function sair(): Promise<void> {
    try {
      await api('/api/auth/logout', { method: 'POST' })
    } finally {
      limparSessao()
      erro.value = ''
      mensagem.value = ''
    }
  }

  async function ligarRealtime(): Promise<void> {
    if (!token.value) return
    const response = await api('/api/auth/ws-ticket', { method: 'POST' })
    const { ticket } = await response.json()
    if (!token.value) return
    const connection = new WebSocket(
      `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/ws`
    )
    socket = connection
    connection.onopen = () => connection.send(JSON.stringify({ ticket }))
    connection.onmessage = async (message) => {
      if (socket !== connection || !usuario.value) return
      const data = JSON.parse(message.data)
      socketConnected.value = true
      socketFrameAt.value = Date.now()
      pontos.value = data.pontos
      historico.value = data.historico
      sessoes.value = data.sessions
      comandos.value = data.commands
      laboratorio.value = data.lab ?? { jobs: [], models: [] }
      insights.value = data.insights ?? { devices: [], alerts: [], active_model_id: null }
      if (data.catalog) {
        cadastro.value = data.catalog
        componentes.value = data.catalog.components
      }
      if (data.messaging) mensageria.value = data.messaging
      const aguardado = comandos.value.find((c) => c.id === comandoAguardado.value)
      if (aguardado && ['applied', 'expired'].includes(aguardado.status)) {
        mensagem.value =
          aguardado.status === 'applied'
            ? 'Comando confirmado pelo atuador.'
            : 'Comando expirou sem confirmação do atuador.'
        comandoAguardado.value = null
      }
      erro.value = data.consumer_online ? '' : 'Reconectando ao barramento de mensagens'
      await nextTick()
      atualizarGrafico()
    }
    connection.onclose = () => {
      if (socket !== connection || !token.value) return
      socketConnected.value = false
      erro.value = 'Conexão em tempo real interrompida. Reconectando…'
      pontos.value = pontos.value.map((ponto) => ({
        ...ponto,
        status: 'SEM DADOS',
        telemetry: null,
      }))
      atualizarGrafico()
      agendarReconexao()
    }
  }

  function agendarReconexao(): void {
    window.clearTimeout(reconectar)
    if (!token.value) return
    reconectar = window.setTimeout(() => {
      ligarRealtime().catch((e) => {
        erro.value = e.message
        agendarReconexao()
      })
    }, 3000)
  }

  function ocupado(ponto: Ponto): boolean {
    return (
      enviando.value === ponto.ponto ||
      comandos.value.some(
        (c) => c.device_id === `ponto${ponto.ponto}` && ['pending', 'published'].includes(c.status)
      )
    )
  }
  function comandoIndisponivel(ponto: Ponto): boolean {
    return !ponto.telemetry || ponto.commands_enabled === false || ocupado(ponto)
  }

  async function comandar(ponto: Ponto, action: string, value: boolean | number): Promise<void> {
    enviando.value = ponto.ponto
    mensagem.value = ''
    erroComando.value = ''
    try {
      const response = await api(`/api/devices/ponto${ponto.ponto}/commands`, {
        method: 'POST',
        body: JSON.stringify({ action, value }),
      })
      const result = await response.json()
      comandos.value.unshift({ id: result.id, device_id: `ponto${ponto.ponto}`, status: 'pending' })
      comandoAguardado.value = result.id
      mensagem.value = `Comando enviado para a estação ${ponto.ponto}. Aguardando confirmação pela telemetria.`
    } catch (e) {
      erroComando.value = e instanceof Error ? e.message : 'Falha ao enviar comando'
    } finally {
      enviando.value = null
    }
  }

  async function abrirAuditoria(): Promise<void> {
    aba.value = 'dashboard'
    await carregarAuditoria()
  }

  async function carregarAuditoria(): Promise<void> {
    try {
      auditoria.value = await (await api('/api/audit')).json()
      mostrarAuditoria.value = true
    } catch (e) {
      erro.value = e instanceof Error ? e.message : 'Falha ao consultar auditoria'
    }
  }

  function textoSessao(status: string): string {
    return (
      (
        {
          charging: 'Carregando',
          paused: 'Pausada',
          completed: 'Concluída',
          ended: 'Encerrada',
        } as Record<string, string>
      )[status] ?? status
    )
  }

  const disponiveis = computed(() => pontos.value.filter((p) => p.status === 'DISPONIVEL').length)
  const emUso = computed(() => pontos.value.filter((p) => p.status === 'EM USO').length)
  const semDados = computed(() => pontos.value.filter((p) => p.status === 'SEM DADOS').length)

  function formatarHorario(dataISO: string | null): string {
    if (!dataISO) return '--:--:--'
    return new Date(dataISO).toLocaleTimeString('pt-BR', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }

  function formatarNumero(valor: number, casas = 1): string {
    return valor.toLocaleString('pt-BR', {
      minimumFractionDigits: casas,
      maximumFractionDigits: casas,
    })
  }

  function conclusao(ponto: Ponto): string {
    if (!ponto.telemetry?.occupied) return 'Sem veículo'
    if (ponto.telemetry && ponto.telemetry.battery_percent >= 100) return 'Concluída'
    const minutos = ponto.telemetry?.estimated_minutes
    if (minutos == null || !ponto.horario) return 'Recarga inativa'
    return `${Math.ceil(minutos)} min · ${formatarHorario(new Date(new Date(ponto.horario).getTime() + minutos * 60000).toISOString())}`
  }

  function classeStatus(status: StatusPonto): string {
    if (status === 'DISPONIVEL') return 'disponivel'
    if (status === 'EM USO') return 'ocupado'
    return 'carregando'
  }

  function textoStatus(status: StatusPonto): string {
    return status === 'DISPONIVEL' ? 'DISPONÍVEL' : status
  }

  function descricaoStatus(status: StatusPonto): string {
    if (status === 'DISPONIVEL') return 'Ponto livre para carregamento.'
    if (status === 'EM USO') return 'Veículo detectado no ponto de recarga.'
    return 'Nenhuma informação disponível.'
  }

  function atualizarGrafico(): void {
    if (!graficoCanvas.value) return
    const data = [disponiveis.value, emUso.value, semDados.value]

    if (grafico) {
      grafico.data.datasets[0].data = data
      grafico.update()
      return
    }

    grafico = new Chart(graficoCanvas.value, {
      type: 'doughnut',
      data: {
        labels: ['Disponíveis', 'Em uso', 'Sem dados'],
        datasets: [
          {
            data,
            backgroundColor: ['#ccff00', '#6f8050', '#555b4b'],
            borderColor: '#1c1e1a',
            borderWidth: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '70%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: { color: '#b9c5a3', padding: 18, usePointStyle: true },
          },
        },
      },
    })
  }

  async function atualizarDashboard(): Promise<void> {
    try {
      const [resStatus, resHistorico] = await Promise.all([
        api('/api/status'),
        api('/api/historico'),
      ])

      if (!resStatus.ok || !resHistorico.ok) throw new Error('Falha ao consultar a API')

      const novosPontos = (await resStatus.json()) as Ponto[]
      const novoHistorico = (await resHistorico.json()) as HistoricoItem[]

      if (!Array.isArray(novosPontos) || !Array.isArray(novoHistorico)) {
        throw new Error('Formato inesperado da API')
      }

      pontos.value = novosPontos
      historico.value = novoHistorico
      erro.value = ''
      await nextTick()
      atualizarGrafico()
    } catch (e) {
      console.error(e)
      erro.value = 'Não foi possível atualizar os dados. Verifique o backend.'
    }
  }

  onMounted(() => {
    atualizarGrafico()
  })

  onBeforeUnmount(() => {
    window.clearTimeout(reconectar)
    socket?.close()
    grafico?.destroy()
  })
</script>

<template>
  <header class="topo">
    <div class="marca">
      <div class="logo" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <path d="m14 2-9 12h6l-1 8 9-13h-6l1-7Z" fill="currentColor" />
        </svg>
      </div>
      <div>
        <h1>smartcharge<span class="brand-dot">.</span></h1>
        <p>Energia conectada. Decisões melhores.</p>
      </div>
    </div>
    <div v-if="usuario" class="conta-atual">
      <span
        >{{ usuario.username
        }}<template v-if="usuario.username.toLowerCase() !== usuario.role">
          · {{ usuario.role }}</template
        ></span
      ><button @click="sair">Sair</button>
    </div>
    <div v-else class="sistema-online">Acesso autenticado</div>
  </header>

  <main v-if="!usuario" class="container login-container">
    <aside class="login-intro">
      <span class="eyebrow">MONITORAMENTO INTELIGENTE</span>
      <h2>A próxima carga.<br /><span>Sob controle.</span></h2>
      <p>Três estações conectadas. Uma visão clara da recarga e da saúde de cada módulo.</p>
      <div class="login-art"><ChargeIllustration /></div>
      <div class="login-tags">
        <span>Tempo real</span><span>Manutenção preditiva</span><span>Ambiente simulado</span>
      </div>
    </aside>
    <form class="login-card" @submit.prevent="entrar">
      <span class="eyebrow">SEU PAINEL DE OPERAÇÃO</span>
      <h2>Entrar no Smart Charge</h2>
      <p>Use as credenciais geradas na instalação.</p>
      <details class="login-help">
        <summary>Primeiro acesso? Veja como obter as senhas</summary>
        <p>Após subir o Docker Compose, execute na pasta do projeto:</p>
        <strong>Windows · PowerShell</strong>
        <pre><code>powershell -ExecutionPolicy Bypass -File .\infra\export-demo-credentials.ps1</code></pre>
        <strong>Linux / macOS · terminal</strong>
        <pre><code>mkdir -p secrets
docker compose run --rm --no-deps db-init python -m services.show_credentials &gt; secrets/usuarios-demo.txt</code></pre>
        <p>
          Abra <code>secrets/usuarios-demo.txt</code>. Escolha uma conta e cole no campo Senha
          somente o texto depois de <code>:</code> na linha correspondente.
        </p>
        <p>
          As contas são <strong>visualizador</strong>, <strong>operador</strong> e
          <strong>administrador</strong>. Para testar todas as funções, use administrador. Cada
          instalação tem suas próprias senhas.
        </p>
      </details>
      <label for="usuario">Usuário</label>
      <input id="usuario" v-model="loginUsuario" autocomplete="username" required maxlength="64" />
      <label for="senha">Senha</label>
      <input
        id="senha"
        v-model="loginSenha"
        type="password"
        autocomplete="current-password"
        required
        maxlength="72"
      />
      <p v-if="erro" role="alert" class="aviso-erro">{{ erro }}</p>
      <button :disabled="entrando" type="submit">{{ entrando ? 'Entrando…' : 'Entrar' }}</button>
      <small>Contas: visualizador, operador e administrador.</small>
    </form>
  </main>

  <main v-else class="container">
    <section class="titulo-pagina" :class="{ 'dashboard-heading': aba === 'dashboard' }">
      <p class="subtitulo">SMART CHARGE · AMBIENTE SIMULADO</p>
      <h2>{{ pageInfo[0] }}</h2>
      <p>{{ pageInfo[1] }}</p>
      <p class="estado-conexao">
        {{
          erro
            ? 'Reconectando ao sistema…'
            : semDados === pontos.length
              ? 'Aguardando leituras das estações…'
              : 'Dados ao vivo'
        }}
      </p>
      <button v-if="usuario.role === 'administrador'" @click="abrirAuditoria">
        Consultar auditoria
      </button>
    </section>

    <p v-if="erro" class="aviso-erro">{{ erro }}</p>
    <p v-if="mensagem" class="aviso-comando" role="status">{{ mensagem }}</p>
    <p v-if="erroComando" class="aviso-erro" role="alert">{{ erroComando }}</p>

    <nav class="abas" aria-label="Seções da aplicação">
      <button :aria-pressed="aba === 'dashboard'" @click="aba = 'dashboard'">Dashboard</button>
      <button :aria-pressed="aba === 'insights'" @click="aba = 'insights'">Insights de IA</button>
      <button :aria-pressed="aba === 'twin'" @click="aba = 'twin'">Gêmeo digital 3D</button>
      <button :aria-pressed="aba === 'assistant'" @click="aba = 'assistant'">
        Assistente local
      </button>
      <button :aria-pressed="aba === 'laboratorio'" @click="aba = 'laboratorio'">
        Laboratório e treinamento
      </button>
      <button :aria-pressed="aba === 'messaging'" @click="aba = 'messaging'">Mensageria</button>
      <button :aria-pressed="aba === 'devices'" @click="aba = 'devices'">Dispositivos</button>
    </nav>
    <LabPanel
      v-if="aba === 'laboratorio'"
      :lab="laboratorio"
      :administrator="usuario.role === 'administrador'"
      :api="api"
    />
    <InsightsPanel v-if="aba === 'insights'" :data="insights" />
    <MessagingPanel
      v-if="aba === 'messaging'"
      :data="mensageria"
      :connected="socketConnected"
      :can-inspect="podeComandar"
      :api="api"
    />
    <DeviceManager
      v-if="aba === 'devices'"
      :catalog="cadastro"
      :administrator="usuario.role === 'administrador'"
      :api="api"
    />
    <AssistantPanel
      v-if="aba === 'assistant'"
      :conversation="conversation"
      :api="api"
      @reset="conversation = $event"
    />
    <DigitalTwin
      v-if="aba === 'twin'"
      :points="pontos"
      :components="componentes"
      :insights="insights"
      :connected="socketConnected"
      :frame-at="socketFrameAt"
      :can-command="podeComandar"
      :busy="pontos.filter(ocupado).map((p) => `ponto${p.ponto}`)"
      @command="(ponto, action, value) => comandar(ponto, action, value)"
    />
    <div v-show="aba === 'dashboard'">
      <section class="overview-grid" aria-label="Resumo das estações">
        <article class="charge-hero">
          <div class="hero-copy">
            <span class="eyebrow">CONECTADO AO QUE IMPORTA</span>
            <h2>Mais energia.<br /><span>Menos incerteza.</span></h2>
            <p>Da próxima recarga à saúde dos módulos. Tudo no mesmo lugar.</p>
            <button @click="aba = 'insights'">
              Ver saúde dos módulos <span aria-hidden="true">↗</span>
            </button>
          </div>
          <ChargeIllustration />
          <span class="hero-footnote"
            >SMART CHARGE / {{ String(pontos.length).padStart(2, '0') }} ESTAÇÕES</span
          >
        </article>
        <div class="overview-stats">
          <article class="metric-card">
            <span class="metric-index">01 / CONEXÃO</span
            ><strong>{{ pontosOnline.length }}<small> / 3</small></strong
            ><span>Estações online</span>
            <div class="connection-dots" aria-hidden="true">
              <i
                v-for="point in pontos"
                :key="point.ponto"
                :class="{ online: socketConnected && point.online }"
              ></i>
            </div>
          </article>
          <article class="metric-card">
            <span class="metric-index">02 / DISPONIBILIDADE</span
            ><strong>{{ pontosOnline.length ? disponiveis : '—' }}<small> vagas</small></strong
            ><span>Prontas para receber</span>
          </article>
          <article class="metric-card">
            <span class="metric-index">03 / POTÊNCIA MEDIDA</span
            ><strong
              >{{ pontosOnline.length ? formatarNumero(potenciaAtual) : '—'
              }}<small> kW</small></strong
            ><span>Somente estações online</span>
          </article>
          <article class="metric-card" :class="{ 'metric-alert': alertasAtivos > 0 }">
            <span class="metric-index">04 / MANUTENÇÃO</span
            ><strong>{{ socketConnected ? alertasAtivos : '—' }}<small> alertas</small></strong
            ><button class="text-action" @click="aba = 'insights'">
              Acompanhar saúde <span aria-hidden="true">↗</span>
            </button>
          </article>
        </div>
      </section>
      <div class="section-heading">
        <div>
          <span class="eyebrow">OPERAÇÃO AO VIVO</span>
          <h2>Suas estações.</h2>
        </div>
        <span class="section-caption">{{ pontosOnline.length }}/3 com leituras disponíveis</span>
      </div>
      <section class="estacoes">
        <article v-for="ponto in pontos" :key="ponto.ponto" class="card-estacao">
          <div class="card-topo">
            <div>
              <span class="identificador">PONTO DE RECARGA</span>
              <h3>{{ ponto.display_name ?? `Estação ${ponto.ponto}` }}</h3>
            </div>
            <span class="numero-estacao">{{ ponto.ponto }}</span>
          </div>
          <div class="area-status" :class="classeStatus(ponto.status)">
            <div class="icone-status">⚡</div>
            <span class="status-label">STATUS ATUAL</span>
            <strong>{{ textoStatus(ponto.status) }}</strong>
            <p>{{ descricaoStatus(ponto.status) }}</p>
          </div>
          <div class="ultima-atualizacao">
            <span>Última atualização</span>
            <strong>{{ formatarHorario(ponto.horario) }}</strong>
          </div>
          <div v-if="ponto.telemetry" class="telemetria">
            <dl>
              <div>
                <dt>Potência de entrada</dt>
                <dd>{{ formatarNumero(ponto.telemetry.power_kw) }} kW</dd>
              </div>
              <div>
                <dt>Bateria</dt>
                <dd>
                  {{
                    ponto.telemetry.occupied
                      ? `${formatarNumero(ponto.telemetry.battery_percent)}%`
                      : 'Sem veículo'
                  }}
                </dd>
              </div>
              <div class="battery-meter">
                <progress
                  v-if="ponto.telemetry.occupied"
                  :value="ponto.telemetry.battery_percent"
                  max="100"
                  :aria-label="`Bateria da estação ${ponto.ponto}`"
                ></progress>
              </div>
              <div>
                <dt>Energia fornecida</dt>
                <dd>{{ formatarNumero(ponto.telemetry.energy_kwh, 3) }} kWh</dd>
              </div>
            </dl>
            <p v-if="ponto.telemetry.automatic_limit_active" class="protecao-termica">
              Proteção térmica ativa
            </p>
            <p v-if="ponto.telemetry.occupied" class="estimativa">
              Conclusão estimada: {{ conclusao(ponto) }}
            </p>
            <p v-else class="estimativa">Vaga livre · aguardando veículo.</p>
            <small
              :class="{ 'layout-placeholder': !ponto.telemetry.occupied }"
              :aria-hidden="!ponto.telemetry.occupied"
              >Estimativa pela potência atual; pode variar durante a recarga.</small
            >
            <details class="technical-details">
              <summary>Sensores e proteção</summary>
              <dl>
                <div>
                  <dt>Temperatura</dt>
                  <dd>{{ formatarNumero(ponto.telemetry.temperature_c) }} °C</dd>
                </div>
                <div>
                  <dt>Corrente</dt>
                  <dd>{{ formatarNumero(ponto.telemetry.current_a) }} A</dd>
                </div>
                <div>
                  <dt>Tensão</dt>
                  <dd>{{ formatarNumero(ponto.telemetry.voltage_v) }} V</dd>
                </div>
                <div>
                  <dt>Contator</dt>
                  <dd>{{ ponto.telemetry.contactor_on ? 'Fechado' : 'Aberto' }}</dd>
                </div>
                <div>
                  <dt>Potência permitida</dt>
                  <dd>{{ formatarNumero(ponto.telemetry.power_limit_percent, 0) }}%</dd>
                </div>
              </dl>
              <p>A proteção limita a potência a 30% em 65 °C e libera em 55 °C.</p>
            </details>
          </div>
          <div v-if="podeComandar" class="controles">
            <p v-if="ponto.commands_enabled === false">
              Novos comandos bloqueados pelo administrador no cadastro.
            </p>
            <button
              :disabled="comandoIndisponivel(ponto)"
              @click="comandar(ponto, 'set_contactor', !ponto.telemetry?.contactor_on)"
            >
              {{ ponto.telemetry?.contactor_on ? 'Pausar recarga' : 'Permitir recarga' }}
            </button>
            <details class="simulation-controls">
              <summary>Controles da simulação</summary>
              <button
                :disabled="comandoIndisponivel(ponto)"
                @click="comandar(ponto, 'set_occupied', !ponto.telemetry?.occupied)"
              >
                {{ ponto.telemetry?.occupied ? 'Liberar vaga' : 'Simular veículo' }}
              </button>
              <label :for="`limite-${ponto.ponto}`">Limite solicitado de potência</label>
              <select
                :id="`limite-${ponto.ponto}`"
                v-model.number="limites[ponto.ponto]"
                :disabled="comandoIndisponivel(ponto)"
              >
                <option v-for="limite in [100, 75, 50, 25, 0]" :key="limite" :value="limite">
                  {{ limite }}%
                </option>
              </select>
              <button
                :disabled="comandoIndisponivel(ponto)"
                @click="comandar(ponto, 'set_power_limit', limites[ponto.ponto] ?? 100)"
              >
                Aplicar limite
              </button>
              <div class="acoes-falha">
                <button
                  :disabled="comandoIndisponivel(ponto)"
                  @click="comandar(ponto, 'set_fault', 100)"
                >
                  Injetar falha
                </button>
                <button
                  :disabled="comandoIndisponivel(ponto)"
                  @click="comandar(ponto, 'set_fault', 0)"
                >
                  Remover falha
                </button>
              </div>
              <p>
                Uma falha altera temperatura, corrente e tensão gradualmente. Remover a falha inicia
                a recuperação; os alertas levam algumas leituras para encerrar.
              </p>
            </details>
            <small v-if="ocupado(ponto)">Aguardando confirmação do atuador…</small>
          </div>
        </article>
      </section>

      <section class="painel-inferior">
        <article class="card-historico historico-geral">
          <div class="historico-topo">
            <div>
              <span class="identificador">ATIVIDADE</span>
              <h3>Histórico recente</h3>
            </div>
            <span class="icone-historico">↻</span>
          </div>
          <div class="lista-historico">
            <p v-if="historico.length === 0" class="carregando-historico">
              Nenhum registro encontrado.
            </p>
            <div
              v-for="(item, index) in historico"
              :key="`${item.ponto}-${item.horario}-${index}`"
              class="item-historico"
            >
              <div class="evento">
                <span
                  class="indicador"
                  :class="item.status === 'EM USO' ? 'vermelho' : 'verde'"
                ></span>
                <div>
                  <strong>{{ item.status === 'EM USO' ? 'Em uso' : 'Disponível' }}</strong>
                  <p>Ponto {{ item.ponto }}</p>
                </div>
              </div>
              <span class="hora-evento">{{ formatarHorario(item.horario) }}</span>
            </div>
          </div>
        </article>

        <article class="card-grafico">
          <div class="historico-topo">
            <div>
              <span class="identificador">VISUALIZAÇÃO</span>
              <h3>Ocupação atual</h3>
            </div>
            <span class="icone-historico">◉</span>
          </div>
          <div class="grafico-area"><canvas ref="graficoCanvas"></canvas></div>
          <div class="resumo-grafico">
            <span
              ><b>{{ disponiveis }}</b> disponíveis</span
            >
            <span
              ><b>{{ emUso }}</b> em uso</span
            >
          </div>
        </article>
      </section>

      <details
        class="history-section"
        @toggle="historyOpen = ($event.target as HTMLDetailsElement).open"
      >
        <summary>Consultar histórico dos sensores</summary>
        <SensorHistory v-if="historyOpen" :api="api" />
      </details>
      <details class="painel-dados">
        <summary>Sessões de recarga</summary>
        <h3>Sessões de recarga</h3>
        <p v-if="!sessoes.length">Aguardando sessões.</p>
        <div class="tabela-scroll" v-else>
          <table>
            <thead>
              <tr>
                <th>Estação</th>
                <th>Estado</th>
                <th>Bateria</th>
                <th>Energia fornecida</th>
                <th>Início</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="sessao in sessoes" :key="sessao.id">
                <td>{{ sessao.device_id }}</td>
                <td>{{ textoSessao(sessao.status) }}</td>
                <td>{{ formatarNumero(sessao.battery_percent) }}%</td>
                <td>{{ formatarNumero(sessao.energy_kwh, 3) }} kWh</td>
                <td>{{ formatarHorario(sessao.started_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
      <section v-if="mostrarAuditoria && usuario.role === 'administrador'" class="painel-dados">
        <h3>Auditoria</h3>
        <button @click="carregarAuditoria">Atualizar registros</button>
        <div class="tabela-scroll">
          <table>
            <thead>
              <tr>
                <th>Horário</th>
                <th>Usuário</th>
                <th>Ação</th>
                <th>Dispositivo</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="registro in auditoria" :key="registro.id">
                <td>{{ formatarHorario(registro.created_at) }}</td>
                <td>{{ registro.username ?? 'Desconhecido' }}</td>
                <td>{{ registro.action }}</td>
                <td>{{ registro.device_id ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </main>

  <footer>
    <span>⚡ Smart Charge</span>
    <p>Sistema inteligente de monitoramento de pontos de recarga</p>
  </footer>
</template>
